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
import json
import time
import tempfile

# Разрешённые команды (GUI не сможет протолкнуть произвольное действие)
ALLOWED_ACTIONS = {"scan", "rescan", "force_farm"}


def _file(name: str) -> str:
    return f"command_{name}.json"


def push_command(name: str, action: str) -> bool:
    """
    Добавляет команду в очередь аккаунта. Вызывается из GUI.
    Возвращает False, если действие не разрешено.
    """
    if action not in ALLOWED_ACTIONS:
        return False

    path = _file(name)
    queue = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                queue = json.load(f) or []
            if not isinstance(queue, list):
                queue = []
        except Exception:
            queue = []

    # не дублируем одинаковую команду, если она уже ждёт
    if not any(c.get("action") == action for c in queue):
        queue.append({"action": action, "ts": time.time()})

    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def pop_commands(name: str) -> list:
    """
    Считывает и ОЧИЩАЕТ очередь команд аккаунта. Вызывается из бота.
    Возвращает список действий (строк), например ["scan"].
    """
    path = _file(name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            queue = json.load(f) or []
    except Exception:
        queue = []

    # удаляем файл сразу, чтобы не выполнить повторно
    try:
        os.remove(path)
    except Exception:
        logging.debug("suppressed error in utils/commands:77", exc_info=True)

    actions = []
    for c in queue:
        a = c.get("action")
        if a in ALLOWED_ACTIONS and a not in actions:
            actions.append(a)
    return actions
