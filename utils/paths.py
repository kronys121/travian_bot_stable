"""
Центральный модуль путей файлов аккаунта.

Все файлы аккаунта живут в data/<account>/:
    data/<acc>/cookies.json
    data/<acc>/status.json
    data/<acc>/stats.json
    data/<acc>/build_progress.json
    data/<acc>/build_history.json
    data/<acc>/cooldowns.json
    data/<acc>/occupied_oases.json
    ...

Старые файлы в корне (cookies_<acc>.json и т.п.) автоматически
переносятся в data/<acc>/ при первом обращении — миграция бесшовная.

Два важных свойства этого модуля:

1. ЯКОРЬ. Все пути считаются от корня проекта, а не от текущего каталога.
   Раньше runner.py стартовал с cwd=<репозиторий> (app.py задаёт cwd явно),
   а сам дашборд запускается через `uvicorn app:app` из произвольного места —
   и два процесса работали с РАЗНЫМИ data/, logs/ и accounts_gui.json.

2. ВАЛИДАЦИЯ ИМЕНИ. Имя аккаунта приходит из URL дашборда
   (/api/accounts/{name}/...) и подставляется в путь. Без проверки
   `DATA_DIR / name` с name="../../Windows/Temp/x" (или абсолютным путём)
   выбрасывает префикс `data/` целиком, а вызывающий код делает mkdir,
   unlink и taskkill по этому пути.
"""
import logging
import os
import re
from pathlib import Path

# Корень проекта: каталог, в котором лежит сам репозиторий (utils/..).
# Переопределяется переменной окружения TRAVIAN_BOT_HOME.
PROJECT_ROOT = Path(os.getenv("TRAVIAN_BOT_HOME") or Path(__file__).resolve().parent.parent)

DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
PIDS_DIR = PROJECT_ROOT / "pids"

# Имя аккаунта = имя каталога и часть имени файла. Разрешаем только то,
# что безопасно на любой ФС и не может уйти вверх по дереву.
ACCOUNT_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class InvalidAccountName(ValueError):
    """Имя аккаунта не прошло валидацию и не может стать путём."""


def is_valid_account_name(name) -> bool:
    return isinstance(name, str) and ACCOUNT_NAME_RE.fullmatch(name) is not None


def safe_account_name(name) -> str:
    """Проверяет имя аккаунта перед подстановкой в путь. Бросает InvalidAccountName."""
    if not is_valid_account_name(name):
        raise InvalidAccountName(
            f"Недопустимое имя аккаунта: {name!r} (разрешены A-Z a-z 0-9 _ - , до 64 символов)"
        )
    return name


# вид файла -> (легаси-имя в корне, новое имя в data/<acc>/)
_KINDS = {
    'cookies':          ('cookies_{name}.json',          'cookies.json'),
    'status':           ('status_{name}.json',           'status.json'),
    'stats':            ('stats_{name}.json',            'stats.json'),
    'build_progress':   ('build_progress_{name}.json',   'build_progress.json'),
    'build_history':    ('build_history_{name}.json',    'build_history.json'),
    'farm_stats':       ('farm_stats_{name}.json',       'farm_stats.json'),
    'history':          ('history_{name}.json',          'history.json'),
    # Ниже — файлы, которые раньше писались прямо в корень репозитория мимо
    # этого модуля. Легаси-имена совпадают с тем, что уже лежит у пользователей,
    # поэтому миграция подхватит их автоматически при первом обращении.
    'cooldowns':        ('cooldowns_{name}.json',        'cooldowns.json'),
    'occupied_oases':   ('occupied_oases_{name}.json',   'occupied_oases.json'),
    'unoccupied_oases': ('unoccupied_oases_{name}.json', 'unoccupied_oases.json'),
    'croppers':         ('croppers_{name}.json',         'croppers.json'),
    'fingerprint':      ('fingerprint_{name}.json',      'fingerprint.json'),
    'command':          ('command_{name}.json',          'command.json'),
    'settings':         ('bot_settings_{name}.json',     'settings.json'),
}


def account_dir(name: str) -> Path:
    """Каталог данных аккаунта (создаётся при обращении)."""
    d = DATA_DIR / safe_account_name(name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def account_file(name: str, kind: str) -> Path:
    """
    Путь к файлу аккаунта данного вида.
    Однократно мигрирует легаси-файл из корня в data/<acc>/.
    """
    if kind not in _KINDS:
        raise KeyError(f"Неизвестный вид файла аккаунта: {kind!r}")
    legacy_tpl, new_name = _KINDS[kind]
    new_path = account_dir(name) / new_name
    legacy = PROJECT_ROOT / legacy_tpl.format(name=name)
    if legacy.exists() and not new_path.exists():
        try:
            legacy.replace(new_path)
            logging.info(f"[paths] Мигрирован {legacy.name} -> {new_path}")
        except OSError as e:
            logging.warning(f"[paths] не удалось мигрировать {legacy.name}: {e}")
            return legacy  # не удалось перенести — работаем со старым
    return new_path


def log_file(name: str, date_str: str) -> Path:
    """Файл лога аккаунта за конкретную дату (logs/<acc>_<YYYY-MM-DD>.log)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / f"{safe_account_name(name)}_{date_str}.log"


def process_log_file(name: str) -> Path:
    """Файл, в который дашборд перенаправляет stdout/stderr процесса бота."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / f"{safe_account_name(name)}_process.log"


def pid_file(name: str) -> Path:
    """PID-файл процесса аккаунта."""
    PIDS_DIR.mkdir(parents=True, exist_ok=True)
    return PIDS_DIR / f"{safe_account_name(name)}.pid"
