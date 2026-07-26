"""
Travian Bot Dashboard — GUI для управления ботом в реальном времени.

Запуск:
    uvicorn app:app --host 127.0.0.1 --port 8000
    (из той же папки, где лежит runner.py)

Доступ: если в .env задан DASHBOARD_TOKEN, каждый запрос должен нести его
в заголовке X-Auth-Token или в параметре ?token=... . Без переменной
дашборд открыт всем, кто дотянется до порта (см. предупреждение в логе).

Возможности:
  - Настройки каждого аккаунта на лету (data/<acc>/settings.json)
  - Менеджер аккаунтов: добавить/изменить/удалить (accounts_gui.json)
  - Старт/Стоп каждого аккаунта НЕЗАВИСИМО (отдельный процесс runner.py --account)
  - Подбор сервера: парсинг списка игровых миров Travian + проверка сервера
"""
import hmac
import ipaddress
import logging
import os
import re
import socket
import sys
import json
import subprocess
from contextlib import asynccontextmanager
from html import escape as _esc
from pathlib import Path
from datetime import datetime
from urllib.parse import quote as _urlquote

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from utils.jsonio import file_lock, read_json, write_json
from utils.paths import (
    account_file, is_valid_account_name, log_file, pid_file, process_log_file,
)
from utils.settings_store import SettingsStore
from utils.i18n import translate_logs
from utils.accounts import (
    load_accounts, get_account, upsert_gui_account,
    delete_gui_account, is_yaml_account,
)
from telegram_miniapp import MINIAPP_HTML
from utils.commands import push_command


# ======= АУТЕНТИФИКАЦИЯ =======
# Раньше на дашборде не было НИКАКОЙ проверки: любой, кто дотянулся до порта,
# мог остановить бота, удалить аккаунт и прочитать прокси вместе с паролем.
# Секрет берётся из переменной окружения DASHBOARD_TOKEN (.env).
# load_dotenv тут обязателен: runner.py и main.py его зовут, а дашборд — нет,
# и токен из .env просто не доезжал бы до процесса uvicorn.
load_dotenv()

DASHBOARD_TOKEN = (os.getenv("DASHBOARD_TOKEN") or "").strip()

if not DASHBOARD_TOKEN:
    logging.warning(
        "⚠️ DASHBOARD_TOKEN не задан — дашборд работает БЕЗ пароля. "
        "Любой, кто дотянется до порта, сможет остановить бота, удалить аккаунт "
        "и увидеть прокси с паролем. Перед тем как открывать порт наружу задай "
        "DASHBOARD_TOKEN в .env (и запускай uvicorn с --host 127.0.0.1)."
    )


