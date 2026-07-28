"""Слой данных десктопной панели.

Здесь всё, что не рисует: справочники настроек, чтение состояния,
фоновые задачи и управление процессом веб-панели.

GUI и веб-панель — два равноправных клиента одного бэкенда: оба зовут
те же функции из app.py и utils/, пишут в те же data/<acc>/*.json.
Поэтому правка в окне сразу видна в браузере и наоборот.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    get_store,
    is_alive,
    load_stats,
    load_status,
    proc_running,
)
from utils.accounts import load_accounts  # noqa: E402
from utils.paths import is_valid_account_name  # noqa: E402

try:
    from config.build_templates import TEMPLATES as BUILD_TEMPLATES
except Exception:
    # Шаблоны — не критичная часть: окно обязано открыться и без них.
    BUILD_TEMPLATES = {"x3": None}

DEFAULT_PORT = 8080
REFRESH_MS = 4000
LOG_REFRESH_MS = 3000


# ============================ СПРАВОЧНИКИ НАСТРОЕК ============================

# Простые тумблеры features. Флаги фарма сюда НЕ входят: это не три
# независимые галочки, а один режим из трёх (см. FARM_MODES).
FEATURE_GROUPS = [
    ("Строительство", [
        ("build_enabled", "Автостройка", "Строит по шаблону или плану деревни"),
        ("build_night_enabled", "Строить ночью", "Стройка работает в ночном окне"),
        ("build_use_ads", "Ускорять рекламой", "Смотреть ролики ради ускорения"),
    ]),
    ("Войска", [
        ("train_enabled", "Обучение", "Держит очередь казармы заполненной"),
        ("smithy_enabled", "Кузница", "Апгрейд войск по очереди"),
        ("smithy_use_ads", "Реклама для кузницы", "Ускорять апгрейды рекламой"),
        ("evasion_enabled", "Эвакуация при атаке", "Уводит войска перед приходом атаки"),
    ]),
    ("Герой и задания", [
        ("adventure_enabled", "Приключения", "Отправляет героя в походы"),
        ("adv_shorten_enabled", "Сокращать поход", "Жмёт кнопку ускорения"),
        ("adv_difficulty_enabled", "Фильтр сложности", "Учитывать сложность приключения"),
        ("tasks_enabled", "Задания", "Забирает награды"),
        ("celebration_enabled", "Праздники", "Проводит праздники в ратуше"),
    ]),
    ("Экономика", [
        ("npc_trade_enabled", "NPC-торговля", "Балансирует ресурсы через NPC"),
        ("transfer_enabled", "Перевозка ресурсов", "Шлёт ресурсы между деревнями"),
        ("reports_enabled", "Разбор отчётов", "Читает отчёты и копит статистику"),
        ("grouped_cycle", "Групповой цикл", "Обходит все деревни одним проходом"),
    ]),
]

# Режим фарма: три варианта, разложенные в два булевых флага.
# Оба флага сразу — невалидное состояние, именно поэтому здесь
# радиокнопки, а не три независимых тумблера.
FARM_MODES = [
    ("troops", "Только войска", {"hero_only": False, "hero_with_troops": False}),
    ("hero", "Только герой", {"hero_only": True, "hero_with_troops": False}),
    ("both", "Герой и войска", {"hero_only": False, "hero_with_troops": True}),
]


def farm_mode_of(features: dict) -> str:
    if features.get("hero_with_troops"):
        return "both"
    if features.get("hero_only"):
        return "hero"
    return "troops"


# (ключ, подпись, min, max, тип).
# Границы ОБЯЗАНЫ совпадать с app._SETTINGS_BOUNDS: иначе окно разрешит
# ввести то, что валидатор отвергнет при сохранении.
NUMERIC = {
    "farm": [
        ("troops_per_raid", "Войск на набег", 1, 5000, int),
        ("troop_type_index", "Тип юнита (1–10)", 1, 10, int),
        ("scan_radius", "Радиус скана", 1, 50, int),
        ("max_distance", "Макс. дистанция", 0, 500, float),
        ("interval_minutes", "Интервал фарма, мин", 1, 1440, int),
        ("cooldown_minutes", "Кулдаун оазиса, мин", 0, 10080, int),
        ("troop_speed_tph", "Скорость юнита, кл/ч", 0, 100, int),
        ("max_animal_defense", "Макс. защита зверей", 0, 10 ** 9, int),
        ("hero_min_health", "Мин. здоровье героя, %", 0, 100, int),
        ("hero_safety_pct", "Запас прочности героя, %", 0, 10000, int),
    ],
    "training": [
        ("troop_type_index", "Тип юнита (1–10)", 1, 10, int),
        ("target_count", "Целевое количество", 0, 1000000, int),
        ("min_queue_size", "Мин. очередь", 0, 100000, int),
        ("spend_pct", "Тратить ресурсов, %", 1, 100, int),
        ("max_batch", "Макс. пачка", 0, 1000000, int),
    ],
    "trade": [
        ("npc_threshold_pct", "Порог NPC, %", 0, 100, int),
        ("transfer_interval_min", "Интервал перевозки, мин", 1, 10080, int),
    ],
    "night": [
        ("start", "Начало ночи (час)", 0, 23, int),
        ("end", "Конец ночи (час)", 0, 23, int),
    ],
}

NUMERIC_TITLES = {
    "farm": "Фарм оазисов",
    "training": "Обучение войск",
    "trade": "Торговля и перевозка",
    "night": "Ночной режим",
}

TRIBES = ["roman", "teuton", "gaul", "egyptian", "hun", "spartan"]
TRIBE_LABELS = {
    "roman": "Римляне", "teuton": "Германцы", "gaul": "Галлы",
    "egyptian": "Египтяне", "hun": "Гунны", "spartan": "Спартанцы",
}
TRIBE_BY_LABEL = {v: k for k, v in TRIBE_LABELS.items()}

TASK_LABELS = {
    "farm": "Фарм оазисов",
    "build": "Стройка",
    "train": "Обучение войск",
    "tasks": "Задания",
    "adventure": "Приключения",
    "celebration": "Праздники",
    "smithy": "Кузница",
    "npc_trade": "NPC-торговля",
    "transfer": "Перевозка ресурсов",
    "stats": "Сбор статистики",
    "reports": "Разбор отчётов",
}


# ================================ ФОРМАТ ================================

def err_text(exc: BaseException) -> str:
    """Читаемый текст ошибки.

    Валидатор настроек лежит в app.py и кидает HTTPException: полезный
    текст у него в .detail, а str(e) даёт бесполезное "422: ...".
    """
    detail = getattr(exc, "detail", None)
    if detail:
        return str(detail)
    return str(exc) or exc.__class__.__name__


def fmt_num(value, dash: str = "—") -> str:
    try:
        return f"{int(float(value)):,}".replace(",", "\u2009")
    except (TypeError, ValueError):
        return dash


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return str(iso)


def num_or(value, default, caster=int):
    try:
        return caster(value)
    except (TypeError, ValueError):
        return default


# ============================== ФОНОВЫЕ ЗАДАЧИ ==============================

class Worker(threading.Thread):
    """Фоновая задача с возвратом результата в Tk-поток через after().

    Tk не потокобезопасен: трогать виджеты из чужого потока нельзя,
    поэтому результат всегда возвращается через очередь событий.

    Сюда обязано уходить всё, что трогает диск или ждёт процесс:
    stop_account() ждёт завершения до 10 секунд и морозит окно.
    """

    def __init__(self, widget: tk.Misc, fn, on_done=None, on_error=None):
        super().__init__(daemon=True)
        self._widget = widget
        self._fn = fn
        self._on_done = on_done
        self._on_error = on_error

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            if self._on_error:
                # exc через аргумент по умолчанию: иначе замыкание увидит
                # уже очищенную переменную (Python удаляет её после except).
                self._widget.after(0, lambda e=exc: self._on_error(e))
            return
        if self._on_done:
            self._widget.after(0, lambda r=result: self._on_done(r))


def collect_snapshot() -> list[dict]:
    """Состояние всех аккаунтов. Вызывать только из Worker: чтение диска."""
    out: list[dict] = []
    for acc in load_accounts():
        name = acc.get("name", "")
        if not is_valid_account_name(name):
            continue  # та же защита, что и в /api/accounts: имя — это имя папки
        status = load_status(name)
        try:
            settings = get_store(name).get_all()
        except Exception:
            settings = {}
        out.append({
            "name": name,
            "account": acc,
            "status": status,
            "alive": is_alive(status),
            "running": proc_running(name) or is_alive(status),
            "stats": load_stats(name),
            "settings": settings,
        })
    return out


# ============================== ВЕБ-ПАНЕЛЬ ==============================

class WebServer:
    """Управление процессом `uvicorn app:app --host 127.0.0.1 --port <порт>`.

    Отдельный процесс, а не поток внутри GUI: uvicorn ставит свои
    обработчики сигналов и перенастраивает logging под себя — в общем
    процессе это ломает и цикл Tk, и логи самого окна.
    """

    def __init__(self, port: int = DEFAULT_PORT):
        self.proc: subprocess.Popen | None = None
        self.port = port

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @staticmethod
    def command(port: int) -> list[str]:
        # sys.executable + "-m uvicorn", а не голый "uvicorn": в venv без
        # активации скрипта uvicorn.exe может не оказаться в PATH.
        return [sys.executable, "-m", "uvicorn", "app:app",
                "--host", "127.0.0.1", "--port", str(port)]

    def command_text(self, port: int | None = None) -> str:
        return "uvicorn app:app --host 127.0.0.1 --port %d" % (port or self.port)

    def start(self, port: int) -> None:
        if self.running():
            return
        self.port = port
        kwargs: dict = {}
        if os.name == "nt":
            # без этого рядом с окном всплывает чёрная консоль
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(self.command(port), cwd=str(ROOT), **kwargs)

    def stop(self) -> None:
        if not self.running():
            self.proc = None
            return
        proc = self.proc
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        self.proc = None
