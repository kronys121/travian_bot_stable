"""
Центральный модуль путей файлов аккаунта.

Все файлы аккаунта живут в data/<account>/:
    data/<acc>/cookies.json
    data/<acc>/status.json
    data/<acc>/stats.json
    data/<acc>/build_progress.json
    data/<acc>/build_history.json

Старые файлы в корне (cookies_<acc>.json и т.п.) автоматически
переносятся в data/<acc>/ при первом обращении — миграция бесшовная.
"""
import logging
from pathlib import Path

DATA_DIR = Path("data")

# вид файла -> (легаси-имя в корне, новое имя в data/<acc>/)
_KINDS = {
    'cookies':        ('cookies_{name}.json',        'cookies.json'),
    'status':         ('status_{name}.json',         'status.json'),
    'stats':          ('stats_{name}.json',          'stats.json'),
    'build_progress': ('build_progress_{name}.json', 'build_progress.json'),
    'build_history':  ('build_history_{name}.json',  'build_history.json'),
    'farm_stats':     ('farm_stats_{name}.json',      'farm_stats.json'),
    'history':        ('history_{name}.json',          'history.json'),
}


def account_dir(name: str) -> Path:
    """Каталог данных аккаунта (создаётся при обращении)."""
    d = DATA_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def account_file(name: str, kind: str) -> Path:
    """
    Путь к файлу аккаунта данного вида.
    Однократно мигрирует легаси-файл из корня в data/<acc>/.
    """
    legacy_tpl, new_name = _KINDS[kind]
    new_path = account_dir(name) / new_name
    legacy = Path(legacy_tpl.format(name=name))
    if legacy.exists() and not new_path.exists():
        try:
            legacy.replace(new_path)
            logging.info(f"[paths] Мигрирован {legacy} -> {new_path}")
        except Exception as e:
            logging.debug(f"[paths] миграция {legacy}: {e}")
            return legacy  # не удалось перенести — работаем со старым
    return new_path