def require_token(
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
):
    """Токен из заголовка X-Auth-Token либо из ?token=... в адресе.

    Query-параметр нужен потому, что "/" и "/account/{name}/logs" открываются
    прямо в браузере — заголовок туда не подставить.
    Если DASHBOARD_TOKEN не задан, проверка выключена и всё работает как раньше
    (локальный однопользовательский режим).
    """
    if not DASHBOARD_TOKEN:
        return
    supplied = x_auth_token or token or ""
    # compare_digest — чтобы токен нельзя было подобрать по времени ответа
    if not hmac.compare_digest(supplied.encode("utf-8"), DASHBOARD_TOKEN.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Требуется токен (X-Auth-Token или ?token=)")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Замена устаревшего @app.on_event("shutdown") (FastAPI 0.139 ругается)."""
    yield
    # При остановке GUI гасим только процессы, запущенные из GUI.
    for name in list(_processes):
        stop_account(name)
    for name in list(_log_handles):
        _close_log(name)


app = FastAPI(
    title="Travian Bot Dashboard", version="4.0",
    lifespan=lifespan, dependencies=[Depends(require_token)],
    # /docs, /redoc и /openapi.json FastAPI регистрирует как обычные роуты
    # Starlette — глобальный dependencies их НЕ покрывает. С включённым токеном
    # они отдавали полную карту API без пароля, поэтому просто выключаем их.
    # Без токена (локальный режим) оставляем как было — удобно для отладки.
    docs_url=None if DASHBOARD_TOKEN else "/docs",
    redoc_url=None if DASHBOARD_TOKEN else "/redoc",
    openapi_url=None if DASHBOARD_TOKEN else "/openapi.json",
)


def _safe_name(name: str) -> str:
    """Проверка {name} из URL — общая для всех роутов.

    Starlette пропускает в {name} всё, кроме '/', поэтому без этой проверки
    имя уходило и в путь файла (обход каталога, taskkill по чужому PID),
    и прямо в HTML (отражённая XSS).
    """
    if not is_valid_account_name(name):
        raise HTTPException(status_code=400, detail="Некорректное имя аккаунта")
    return name


# ======= ПРОЦЕССЫ АККАУНТОВ =======
# Каждый аккаунт = отдельный процесс `python runner.py --account <name>`.
# Полная независимость: старт/стоп одного не влияет на другие.

_processes: dict[str, subprocess.Popen] = {}

# Дескрипторы лог-файлов процессов. Раньше open() в start_account никогда
# не закрывался: после нескольких перезапусков дашборд держал стопку
# открытых логов, и на Windows их нельзя было ни удалить, ни переименовать.
_log_handles: dict = {}

_STILL_ACTIVE = 259  # GetExitCodeProcess: процесс ещё работает

_k32 = None


def _kernel32():
    """kernel32 с объявленными прототипами (иначе HANDLE режется до int32)."""
    global _k32
    if _k32 is None:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.GetProcessTimes.argtypes = ([wintypes.HANDLE]
                                      + [ctypes.POINTER(wintypes.FILETIME)] * 4)
        _k32 = k
    return _k32


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _proc_create_time(pid: int) -> int | None:
    """Время создания процесса (FILETIME). None, если недоступно/не Windows.

    Нужно, чтобы отличить наш процесс от чужого, которому ОС отдала тот же
    номер PID после смерти бота — иначе taskkill убивал постороннюю программу.
    """
    if os.name != 'nt' or pid <= 0:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k = _kernel32()
        h = k.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            ct, et, kt, ut = (wintypes.FILETIME() for _ in range(4))
            if not k.GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et),
                                     ctypes.byref(kt), ctypes.byref(ut)):
                return None
            return (ct.dwHighDateTime << 32) | ct.dwLowDateTime
        finally:
            k.CloseHandle(h)
    except Exception:
        logging.debug("create_time недоступен", exc_info=True)
        return None


def _pid_alive(pid: int) -> bool:
    """Проверяет, жив ли процесс с данным PID (кроссплатформенно).

    На Windows OpenProcess успешно открывает и УЖЕ ЗАВЕРШИВШИЙСЯ процесс, пока
    жив хоть один хэндл на него — а его держит наш же Popen в _processes.
    Поэтому одного OpenProcess мало: спрашиваем код выхода, живой процесс
    отвечает STILL_ACTIVE. Без этого после самопроизвольного падения бота
    «Старт» отвечал 409 до тех пор, пока не нажмёшь «Стоп».
    """
    if pid <= 0:
        return False
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            k = _kernel32()
            h = k.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            try:
                code = wintypes.DWORD()
                if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                    return False
                return code.value == _STILL_ACTIVE
            finally:
                k.CloseHandle(h)
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False


def _pid_file(name: str) -> Path:
    """PID-файл аккаунта (pids/<name>.pid, якорь — корень проекта)."""
    return pid_file(name)


def _write_pid_file(name: str, pid: int):
    """Пишем PID вместе со временем старта: голого номера мало (см. _orphan_pid)."""
    write_json(_pid_file(name), {
        "pid": pid,
        "create_time": _proc_create_time(pid),
        "image": sys.executable,
    })


