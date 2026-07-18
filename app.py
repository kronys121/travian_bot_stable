"""
Travian Bot Dashboard — GUI для управления ботом в реальном времени.

Запуск:
    uvicorn app:app --port 8000
    (из той же папки, где лежит runner.py)

Возможности:
  - Настройки каждого аккаунта на лету (bot_settings_{name}.json)
  - Менеджер аккаунтов: добавить/изменить/удалить (accounts_gui.json)
  - Старт/Стоп каждого аккаунта НЕЗАВИСИМО (отдельный процесс runner.py --account)
  - Подбор сервера: парсинг списка игровых миров Travian + проверка сервера
"""
import logging
import os
from utils.paths import account_file
import re
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from utils.settings_store import SettingsStore
from utils.i18n import translate_logs
from utils.accounts import (
    load_accounts, get_account, upsert_gui_account,
    delete_gui_account, is_yaml_account,
)
from telegram_miniapp import MINIAPP_HTML
from utils.commands import push_command

app = FastAPI(title="Travian Bot Dashboard", version="4.0")


# ======= ПРОЦЕССЫ АККАУНТОВ =======
# Каждый аккаунт = отдельный процесс `python runner.py --account <name>`.
# Полная независимость: старт/стоп одного не влияет на другие.

_processes: dict[str, subprocess.Popen] = {}

_PIDS_DIR = Path("pids")


def _pid_file(name: str) -> Path:
    return _PIDS_DIR / f"{name}.pid"


def _pid_alive(pid: int) -> bool:
    """Проверяет, жив ли процесс с данным PID (кроссплатформенно)."""
    try:
        if os.name == 'nt':
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False


def _orphan_pid(name: str) -> int | None:
    """PID процесса-сироты (запущен прошлым GUI, всё ещё жив)."""
    pf = _pid_file(name)
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
    except Exception:
        pf.unlink(missing_ok=True)
        return None
    if _pid_alive(pid):
        return pid
    pf.unlink(missing_ok=True)  # мёртвый PID-файл — чистим
    return None


def proc_running(name: str) -> bool:
    p = _processes.get(name)
    if p is not None and p.poll() is None:
        return True
    # Процесс мог быть запущен предыдущим экземпляром GUI
    return _orphan_pid(name) is not None


def start_account(name: str) -> bool:
    if proc_running(name):
        return False
    Path("logs").mkdir(exist_ok=True)
    _PIDS_DIR.mkdir(exist_ok=True)
    out = open(f"logs/{name}_process.log", "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "runner.py", "--account", name],
        stdout=out, stderr=subprocess.STDOUT,
        cwd=str(Path(__file__).parent),
    )
    _processes[name] = proc
    try:
        _pid_file(name).write_text(str(proc.pid))
    except Exception as e:
        logging.debug(f"pid file write: {e}")
    return True


def stop_account(name: str) -> bool:
    """
    Останавливает процесс бота и сбрасывает status-файл.
    Убивает как управляемый процесс, так и сироту из PID-файла.
    """
    p = _processes.get(name)
    killed = False
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        killed = True

    # Сирота от предыдущего экземпляра GUI
    orphan = _orphan_pid(name)
    if orphan is not None:
        try:
            if os.name == 'nt':
                subprocess.run(["taskkill", "/PID", str(orphan), "/T", "/F"],
                               capture_output=True)
            else:
                os.kill(orphan, 15)  # SIGTERM
            killed = True
        except Exception as e:
            logging.debug(f"orphan kill: {e}")

    _pid_file(name).unlink(missing_ok=True)

    # Убираем из таблицы процессов в любом случае
    _processes.pop(name, None)

    # Сбрасываем status-файл чтобы GUI перестал считать бота живым.
    # is_alive() смотрит на поле "alive" + свежесть "last_heartbeat",
    # поэтому гасим именно "alive" и обнуляем heartbeat (иначе после
    # принудительного закрытия PyCharm лампочка оставалась зелёной).
    status_path = account_file(name, 'status')
    if status_path.exists():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            data["alive"] = False
            data["running"] = False
            data["last_heartbeat"] = None
            data["last_action"] = "Остановлен из GUI"
            status_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logging.debug("suppressed error in app:95", exc_info=True)

    return True  # всегда успех — бот точно не работает после вызова


# ======= ДАННЫЕ =======

def load_status(name: str) -> dict:
    p = account_file(name, 'status')
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logging.debug("suppressed error in app:108", exc_info=True)
    return {}


