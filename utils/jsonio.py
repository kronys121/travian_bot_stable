"""
Единая безопасная работа с JSON-файлами состояния.

Зачем: половина модулей писала состояние обычным `open(path, "w")`.
Если процесс умирал (или второй поток открывал тот же файл) посреди
`json.dump`, на диске оставался обрезанный файл. Читатели ловили
JSONDecodeError, молча возвращали пустой словарь — и бот терял кулдауны,
список оазисов или куки без единой строчки в логе.

Здесь один правильный способ: пишем во временный файл рядом и делаем
os.replace() — на всех поддерживаемых ФС это атомарная операция, читатель
видит либо старый файл целиком, либо новый целиком.
"""
import json
import logging
import os
import threading
from pathlib import Path

# Один процесс может писать один и тот же файл из нескольких потоков
# (главный поток + поток мониторинга атак). Блокировка на путь защищает
# read-modify-write целиком, а не только сам dump.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def file_lock(path) -> threading.Lock:
    """Возвращает (создавая при первом обращении) блокировку для пути."""
    key = str(Path(path).resolve())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def write_json(path, data, indent: int | None = None) -> bool:
    """
    Атомарно записывает data в path. Возвращает True при успехе.

    Временный файл уникален для процесса и потока: иначе два писателя
    одного файла затирали общий `<path>.tmp` друг у друга и os.replace
    публиковал перемешанный JSON.
    """
    p = Path(path)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        return True
    except Exception as e:
        logging.error(f"❌ Не удалось записать {p.name}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def read_json(path, default=None):
    """
    Читает JSON. Возвращает default, если файла нет.

    ВАЖНО: битый файл — это НЕ то же самое, что отсутствующий. Здесь
    возвращается default, но в лог пишется ERROR, а сам файл сохраняется
    под именем `<name>.corrupt-<pid>.json`, чтобы данные можно было
    восстановить руками. Молча затирать чужие настройки нельзя.
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logging.error(f"❌ Битый JSON в {p.name}: {e}. Файл сохранён как .corrupt-*")
        quarantine(p)
        return default
    except OSError as e:
        logging.error(f"❌ Не удалось прочитать {p.name}: {e}")
        return default


def quarantine(path) -> Path | None:
    """Отодвигает битый файл в сторону, чтобы не потерять его содержимое."""
    p = Path(path)
    try:
        dst = p.with_name(f"{p.name}.corrupt-{os.getpid()}")
        p.replace(dst)
        return dst
    except OSError as e:
        logging.debug(f"quarantine {p}: {e}")
        return None