def _read_pid_record(name: str) -> dict | None:
    pf = _pid_file(name)
    if not pf.exists():
        return None
    data = read_json(pf)
    if isinstance(data, int):  # легаси-формат: в файле лежал просто номер
        return {"pid": data, "create_time": None}
    if isinstance(data, dict) and isinstance(data.get("pid"), int):
        return data
    return None


def _orphan_pid(name: str) -> int | None:
    """PID процесса-сироты (запущен прошлым GUI, всё ещё жив)."""
    rec = _read_pid_record(name)
    if rec is None:
        _pid_file(name).unlink(missing_ok=True)
        return None
    pid = rec["pid"]
    if not _pid_alive(pid):
        _pid_file(name).unlink(missing_ok=True)  # мёртвый PID-файл — чистим
        return None
    want, got = rec.get("create_time"), _proc_create_time(pid)
    if want and got and want != got:
        # Номер PID переиспользован ОС — это уже чужой процесс, трогать нельзя
        logging.warning(f"⚠️ PID {pid} принадлежит другому процессу — PID-файл {name} сброшен")
        _pid_file(name).unlink(missing_ok=True)
        return None
    return pid


def proc_running(name: str) -> bool:
    p = _processes.get(name)
    if p is not None and p.poll() is None:
        return True
    if not is_valid_account_name(name):
        return False
    # Процесс мог быть запущен предыдущим экземпляром GUI
    return _orphan_pid(name) is not None


def _close_log(name: str):
    """Закрывает файл stdout процесса аккаунта, если он ещё открыт."""
    fh = _log_handles.pop(name, None)
    if fh is None:
        return
    try:
        fh.close()
    except Exception:
        logging.debug(f"close log handle {name}", exc_info=True)


def start_account(name: str) -> bool:
    if proc_running(name):
        return False
    _close_log(name)  # дескриптор от предыдущего запуска
    out = open(process_log_file(name), "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "runner.py", "--account", name],
        stdout=out, stderr=subprocess.STDOUT,
        cwd=str(Path(__file__).parent),
    )
    _processes[name] = proc
    _log_handles[name] = out
    try:
        _write_pid_file(name, proc.pid)
    except Exception as e:
        logging.debug(f"pid file write: {e}")
    return True


def stop_account(name: str) -> bool:
    """
    Останавливает процесс бота и сбрасывает status-файл.
    Убивает как управляемый процесс, так и сироту из PID-файла.
    """
    p = _processes.get(name)
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()

    # Сирота от предыдущего экземпляра GUI
    orphan = _orphan_pid(name)
    if orphan is not None:
        try:
            if os.name == 'nt':
                # timeout: без него зависший taskkill вешал весь HTTP-запрос
                subprocess.run(["taskkill", "/PID", str(orphan), "/T", "/F"],
                               capture_output=True, timeout=15)
            else:
                os.kill(orphan, 15)  # SIGTERM
        except Exception as e:
            logging.debug(f"orphan kill: {e}")

    _pid_file(name).unlink(missing_ok=True)

    # Убираем из таблицы процессов в любом случае
    _processes.pop(name, None)
    _close_log(name)

    # Сбрасываем status-файл чтобы GUI перестал считать бота живым.
    # is_alive() смотрит на поле "alive" + свежесть "last_heartbeat",
    # поэтому гасим именно "alive" и обнуляем heartbeat (иначе после
    # принудительного закрытия PyCharm лампочка оставалась зелёной).
    # Запись атомарная и под общей блокировкой: тот же файл пишет бот, и
    # обычный open(...,"w") оставлял на диске обрезанный JSON.
    status_path = account_file(name, 'status')
    if status_path.exists():
        with file_lock(status_path):
            data = read_json(status_path, default={})
            if not isinstance(data, dict):
                data = {}
            data["alive"] = False
            data["running"] = False
            data["last_heartbeat"] = None
            data["last_action"] = "Остановлен из GUI"
            write_json(status_path, data)

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
    """Читает накопленную статистику фарма (data/<acc>/farm_stats.json)
    и досчитывает нетто-профит (добыча − стоимость погибших войск)."""
    p = account_file(name, 'farm_stats')
    data = {}
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logging.debug("suppressed error: farm_stats read", exc_info=True)
    if data:
        try:
            tribe = get_store(name).section("farm").get("tribe", "roman")
        except Exception:
            tribe = "roman"
        data["tribe"] = tribe
        _attach_farm_net(data, tribe)
    return data


