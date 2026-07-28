"""
gui.py — десктопная панель управления Travian Bot.

Запуск:
    python gui.py
    (или start.bat -> пункт [2])

Архитектура
-----------
GUI НЕ дублирует логику бэкенда. Веб-панель (app.py) и это окно — два
равноправных клиента одних и тех же функций:

    реестр аккаунтов   -> utils.accounts
    старт/стоп процесса -> app.start_account / app.stop_account
    настройки          -> utils.settings_store.SettingsStore
    команды боту       -> utils.commands.push_command
    валидация настроек -> app._validate_settings

Поэтому правка настройки из окна мгновенно видна в браузере и наоборот:
обе стороны пишут в один и тот же data/<acc>/settings.json, а бот
перечитывает его по mtime.

Потоки
------
Tk не терпит обращений из чужих потоков. Всё, что может подвиснуть
(stop_account ждёт процесс до 10 секунд, чтение статистики лезет на диск),
уходит в Worker и возвращается в UI через root.after(0, ...).
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import customtkinter as ctk
except ImportError:
    raise SystemExit(
        "\n  Не установлен customtkinter.\n"
        "  Выполни:  pip install -r requirements.txt\n"
        "  (или запусти start.bat и выбери пункт [3])\n"
    )

# Бэкенд переиспользуем как есть.
from app import (  # noqa: E402
    _validate_settings as validate_settings,
    get_last_logs,
    get_store,
    is_alive,
    load_farm_stats,
    load_statsateway := None,  # placeholder
)
