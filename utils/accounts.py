"""
Единый реестр аккаунтов для runner.py и app.py (GUI).

Источники (мержатся по имени):
  1. config.yaml -> accounts:[...]   — "ручные" аккаунты (редактируются в файле)
  2. accounts_gui.json               — аккаунты, добавленные/изменённые через GUI

GUI-запись с тем же name ПЕРЕКРЫВАЕТ yaml-запись (поверх, поле за полем).
Так yaml с комментариями никогда не перезаписывается программно.

Пароли:
  - можно хранить прямо в записи (email/password),
  - либо в .env:  TRAVIAN_EMAIL_<NAME> / TRAVIAN_PASSWORD_<NAME>
    (или общие TRAVIAN_EMAIL / TRAVIAN_PASSWORD, если аккаунт один).
"""
import os
import json
import yaml
from urllib.parse import urlparse
from pathlib import Path

GUI_FILE = Path("accounts_gui.json")
YAML_FILE = Path("config.yaml")

# Дефолты для нового аккаунта, созданного из GUI
DEFAULT_ACCOUNT = {
    "rate": 3,
    "headless": True,
    "proxy": "",          # прокси вида socks5://user:pass@host:port (пусто = без прокси)
    "sleep_hours": [2, 8],
    "evasion_enabled": True,
    "attack_check_interval": 120,
    "farm": {
        "troops_per_raid": 10,
        "troop_type_index": 4,
        "max_distance": 10.0,
        "scan_radius": 10,
        "interval_minutes": 60,
        "cooldown_minutes": 60,
    },
    "training": {"enabled": False, "troop_type_index": 1, "target_count": 100, "building": "barracks"},
    "trade": {"npc_enabled": False, "npc_threshold_pct": 85},
}


def _load_yaml_accounts() -> list[dict]:
    try:
        with open(YAML_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f).get("accounts", []) or []
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _load_gui_accounts() -> list[dict]:
    try:
        return json.loads(GUI_FILE.read_text(encoding="utf-8")).get("accounts", [])
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _save_gui_accounts(accounts: list[dict]):
    tmp = GUI_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, GUI_FILE)


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        elif v is not None and v != "":
            out[k] = v
    return out


def load_accounts() -> list[dict]:
    """Мерж yaml + gui. Порядок: сперва yaml-аккаунты, затем новые gui-аккаунты."""
    yaml_accs = {a.get("name"): a for a in _load_yaml_accounts() if a.get("name")}
    gui_accs = {a.get("name"): a for a in _load_gui_accounts() if a.get("name")}

    result = []
    for name, acc in yaml_accs.items():
        if name in gui_accs:
            result.append(_deep_merge(acc, gui_accs[name]))
        else:
            result.append(acc)
    for name, acc in gui_accs.items():
        if name not in yaml_accs:
            result.append(_deep_merge(DEFAULT_ACCOUNT, acc))
    return result


def get_account(name: str) -> dict | None:
    return next((a for a in load_accounts() if a.get("name") == name), None)


def upsert_gui_account(data: dict) -> dict:
    """Добавляет или обновляет аккаунт в accounts_gui.json."""
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Имя аккаунта обязательно")
    accounts = _load_gui_accounts()
    existing = next((a for a in accounts if a.get("name") == name), None)
    if existing:
        merged = _deep_merge(existing, data)
        accounts = [merged if a.get("name") == name else a for a in accounts]
    else:
        merged = data
        accounts.append(merged)
    _save_gui_accounts(accounts)
    return get_account(name)


def delete_gui_account(name: str) -> bool:
    """Удаляет аккаунт из accounts_gui.json. yaml-аккаунты не трогает."""
    accounts = _load_gui_accounts()
    new_list = [a for a in accounts if a.get("name") != name]
    if len(new_list) == len(accounts):
        return False
    _save_gui_accounts(new_list)
    return True


def is_yaml_account(name: str) -> bool:
    return any(a.get("name") == name for a in _load_yaml_accounts())


def resolve_credentials(acc: dict) -> tuple[str | None, str | None]:
    """
    Логин/пароль для аккаунта, в порядке приоритета:
      1. поля email/password в записи аккаунта
      2. .env: TRAVIAN_EMAIL_<NAME> / TRAVIAN_PASSWORD_<NAME>
      3. .env: TRAVIAN_EMAIL / TRAVIAN_PASSWORD (общие)
    """
    name = (acc.get("name") or "").upper().replace("-", "_")
    email = (
        acc.get("email")
        or os.getenv(f"TRAVIAN_EMAIL_{name}")
        or os.getenv("TRAVIAN_EMAIL")
    )
    password = (
        acc.get("password")
        or os.getenv(f"TRAVIAN_PASSWORD_{name}")
        or os.getenv("TRAVIAN_PASSWORD")
    )
    return email, password


def validate_proxy(proxy_str: str | None, timeout: float = 5.0) -> tuple[bool, str]:
    """
    Проверяет TCP-доступность прокси-хоста ПЕРЕД запуском браузера.
    Возвращает (True, "") если хост отвечает, иначе (False, описание ошибки).
    Работает для socks5:// и http:// — проверяется только сам хост:порт.
    """
    import socket
    from urllib.parse import urlparse as _up

    if not proxy_str or not str(proxy_str).strip():
        return True, ""  # нет прокси — ок
    raw = str(proxy_str).strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        u = _up(raw)
        host, port = u.hostname, u.port
        if not host or not port:
            return False, f"Не удалось разобрать прокси: {proxy_str}"
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, ""
    except OSError as e:
        return False, f"Прокси недоступен ({host}:{port}): {e}"
    except Exception as e:
        return False, f"Ошибка проверки прокси: {e}"


def parse_proxy(proxy_str: str | None) -> dict | None:
    """
    Превращает строку прокси в dict для Playwright launch(proxy=...).

    Поддерживаемые форматы:
      socks5://user:pass@host:port
      http://user:pass@host:port
      https://host:port           (без авторизации)
      host:port                   (по умолчанию считаем http)

    Возвращает None, если строка пустая/битая (запуск без прокси).
    Пример результата:
      {"server": "socks5://45.147.100.35:8000",
       "username": "e7WZv5", "password": "JkgCKD"}
    """
    if not proxy_str or not str(proxy_str).strip():
        return None
    raw = str(proxy_str).strip()
    # добавляем схему по умолчанию, если её нет (urlparse иначе не разберёт host:port)
    if "://" not in raw:
        raw = "http://" + raw
    try:
        u = urlparse(raw)
        if not u.hostname or not u.port:
            return None
        scheme = (u.scheme or "http").lower()
        server = f"{scheme}://{u.hostname}:{u.port}"
        proxy = {"server": server}
        if u.username:
            proxy["username"] = u.username
        if u.password:
            proxy["password"] = u.password
        return proxy
    except Exception:
        return None