# Стоимость обучения юнита (сумма ресурсов) по племени, индекс 0=t1..9=t10.
# Стандартные значения x1; поселенцы/вожди (t9/t10) = 0 (в фарме не гибнут).
# Точно для классических племён; для остальных — оценка.
UNIT_COST_BY_TRIBE = {
    "roman":    [400, 460, 600, 360, 1410, 2170, 1830, 2990, 0, 0],
    "teuton":   [250, 340, 490, 360, 1005, 1525, 1720, 2760, 0, 0],
    "gaul":     [315, 535, 380, 1090, 1090, 1965, 1910, 3130, 0, 0],
    "egyptian": [150, 420, 565, 380, 1090, 1800, 2200, 2920, 0, 0],
    "hun":      [290, 370, 380, 900, 1200, 1600, 1900, 2900, 0, 0],
    "spartan":  [200, 300, 380, 900, 1100, 1800, 1900, 2900, 0, 0],
}


def _attach_farm_net(farm: dict, tribe: str):
    """Считает стоимость погибших войск и чистый профит фарма (в ресурсах)."""
    costs = UNIT_COST_BY_TRIBE.get(tribe) or UNIT_COST_BY_TRIBE["roman"]
    lost_value = 0
    for k, v in (farm.get("by_troop") or {}).items():
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= len(costs):
            lost_value += int(v.get("lost", 0)) * (costs[idx - 1] or 0)
    tot = farm.setdefault("totals", {})
    tot["lost_value"] = lost_value
    tot["net"] = int(tot.get("loot", 0)) - lost_value


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


# Сколько байт хвоста лога читать. Логи растут до десятков мегабайт, а
# страница логов перезагружается каждые 10 секунд — читать файл целиком
# ради 150 строк нельзя.
_LOG_TAIL_BYTES = 512 * 1024


def get_last_logs(account_name: str, lines: int = 150) -> list[str]:
    if not is_valid_account_name(account_name):
        return []
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = log_file(account_name, date_str)
    if not path.exists():
        path = process_log_file(account_name)
        if not path.exists():
            return []
    lines = max(1, int(lines))
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _LOG_TAIL_BYTES))
            chunk = f.read()
        text = chunk.decode("utf-8", errors="replace")
        if size > _LOG_TAIL_BYTES:
            text = text.split("\n", 1)[-1]  # первая строка обрезана посередине
        return text.splitlines()[-lines:]
    except Exception:
        return []


def _mask_proxy(proxy: str) -> str:
    """Прячет пароль в строке прокси: наружу отдавать его нельзя.

    Формат сохраняем (scheme://user:***@host:port), чтобы поле в дашборде
    и мини-аппе выглядело как раньше.
    """
    raw = (proxy or "").strip()
    if not raw:
        return ""
    head, sep, tail = raw.rpartition("@")
    if not sep:
        return raw  # без креденшелов — прятать нечего
    scheme, s2, userinfo = head.rpartition("://")
    user = userinfo.split(":", 1)[0]
    return f"{scheme}{s2}{user}:***@{tail}"


def _is_masked_proxy(proxy: str) -> bool:
    """Клиент вернул строку с нашей же маской — значит поле не меняли."""
    return ":***@" in (proxy or "")


# ======= API: АККАУНТЫ =======