def load_stats(name: str) -> dict:
    """Статистика аккаунта (ресурсы/войска/герой/атаки) из stats-файла.
    Дополняется статистикой фарма (набеги/юниты/оазисы) из farm_stats-файла."""
    p = account_file(name, 'stats')
    stats = {}
    try:
        if p.exists():
            stats = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logging.debug("suppressed error in app:119", exc_info=True)
    farm = load_farm_stats(name)
    if farm:
        stats["farm"] = farm
    return stats


def load_farm_stats(name: str) -> dict:
    """Читает накопленную статистику фарма (data/<acc>/farm_stats.json)."""
    p = account_file(name, 'farm_stats')
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logging.debug("suppressed error: farm_stats read", exc_info=True)
    return {}


def is_alive(status: dict) -> bool:
    """Живой = heartbeat не старше 5 минут и alive=True."""
    if not status.get("alive"):
        return False
    hb = status.get("last_heartbeat")
    if not hb:
        return False
    try:
        delta = (datetime.now() - datetime.fromisoformat(hb)).total_seconds()
        return delta < 300
    except Exception:
        return False


def get_store(name: str) -> SettingsStore:
    acc = get_account(name)
    if acc is None:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    return SettingsStore(name, acc)


def get_last_logs(account_name: str, lines: int = 150) -> list[str]:
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = Path(f"logs/{account_name}_{date_str}.log")
    if not log_file.exists():
        log_file = Path(f"logs/{account_name}_process.log")
        if not log_file.exists():
            return []
    try:
        return log_file.read_text(encoding="utf-8").splitlines()[-lines:]
    except Exception:
        return []


# ======= API: АККАУНТЫ =======

@app.get("/api/accounts")
async def api_accounts():
    out = []
    for acc in load_accounts():
        name = acc.get("name", "")
        status = load_status(name)
        out.append({
            "name": name,
            "server": acc.get("server", ""),
            "email": acc.get("email", "") or "",
            "has_password": bool(acc.get("password")),
            "rate": acc.get("rate", 3),
            "headless": acc.get("headless", True),
            "proxy": acc.get("proxy", "") or "",
            "from_yaml": is_yaml_account(name),
            "running": proc_running(name) or is_alive(status),
            "managed": name in _processes,   # процессом управляет этот GUI
            "status": {
                "alive": is_alive(status),
                "last_action": status.get("last_action", "Не запущен"),
                "current_village": status.get("current_village", "—"),
                "last_heartbeat": status.get("last_heartbeat"),
            },
            "stats": load_stats(name),
            "settings": get_store(name).get_all(),
            "build_progress": _load_build_progress(name),
        })
    return JSONResponse(content=out)


def _load_build_progress(name: str) -> dict:
    """Читает файл прогресса стройки: {village_key: step}."""
    try:
        p = account_file(name, 'build_progress')
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logging.debug("suppressed error in app:196", exc_info=True)
    return {}


@app.post("/api/accounts")
async def api_add_account(data: dict):
    """
    Добавить/обновить аккаунт из GUI. Поля:
      name (обяз.), server (обяз.), email, password, rate, headless
    Пароль хранится в accounts_gui.json.
    Альтернатива: оставь password пустым и задай в .env
      TRAVIAN_EMAIL_<NAME> / TRAVIAN_PASSWORD_<NAME>
    """
    name = (data.get("name") or "").strip()
    server = (data.get("server") or "").strip()
    if not name or not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        raise HTTPException(400, "Имя: только буквы/цифры/_- без пробелов")
    if not server:
        raise HTTPException(400, "Укажи сервер (например ts30.x3.international.travian.com)")

    server = re.sub(r"^https?://", "", server).strip("/")
    allowed = {"name", "server", "email", "password", "rate", "headless", "proxy", "build_template"}
    clean = {k: v for k, v in data.items() if k in allowed}
    clean["server"] = server
    if "proxy" in clean:
        clean["proxy"] = (clean["proxy"] or "").strip()
    # Путь до куков не хардкодим — runner берёт его из utils.paths (data/<acc>/)
    if "rate" in clean:
        clean["rate"] = int(clean["rate"])
    # Проверяем что шаблон существует; дефолт x3
    from config.build_templates import TEMPLATES
    bt = clean.get("build_template", "x3")
    if bt not in TEMPLATES:
        bt = "x3"
    clean["build_template"] = bt

    acc = upsert_gui_account(clean)
    return {"ok": True, "account": {"name": acc["name"], "server": acc["server"]}}


@app.delete("/api/accounts/{name}")
async def api_delete_account(name: str):
    if proc_running(name):
        stop_account(name)
    if is_yaml_account(name):
        raise HTTPException(400, "Аккаунт задан в config.yaml — удали его из файла вручную")
    if not delete_gui_account(name):
        raise HTTPException(404, "Аккаунт не найден")
    return {"ok": True}


