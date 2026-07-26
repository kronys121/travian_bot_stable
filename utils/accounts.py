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
import logging
import yaml
from urllib.parse import quote

from utils.jsonio import write_json
from utils.merge import deep_merge as _deep_merge
from utils.paths import PROJECT_ROOT

GUI_FILE = PROJECT_ROOT / "accounts_gui.json"
YAML_FILE = PROJECT_ROOT / "config.yaml"


class AccountStoreError(RuntimeError):
    """Реестр аккаунтов на диске повреждён — писать поверх него нельзя."""


# Дефолты подключения для нового аккаунта, созданного из GUI.
# ВАЖНО: здесь только параметры ПОДКЛЮЧЕНИЯ. Игровые настройки (farm/training/
# trade) живут ровно в одном месте — utils/settings_store.DEFAULT_SETTINGS.
# Раньше копия жила и тут, значения разъехались (troop_type_index 4 против 1,
# scan_radius 10 против 5), и созданный из GUI аккаунт молча получал чужие
# дефолты: фарм осадными орудиями по радиусу 10.
DEFAULT_ACCOUNT = {
    "rate": 3,
    "headless": True,
    "proxy": "",          # прокси вида http://user:pass@host:port (пусто = без прокси)
    "sleep_hours": [2, 8],
    "evasion_enabled": True,
    "attack_check_interval": 120,
}


def _load_yaml_accounts() -> list[dict]:
    """Аккаунты из config.yaml. Бросает AccountStoreError, если файл битый."""
    try:
        with open(YAML_FILE, "r", encoding="utf-8") as f:
            # safe_load пустого файла возвращает None — без `or {}` тут был
            # AttributeError на КАЖДОМ вызове, который молча съедался.
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        logging.error(f"❌ {YAML_FILE.name} не читается: {e}")
        raise AccountStoreError(str(e)) from e
    if not isinstance(data, dict):
        logging.error(f"❌ {YAML_FILE.name}: ожидался объект, получен {type(data).__name__}")
        raise AccountStoreError("config.yaml: корень не является объектом")
    return data.get("accounts") or []


def _load_gui_accounts() -> list[dict]:
    """Аккаунты из accounts_gui.json. Бросает AccountStoreError, если файл битый."""
    try:
        raw = GUI_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        logging.error(f"❌ {GUI_FILE.name} не читается: {e}")
        raise AccountStoreError(str(e)) from e
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        # Раньше здесь был `return []`: реестр «пустел», а следующее сохранение
        # из GUI переписывало файл целиком и уничтожало все аккаунты.
        logging.error(f"❌ {GUI_FILE.name} повреждён: {e}")
        raise AccountStoreError(str(e)) from e
    return (data or {}).get("accounts") or []


def _save_gui_accounts(accounts: list[dict]):
    if not write_json(GUI_FILE, {"accounts": accounts}, indent=2):
        raise AccountStoreError(f"не удалось записать {GUI_FILE.name}")


def _safe_load(loader) -> list[dict]:
    """Для чтения (GUI-список): битый источник не должен ронять дашборд."""
    try:
        return loader()
    except AccountStoreError:
        return []


def load_accounts() -> list[dict]:
    """Мерж yaml + gui. Порядок: сперва yaml-аккаунты, затем новые gui-аккаунты.

    Битый источник даёт пустой список И запись в лог. Изменять реестр в этом
    состоянии нельзя — за этим следят upsert_gui_account/delete_gui_account,
    которые читают строго и падают с AccountStoreError.
    """
    yaml_accs = {a.get("name"): a for a in _safe_load(_load_yaml_accounts) if a.get("name")}
    gui_accs = {a.get("name"): a for a in _safe_load(_load_gui_accounts) if a.get("name")}

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
    """Добавляет или обновляет аккаунт в accounts_gui.json.

    Читает файл СТРОГО (_load_gui_accounts, не _safe_load): если он повреждён,
    лучше вернуть ошибку, чем перезаписать реестр одним аккаунтом.
    """
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
    return any(a.get("name") == name for a in _safe_load(_load_yaml_accounts))


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

    if not proxy_str or not str(proxy_str).strip():
        return True, ""  # нет прокси — ок
    p = split_proxy(proxy_str)
    if not p:
        return False, f"Не удалось разобрать прокси: {proxy_str}"
    host, port = p["host"], p["port"]
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, ""
    except OSError as e:
        return False, f"Прокси недоступен ({host}:{port}): {e}"