@app.get("/api/accounts")
async def api_accounts():
    out = []
    for acc in load_accounts():
        name = acc.get("name", "")
        if not is_valid_account_name(name):
            # Имя аккаунта стало именем каталога, и utils.paths теперь его
            # проверяет. Без этой ветки ОДИН старый аккаунт с пробелом в
            # config.yaml ронял весь список 500-й, и дашборд оставался пустым.
            logging.warning(
                f"⚠️ Аккаунт {name!r} пропущен: в имени разрешены только "
                f"буквы/цифры/_- (до 64 символов). Переименуй его в config.yaml/GUI."
            )
            continue
        status = load_status(name)
        proxy = acc.get("proxy", "") or ""
        out.append({
            "name": name,
            "server": acc.get("server", ""),
            "email": acc.get("email", "") or "",
            "has_password": bool(acc.get("password")),
            "rate": acc.get("rate", 3),
            "headless": acc.get("headless", True),
            # Пароль прокси наружу не отдаём (раньше уходил в открытом виде).
            # Ключ "proxy" сохранён, чтобы поле в GUI не сломалось.
            "proxy": _mask_proxy(proxy),
            "has_proxy": bool(proxy),
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
    # is_valid_account_name — та же проверка, что и в utils.paths (в т.ч. длина):
    # имя становится именем каталога, безлимитное регуляркой [A-Za-z0-9_-]+ мало
    if not is_valid_account_name(name):
        raise HTTPException(400, "Имя: только буквы/цифры/_- без пробелов, до 64 символов")
    if not server:
        raise HTTPException(400, "Укажи сервер (например ts30.x3.international.travian.com)")

    server = re.sub(r"^https?://", "", server).strip("/")
    allowed = {"name", "server", "email", "password", "rate", "headless", "proxy", "build_template"}
    clean = {k: v for k, v in data.items() if k in allowed}
    clean["name"] = name
    clean["server"] = server
    if "proxy" in clean:
        clean["proxy"] = (clean["proxy"] or "").strip()
        if _is_masked_proxy(clean["proxy"]):
            # клиент вернул нашу же маску — это «не менять», а не «записать звёздочки»
            clean.pop("proxy")
    # Пустое поле логина/пароля означает «оставь как есть», а не «сотри».
    # Форма «Добавить аккаунт» не подставляет сохранённый пароль обратно, и без
    # этой проверки повторная отправка формы (например, чтобы сменить сервер)
    # затирала пустой строкой логин из config.yaml — бот терял доступ.
    # Прокси тут намеренно НЕ трогаем: его очистка из интерфейса — рабочий сценарий.
    for secret in ("email", "password"):
        if secret in clean and not str(clean[secret] or "").strip():
            clean.pop(secret)
    # Путь до куков не хардкодим — runner берёт его из utils.paths (data/<acc>/)
    if "rate" in clean:
        # int() без обработки давал 500 вместо внятного 400 на "abc" или ""
        try:
            clean["rate"] = int(clean["rate"])
        except (TypeError, ValueError):
            raise HTTPException(400, "rate: ожидается число")
    # Проверяем что шаблон существует; дефолт x3
    from config.build_templates import TEMPLATES
    bt = clean.get("build_template", "x3")
    if bt not in TEMPLATES:
        bt = "x3"
    clean["build_template"] = bt

    acc = upsert_gui_account(clean)
    return {"ok": True, "account": {"name": acc["name"], "server": acc["server"]}}


@app.delete("/api/accounts/{name}")
def api_delete_account(name: str):
    _safe_name(name)
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
    _safe_name(name)
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    # подключение
    conn_allowed = {"rate", "headless", "proxy"}
    patch = {k: v for k, v in data.items() if k in conn_allowed}
    if "proxy" in patch:
        patch["proxy"] = (patch["proxy"] or "").strip()
        if _is_masked_proxy(patch["proxy"]):
            # клиент вернул нашу же маску — поле не трогали, прокси не меняем
            patch.pop("proxy")
    # settings (farm/training/trade/features) — если переданы.
    # Проверяем ДО записи подключения: иначе при 422 на настройках rate/proxy
    # уже оказывались сохранены, и запрос применялся наполовину.
    clean = {}
    if "settings" in data and isinstance(data["settings"], dict):
        clean = {k: v for k, v in data["settings"].items()
                 if k in _SETTINGS_SECTIONS and isinstance(v, dict)}
        if clean:
            clean = _validate_settings(clean)
    if patch:
        # upsert_gui_account принимает ОДИН аргумент — здесь передавали два,
        # и каждый PUT падал 500-й (настройки подключения не сохранялись).
        # {**acc, **patch} тоже нельзя: acc — это мерж yaml+gui, и пароль из
        # config.yaml навсегда переехал бы копией в accounts_gui.json.
        upsert_gui_account({"name": name, **patch})
    if clean:
        get_store(name).save(clean)
    return {"ok": True}


@app.post("/api/accounts/{name}/start")
async def api_start(name: str):
    _safe_name(name)
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    if proc_running(name):
        raise HTTPException(409, "Уже запущен из этого GUI")
    if is_alive(load_status(name)):
        raise HTTPException(409, "Бот уже работает (запущен вне GUI, напр. через runner.py)")
    start_account(name)
    return {"ok": True}


@app.post("/api/accounts/{name}/stop")
def api_stop(name: str):
    # Раньше здесь не было НИ проверки имени, НИ проверки существования
    # аккаунта: POST /api/accounts/<что угодно>/stop отвечал {"ok":true},
    # создавал data/<что угодно>/ и мог дойти до taskkill по чужому PID.
    _safe_name(name)
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    stop_account(name)  # всегда возвращает True, 409 больше не кидаем
    return {"ok": True}


@app.post("/api/accounts/{name}/scan")
async def api_scan(name: str):
    """Принудительный полный скан карты: ставит команду в очередь бота."""
    _safe_name(name)
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
    _safe_name(name)
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
    _safe_name(name)
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
    _safe_name(name)
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
def api_servers():
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


# host приходит из адресной строки и подставляется в URL запроса. Раньше
# отрезалась только схема, поэтому через дашборд можно было дёргать любой
# адрес (включая 127.0.0.1 и внутреннюю сеть) и читать по ответу, что там
# живёт — классический SSRF. Теперь: только домен travian.*, только
# публичный IP, без редиректов и без деталей ошибки наружу.
_CHECK_HOST_RE = re.compile(r"[a-z0-9.-]+(:\d{1,5})?")
# Хвост домена — максимум два уровня (travian.com, travian.co.uk, travian.com.br).
# С `*` вместо `?` проверку обходил любой чужой домен вида
# xxx.travian.com.злоумышленник.net — он тоже заканчивался на «.travian.<...>».
_TRAVIAN_HOST_RE = re.compile(r"(^|\.)travian\.[a-z]{2,}(\.[a-z]{2,})?$")


def _is_public_host(hostname: str) -> bool:
    """True, если имя резолвится и ВСЕ его адреса публичные."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


@app.get("/api/servers/check")
def api_server_check(host: str):
    """Проверка: сервер существует и отвечает как Travian."""
    host = re.sub(r"^https?://", "", host or "").strip("/").strip().lower()
    if not _CHECK_HOST_RE.fullmatch(host):
        return {"ok": False, "status_code": 0, "error": "Недопустимый адрес сервера"}
    hostname = host.split(":", 1)[0]
    if not _TRAVIAN_HOST_RE.search(hostname):
        return {"ok": False, "status_code": 0, "error": "Ожидается домен travian.*"}
    if not _is_public_host(hostname):
        return {"ok": False, "status_code": 0, "error": "Адрес не резолвится или он локальный"}
    try:
        resp = requests.get(
            f"https://{host}/", timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=False,
        )
    except requests.RequestException:
        # str(e) наружу не отдаём — там внутренние адреса и детали сети
        return {"ok": False, "status_code": 0, "error": "Сервер не отвечает"}
    loc = (resp.headers.get("Location") or "").lower()
    ok = ((resp.status_code == 200 and "travian" in resp.text.lower())
          or (300 <= resp.status_code < 400 and "travian." in loc))
    return {"ok": ok, "status_code": resp.status_code}


# ======= API: НАСТРОЙКИ =======

_SETTINGS_SECTIONS = {"features", "farm", "training", "trade", "build",
                      "smithy", "task_order", "night"}

# Границы числовых настроек: (тип, min, max).
# Раньше фильтрация была только на уровне секции, и в файл попадало что угодно.
# Самое неприятное — farm.interval_minutes: int("") в idle_hook кидал
# ValueError ДО write_status, исключение глушилось на DEBUG, и heartbeat
# замирал навсегда, а дашборд продолжал показывать бота живым.
_SETTINGS_BOUNDS = {
    ("farm", "troops_per_raid"):        (int,   1, 5000),
    ("farm", "troop_type_index"):       (int,   1, 10),
    ("farm", "scan_radius"):            (int,   1, 50),
    ("farm", "interval_minutes"):       (int,   1, 1440),
    ("farm", "cooldown_minutes"):       (int,   0, 10080),
    ("farm", "max_distance"):           (float, 0, 500),
    ("farm", "troop_speed_tph"):        (int,   0, 100),
    ("farm", "max_animal_defense"):     (int,   0, 10 ** 9),
    ("farm", "hero_min_health"):        (int,   0, 100),
    ("farm", "hero_safety_pct"):        (int,   0, 10000),
    ("training", "troop_type_index"):   (int,   1, 10),
    ("training", "target_count"):       (int,   0, 1000000),
    ("training", "min_queue_size"):     (int,   0, 100000),
    ("training", "spend_pct"):          (int,   1, 100),
    ("training", "max_batch"):          (int,   0, 1000000),
    ("trade", "npc_threshold_pct"):     (int,   0, 100),
    ("trade", "transfer_interval_min"): (int,   1, 10080),
    ("night", "start"):                 (int,   0, 23),
    ("night", "end"):                   (int,   0, 23),
}


def _validate_settings(clean: dict) -> dict:
    """Приводит числовые настройки к числу и проверяет границы (422 при выходе)."""
    for (sec, key), (caster, lo, hi) in _SETTINGS_BOUNDS.items():
        block = clean.get(sec)
        if not isinstance(block, dict) or key not in block:
            continue
        raw = block[key]
        if isinstance(raw, bool):
            raise HTTPException(422, f"{sec}.{key}: ожидается число")
        try:
            val = caster(raw)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{sec}.{key}: ожидается число, получено {raw!r}")
        if not (lo <= val <= hi):
            raise HTTPException(422, f"{sec}.{key}: допустимо {lo}..{hi}, получено {val}")
        block[key] = val
    return clean


@app.get("/api/accounts/{name}/settings")
async def api_get_settings(name: str):
    _safe_name(name)
    return JSONResponse(content=get_store(name).get_all())


@app.post("/api/accounts/{name}/settings")
async def api_save_settings(name: str, updates: dict):
    _safe_name(name)
    clean = {k: v for k, v in updates.items()
             if k in _SETTINGS_SECTIONS and isinstance(v, dict)}
    if not clean:
        raise HTTPException(status_code=400, detail="Нет валидных настроек")
    clean = _validate_settings(clean)
    store = get_store(name)
    # village_plans / custom_plans — коллекции, которыми полностью управляет GUI:
    # заменяем целиком, чтобы удаление элемента из дашборда реально применялось.
    store.save(clean, replace_paths=[("build", "village_plans"), ("build", "custom_plans")])
    return {"ok": True, "settings": store.get_all()}


@app.get("/api/accounts/{name}/logs")
async def api_logs(name: str, lines: int = Query(150, ge=1, le=2000)):
    # lines без границ: "?lines=0" превращался в [-0:] == весь файл целиком
    _safe_name(name)
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
async def account_logs(name: str, lines: int = Query(150, ge=1, le=2000),
                       lang: str = "ru", token: str | None = Query(default=None)):
    _safe_name(name)
    lang = "en" if lang == "en" else "ru"
    log_lines = translate_logs(get_last_logs(name, lines), lang)
    # экранируем на случай спецсимволов HTML в строках лога
    empty_txt = "Log is empty" if lang == "en" else "Лог пуст"
    log_html = "\n".join(_esc(ln) for ln in log_lines) if log_lines else empty_txt

    t = {
        "ru": {"title": "Логи", "back": "Дашборд", "refresh": "автообновление каждые 10 с",
               "toggle": "English", "other": "en"},
        "en": {"title": "Logs", "back": "Dashboard", "refresh": "auto-refresh every 10s",
               "toggle": "Русский", "other": "ru"},
    }[lang]
    # Имя аккаунта уже прошло _safe_name, но экранируем и здесь: раньше оно
    # подставлялось в разметку сырым — кавычка в URL давала отражённую XSS.
    safe = _esc(name)
    # токен тащим дальше по ссылке, иначе переключатель языка отдаст 401
    tok = f"&amp;token={_esc(_urlquote(token))}" if token else ""
    html = f"""<!DOCTYPE html><html lang="{lang}"><head>
    <title>{t['title']}: {safe}</title><meta charset="utf-8">
    <meta http-equiv="refresh" content="10">
    <style>
      body {{ font-family: ui-monospace, Consolas, monospace; background: #0f1115; color: #c9cfda; padding: 20px; font-size: 12px; }}
      h2 {{ color: #e94560; margin-bottom: 8px; }}
      a {{ color: #e94560; }}
      .lang-btn {{ display: inline-block; margin-left: 12px; padding: 3px 10px; border: 1px solid #e94560;
                   border-radius: 6px; text-decoration: none; font-size: 12px; }}
      pre {{ background: #171a21; border: 1px solid #2a2f3a; padding: 15px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }}
    </style></head><body>
    <h2>{t['title']}: {safe}</h2>
    <p><a href="/">&larr; {t['back']}</a> · {t['refresh']}
       <a class="lang-btn" href="/account/{safe}/logs?lines={lines}&amp;lang={t['other']}{tok}">{t['toggle']}</a></p>
    <pre>{log_html}</pre>
    </body></html>"""
    return HTMLResponse(content=html)


def _render_account_page(filename: str, name: str) -> str:
    """Подставляет имя аккаунта в статическую страницу.

    Сначала заменяем именно строковый ЛИТЕРАЛ "__ACCOUNT__" на json.dumps(name):
    раньше сюда шла сырая подстановка, и кавычка в имени закрывала JS-строку.
    Остальные вхождения (<title>, href) экранируем как HTML.
    """
    page = (Path(__file__).parent / "static" / filename).read_text(encoding="utf-8")
    return page.replace('"__ACCOUNT__"', json.dumps(name)).replace("__ACCOUNT__", _esc(name))


@app.get("/api/accounts/{name}/farm_stats")
async def api_farm_stats(name: str):
    """Сырая статистика фарма для страницы с графиками (+ племя и нетто-профит)."""
    _safe_name(name)
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    return JSONResponse(content=load_farm_stats(name))


@app.get("/account/{name}/farm", response_class=HTMLResponse)
async def account_farm(name: str):
    """Страница с интерактивными графиками статистики фарма."""
    _safe_name(name)
    return HTMLResponse(content=_render_account_page("farm.html", name))


@app.get("/api/accounts/{name}/history")
async def api_history(name: str):
    """Временной ряд метрик (ресурсы/производство/войска/герой) для аналитики."""
    _safe_name(name)
    if get_account(name) is None:
        raise HTTPException(404, "Аккаунт не найден")
    p = account_file(name, 'history')
    data = []
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logging.debug("suppressed error: history read", exc_info=True)
    return JSONResponse(content=data if isinstance(data, list) else [])


@app.get("/account/{name}/analytics", response_class=HTMLResponse)
async def account_analytics(name: str):
    """Страница аналитики: динамика ресурсов, войск и героя во времени."""
    _safe_name(name)
    return HTMLResponse(content=_render_account_page("analytics.html", name))