@app.put("/api/accounts/{name}")
async def api_update_account(name: str, data: dict):
    """Обновляет подключение (rate/headless/proxy) и опционально settings из мини-аппа."""
    acc = get_account(name)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    # подключение
    conn_allowed = {"rate", "headless", "proxy"}
    patch = {k: v for k, v in data.items() if k in conn_allowed}
    if "proxy" in patch:
        patch["proxy"] = (patch["proxy"] or "").strip()
    if patch:
        upsert_gui_account(name, {**acc, **patch})
    # settings (farm/training/trade/features) — если переданы
    if "settings" in data and isinstance(data["settings"], dict):
        allowed_sections = {"features", "farm", "training", "trade", "build", "smithy", "task_order"}
        clean = {k: v for k, v in data["settings"].items()
                 if k in allowed_sections and isinstance(v, dict)}
        if clean:
            get_store(name).save(clean)
    return {"ok": True}


@app.post("/api/accounts/{name}/start")
async def api_start(name: str):
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    if proc_running(name):
        raise HTTPException(409, "��же запущен из этого GUI")
    if is_alive(load_status(name)):
        raise HTTPException(409, "Бот уже работает (запущен вне GUI, напр. через runner.py)")
    start_account(name)
    return {"ok": True}


@app.post("/api/accounts/{name}/stop")
async def api_stop(name: str):
    stop_account(name)  # всегда возвращает True, 409 больше не кидаем
    return {"ok": True}


@app.post("/api/accounts/{name}/scan")
async def api_scan(name: str):
    """П���инудительный полный скан карты: ставит команду в очередь бота."""
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    if not (proc_running(name) or is_alive(load_status(name))):
        raise HTTPException(409, "Бот не запущен — скан невозможен")
    if not push_command(name, "scan"):
        raise HTTPException(500, "Не удалось поставить команду")
    return {"ok": True}


@app.post("/api/accounts/{name}/reset_build")
async def api_reset_build(name: str):
    """Сбрасывает прогресс стройки аккаунта на шаг 1 (все деревни)."""
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    try:
        from services.smart_builder import SmartBuilder

        class _FakeConfig:
            pass

        cfg = _FakeConfig()
        cfg.name = name
        sb = SmartBuilder.__new__(SmartBuilder)
        sb._progress_path = account_file(name, 'build_progress')
        sb.reset_progress(village_key=None)
    except Exception as e:
        raise HTTPException(500, f"Ошибка сброса прогресса: {e}")
    return {"ok": True}


@app.post("/api/accounts/{name}/rescan")
async def api_rescan(name: str):
    """Быстрый перескан известных оазисов: ставит команду в очередь бота."""
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    if not (proc_running(name) or is_alive(load_status(name))):
        raise HTTPException(409, "Бот не запущен — перескан невозможен")
    if not push_command(name, "rescan"):
        raise HTTPException(500, "Не удалось поставить команду")
    return {"ok": True}


@app.post("/api/accounts/{name}/force_farm")
async def api_force_farm(name: str):
    """Принудительная атака войсками: сбрасывает счётчик и фармит немедленно."""
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    if not (proc_running(name) or is_alive(load_status(name))):
        raise HTTPException(409, "Бот не запущен — фарм невозможен")
    if not push_command(name, "force_farm"):
        raise HTTPException(500, "Не удалось поставить команду")
    return {"ok": True}


# ======= API: СЕРВЕРЫ =======

_servers_cache: dict = {"ts": 0, "list": []}


@app.get("/api/servers")
async def api_servers():
    """
    Список игровых миров Travian: парсим публичные страницы.
    Кэш 10 минут. Если не получилось — возвращаем пустой список,
    сервер всегда можно вписать вручную.
    """
    import time as _t
    if _t.time() - _servers_cache["ts"] < 600 and _servers_cache["list"]:
        return JSONResponse(content={"servers": _servers_cache["list"], "cached": True})

    found: set[str] = set()
    pages = [
        "https://www.travian.com/international",
        "https://www.travian.com/",
    ]
    for url in pages:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            # ловим и ts30.x3.international.travian.com, и ts5.travian.ru и т.п.
            for m in re.finditer(r"https?://((?:[a-z0-9\-]+\.)+travian\.[a-z.]+)", resp.text):
                host = m.group(1).lower()
                if re.match(r"^ts\d+\.", host) or ".x" in host.split(".")[0]:
                    found.add(host)
        except Exception:
            continue

    servers = sorted(found)
    if servers:
        _servers_cache["ts"] = _t.time()
        _servers_cache["list"] = servers
    return JSONResponse(content={"servers": servers, "cached": False})