def split_proxy(proxy_str: str | None) -> dict | None:
    """
    Разбирает строку прокси в {scheme, host, port, username, password}.
    Возвращает None, если строка пустая или неразбираемая.

    Свой разбор, а не urlparse: пароли у прокси-провайдеров часто содержат
    «/», а для urlparse слэш заканчивает netloc — строка
    socks5://user:pa/ss@1.2.3.4:1080 разбиралась как хост "ss" без порта.
    Здесь netloc режется по ПОСЛЕДНЕМУ «@», поэтому в пароле допустимы
    любые символы, кроме пробела.

    Поддерживаемые формы:
        socks5://user:pass@host:port
        http://user:pass@host:port
        https://host:port
        host:port                    (считаем http)
    """
    if not proxy_str or not str(proxy_str).strip():
        return None
    raw = str(proxy_str).strip()

    scheme, sep, rest = raw.partition("://")
    if not sep:
        scheme, rest = "http", raw
    scheme = scheme.lower()

    # ВАЖЕН ПОРЯДОК: сначала отделяем логин:пароль по последнему «@»,
    # и только потом срезаем путь у ОСТАВШЕЙСЯ части host:port.
    # Наоборот нельзя — пароль со слэшем (обычное дело у прокси-провайдеров)
    # обрезался бы вместе с «путём».
    username = password = None
    if "@" in rest:
        userinfo, _, rest = rest.rpartition("@")
        username, _, password = userinfo.partition(":")
        username = username or None
        password = password or None

    # отбрасываем путь/параметры, если их вписали по привычке
    rest = rest.split("/", 1)[0].split("?", 1)[0]

    host, _, port_s = rest.rpartition(":")
    if not host or not port_s:
        return None
    try:
        port = int(port_s)
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    return {"scheme": scheme, "host": host, "port": port,
            "username": username, "password": password}


def requests_proxies(proxy_str: str | None) -> dict | None:
    """
    Прокси в формате библиотеки requests: {"http": ..., "https": ...}.

    Нужен для потока мониторинга атак: он ходит на dorf1.php обычным
    requests, а НЕ через браузер. Без этого весь смысл прокси терялся —
    браузер шёл через прокси, а монитор каждые 2 минуты стучался с
    настоящего IP машины, с теми же куками аккаунта. Для игры это один
    аккаунт, одновременно активный с двух разных адресов.

    В отличие от Chromium, requests+PySocks умеет SOCKS5 с логином/паролем,
    поэтому туннель тут не нужен. Схему socks5 меняем на socks5h: так имя
    хоста резолвит сам прокси, а не мы (иначе DNS-запрос уходит с нашего IP).
    """
    p = split_proxy(proxy_str)
    if not p:
        return None
    scheme = "socks5h" if p["scheme"] in ("socks5", "socks5h") else p["scheme"]
    auth = ""
    if p["username"]:
        auth = quote(p["username"], safe="")
        if p["password"]:
            auth += ":" + quote(p["password"], safe="")
        auth += "@"
    url = f"{scheme}://{auth}{p['host']}:{p['port']}"
    return {"http": url, "https": url}


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
    p = split_proxy(proxy_str)
    if not p:
        return None
    # Chromium знает socks5, но не socks5h (это соглашение библиотек, а не схема
    # браузера). Отдавать ему socks5h — гарантированный отказ запуска.
    # Удалённый DNS у Chromium для SOCKS5 включён и так.
    scheme = "socks5" if p["scheme"] == "socks5h" else p["scheme"]
    proxy = {"server": f"{scheme}://{p['host']}:{p['port']}"}
    if p["username"]:
        proxy["username"] = p["username"]
    if p["password"]:
        proxy["password"] = p["password"]
    return proxy
