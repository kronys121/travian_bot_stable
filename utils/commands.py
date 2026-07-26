"""
Простой файловый мост команд между GUI (app.py) и запущенным ботом (runner.py).

GUI и каждый бот — РАЗНЫЕ процессы, общей памяти нет. Статус бот отдаёт
через status_{name}.json; ровно так же принимаем команды в обратную сторону:
GUI дописывает команду в command_{name}.json, бот вычитывает её в idle-цикле
планировщика и очищает файл.

Формат файла — список команд (на случай если накопилось несколько):
    [{"action": "scan", "ts": 1712345678.9}, ...]
"""

import logging
import os
import time
from pathlib import Path

from utils.jsonio import file_lock, read_json, write_json
from utils.paths import account_file

# Разрешённые команды (GUI не сможет протолкнуть произвольное действие)
ALLOWED_ACTIONS = {"scan", "rescan", "force_farm"}


def _file(name: str) -> Path:
    # account_file валидирует имя аккаунта: оно приходит из URL дашборда
    # и раньше подставлялось в путь без проверки.
    return account_file(name, 'command')


def push_command(name: str, action: str) -> bool:
    """
    Добавляет команду в очередь аккаунта. Вызывается из GUI.
    Возвращает False, если действие не разрешено или запись не удалась.
    """
    if action not in ALLOWED_ACTIONS:
        return False

    path = _file(name)
    with file_lock(path):
        queue = read_json(path, default=[])
        if not isinstance(queue, list):
            queue = []
        # не дублируем одинаковую команду, если она уже ждёт
        queue = [c for c in queue if isinstance(c, dict)]
        if not any(c.get("action") == action for c in queue):
            queue.append({"action": action, "ts": time.time()})
        return write_json(path, queue)


def pop_commands(name: str) -> list:
    """
    Считывает и ОЧИЩАЕТ очередь команд аккаунта. Вызывается из бота.
    Возвращает список действий (строк), например ["scan"].

    Забирает файл через os.replace на «.taken» ДО чтения. Переименование
    атомарно, поэтому команда, положенная дашбордом между чтением и удалением,
    больше не теряется — она останется в новом command.json.
    """
    path = _file(name)
    if not path.exists():
        return []
    taken = path.with_name(path.name + f".taken.{os.getpid()}")
    try:
        os.replace(path, taken)
    except OSError as e:
        logging.debug(f"pop_commands: файл команд занят ({e}) — попробуем в следующий раз.")
        return []

    queue = read_json(taken, default=[])
    try:
        taken.unlink(missing_ok=True)
    except OSError as e:
        logging.debug(f"pop_commands: не удалось удалить {taken.name}: {e}")

    actions = []
    for c in queue if isinstance(queue, list) else []:
        a = c.get("action") if isinstance(c, dict) else None
        if a in ALLOWED_ACTIONS and a not in actions:
            actions.append(a)
    return actions