@app.get("/api/servers/check")
async def api_server_check(host: str):
    """Проверка: сервер существует и отвечает как Travian."""
    host = re.sub(r"^https?://", "", host).strip("/")
    try:
        resp = requests.get(
            f"https://{host}/", timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True,
        )
        ok = resp.status_code == 200
        looks_travian = "travian" in resp.text.lower() or "travian" in str(resp.url).lower()
        return {"ok": ok and looks_travian, "status_code": resp.status_code,
                "final_url": str(resp.url)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ======= API: ��АСТРОЙКИ =======

@app.get("/api/accounts/{name}/settings")
async def api_get_settings(name: str):
    return JSONResponse(content=get_store(name).get_all())


@app.post("/api/accounts/{name}/settings")
async def api_save_settings(name: str, updates: dict):
    allowed_sections = {"features", "farm", "training", "trade", "build", "smithy", "task_order"}
    clean = {k: v for k, v in updates.items() if k in allowed_sections and isinstance(v, dict)}
    if not clean:
        raise HTTPException(status_code=400, detail="Нет валидных настроек")
    store = get_store(name)
    store.save(clean)
    return {"ok": True, "settings": store.get_all()}


@app.get("/api/accounts/{name}/logs")
async def api_logs(name: str, lines: int = 150):
    return JSONResponse(content={"lines": get_last_logs(name, lines)})


# ======= UI =======

# HTML дашборда вынесен в static/dashboard.html
DASHBOARD_HTML = (Path(__file__).parent / "static" / "dashboard.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/miniapp", response_class=HTMLResponse)
async def telegram_miniapp():
    """Telegram Mini App — открывается внутри Telegram через WebApp кнопку."""
    return HTMLResponse(content=MINIAPP_HTML)


@app.get("/account/{name}/logs", response_class=HTMLResponse)
async def account_logs(name: str, lines: int = 150, lang: str = "ru"):
    lang = "en" if lang == "en" else "ru"
    log_lines = translate_logs(get_last_logs(name, lines), lang)
    # экранируем на случай сп��цсимволов HTML в строках лога
    from html import escape as _esc
    empty_txt = "Log is empty" if lang == "en" else "Лог пуст"
    log_html = "\n".join(_esc(ln) for ln in log_lines) if log_lines else empty_txt

    t = {
        "ru": {"title": "Логи", "back": "Дашбо��д", "refresh": "автообновление каждые 10 с",
               "toggle": "English", "other": "en"},
        "en": {"title": "Logs", "back": "Dashboard", "refresh": "auto-refresh every 10s",
               "toggle": "Русский", "other": "ru"},
    }[lang]
    html = f"""<!DOCTYPE html><html lang="{lang}"><head>
    <title>{t['title']}: {name}</title><meta charset="utf-8">
    <meta http-equiv="refresh" content="10">
    <style>
      body {{ font-family: ui-monospace, Consolas, monospace; background: #0f1115; color: #c9cfda; padding: 20px; font-size: 12px; }}
      h2 {{ color: #e94560; margin-bottom: 8px; }}
      a {{ color: #e94560; }}
      .lang-btn {{ display: inline-block; margin-left: 12px; padding: 3px 10px; border: 1px solid #e94560;
                   border-radius: 6px; text-decoration: none; font-size: 12px; }}
      pre {{ background: #171a21; border: 1px solid #2a2f3a; padding: 15px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }}
    </style></head><body>
    <h2>{t['title']}: {name}</h2>
    <p><a href="/">&larr; {t['back']}</a> · {t['refresh']}
       <a class="lang-btn" href="/account/{name}/logs?lines={lines}&lang={t['other']}">{t['toggle']}</a></p>
    <pre>{log_html}</pre>
    </body></html>"""
    return HTMLResponse(content=html)


@app.get("/api/accounts/{name}/farm_stats")
async def api_farm_stats(name: str):
    """Сырая статистика фарма для страницы с графиками."""
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    return JSONResponse(content=load_farm_stats(name))


@app.get("/account/{name}/farm", response_class=HTMLResponse)
async def account_farm(name: str):
    """Страница с интерактивными графиками статистики фарма."""
    html = (Path(__file__).parent / "static" / "farm.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html.replace("__ACCOUNT__", name))


@app.on_event("shutdown")
def shutdown_processes():
    """При остановке GUI гасим только процессы, запущенные из GUI."""
    for name in list(_processes):
        stop_account(name)
