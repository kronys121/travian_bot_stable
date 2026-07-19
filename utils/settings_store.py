import json
import logging
import os
import threading
import time
from pathlib import Path

DEFAULT_SETTINGS = {
    "features": {
        "farm_enabled": True,
        "hero_only": False,          # фарм ТОЛЬКО героем (без войск)
        "hero_with_troops": False,   # герой (по животным) + войска (по пустым) в одном цикле
        "hero_farm_enabled": False,  # отдельная задача планировщика: фарм героем по животным
        "build_enabled": True,
        "build_night_enabled": False,  # строить ночью; False = пауза стройки в часы sleep_hours
        "build_use_ads": True,        # строить через рекламу (section2, -25% времени)
        "tasks_enabled": True,
        "adventure_enabled": True,
        "adv_shorten_enabled": False,     # смотреть видео для сокращения времени приключения
        "adv_difficulty_enabled": False,  # повышать сложность приключения через видео
        "celebration_enabled": False,     # авто-праздники в Ратуше (КО)
        "smithy_enabled": False,          # авто-улучшение войск в кузнице
        "smithy_use_ads": False,          # улучшать войска в кузнице через рекламу (-25% времени)
        "train_enabled": False,           # по умолчанию ВЫКЛ — включается из GUI
        "npc_trade_enabled": False,   # по умолчанию ВЫКЛ — включается из GUI
        "transfer_enabled": False,    # переброска ресурсов между деревнями (ВЫКЛ)
        "reports_enabled": True,      # читать боевые отчёты (добыча/потери/профит)
        "grouped_cycle": False,       # обход деревень «пачкой»: за один заход в деревню — все действия
        "evasion_enabled": True,
    },
    "farm": {
        # Племя аккаунта (для имён юнитов в GUI): roman | teuton | gaul |
        # egyptian | hun | spartan. На логику бота не влияет — он работает
        # по индексам troop_type_index.
        "tribe": "roman",
        "troops_per_raid": 10,
        "troop_type_index": 1,          # legacy-фолбэк — заменён farm_troop_indices
        "farm_troop_indices": [],       # список индексов юнитов для фарма (пусто = [troop_type_index])
        "max_distance": 0.0,
        "scan_radius": 5,
        "interval_minutes": 60,
        "cooldown_minutes": 60,
        # Скорость войск (клеток/час) для расчёта кулдауна с учётом времени
        # возврата. 0 = выкл (используется только cooldown_minutes).
        "troop_speed_tph": 0,
        # Макс. допустимая защита животных для обычного набега. Прямо перед
        # отправкой оазис перепроверяется: если защита животных больше этого
        # значения — набег отменяется (цель остаётся в списке).
        # 0 = отменять при ЛЮБЫХ животных.
        "max_animal_defense": 0,
    },
    "training": {
        # Одиночный формат (фолбэк, если queue пуст)
        "troop_type_index": 1,
        "target_count": 100,
        "building": "barracks",   # barracks | stable
        # Минимальный порог в очереди здания: не заказывать если уже >= N юнитов
        # стоят в очереди тренировки казармы/конюшни. 0 = выкл.
        "min_queue_size": 0,
        # Глобальная очередь (применяется если деревня не найдена в village_queues)
        # [{"troop_type_index": 1, "target_count": 200, "building": "barracks"}, ...]
        "queue": [],
        # Очереди по деревням: {"Столица": [...queue...], "Деревня 2": [...]}
        # Если деревня не найдена — используется глобальная queue выше.
        "village_queues": {},
    },
    "smithy": {
        # Очередь улучшений кузницы (сортируется по priority перед выполнением).
        # Каждая запись: {troop_type_index, target_level, priority, enabled}
        # target_level: 1-20, priority: меньше число = выше приоритет (1 = первый)
        # enabled: true/false — можно временно отключить без удаления строки
        "upgrade_queue": [],
        # Тумблер включается из раздела features
    },
    "build": {
        # Назначение шаблона плана застройки для каждой деревни.
        # Ключ — village_key (имя деревни или её id), значение — id шаблона.
        # Доступные id: x1 | x3 | farmer | capital | offense | defense | none
        # Если деревня не найдена — используется глобальный config.BUILD_PLAN.
        "village_plans": {},
    },
    "trade": {
        "npc_threshold_pct": 85,
        # Переброска ресурсов между своими деревнями по расписанию.
        # transfer_rules: [{"from": "<имя деревни>", "to_x": int, "to_y": int,
        #                   "res": ["wood","clay","iron","crop"], "reserve": int}]
        "transfer_interval_min": 60,
        "transfer_rules": [],
    },
    "night": {
        # Ночной режим: бот «спит» в этом окне (кроме стройки/кузницы, если
        # включена «стройка ночью»). Часы серверные, 0-23.
        "enabled": True,
        "start": 2,   # начало ночи (час)
        "end": 8,     # конец ночи (час); при переходе через полночь start > end
    },
    "task_order": {
        # Порядок выполнения периодических задач (перетаскивается в GUI).
        # Чем выше в списке — тем важнее: задача с меньшим индексом выполнится
        # первой, когда несколько задач готовы к запуску одновременно.
        # Срочные задачи (evade/scan/rescan) сюда не входят — они всегда важнее.
        "order": [
            "farm", "hero_farm", "build", "train", "tasks", "adventure",
            "celebration", "smithy", "npc_trade", "transfer", "stats", "reports",
        ],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно накладывает override на base (не мутирует аргументы)."""
    result = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        elif v is not None:
            result[k] = v
    return result


class SettingsStore:
    """
    Единый источник настроек аккаунта: bot_settings_{name}.json.

    - Бот вызывает get()/section() перед каждой задачей — файл перечитывается,
      если изменился на диске (mtime) => настройки применяются В РЕАЛЬНОМ ВРЕМЕНИ.
    - Дашборд (app.py) пишет в этот же файл через save().
    - Запись атомарная (tmp + os.replace), чтобы бот не прочитал полфайла.
    """

    def __init__(self, account_name: str, yaml_account_config: dict = None):
        self.account_name = account_name
        self.path = Path(f"bot_settings_{account_name}.json")
        self._lock = threading.Lock()
        self._mtime = 0.0
        self._data = {}
        self._init_from_yaml(yaml_account_config or {})

    # ---------- инициализация ----------

    def _init_from_yaml(self, acc: dict):
        """
        Первый запуск: создаём файл из config.yaml + дефолтов.
        Если файл уже есть — YAML используется только для недостающих ключей,
        чтобы не перетирать то, что пользователь выставил в GUI.
        """
        from_yaml = {
            "features": {
                "train_enabled": (acc.get("training") or {}).get("enabled", False),
                "npc_trade_enabled": (acc.get("trade") or {}).get("npc_enabled", False),
                "evasion_enabled": acc.get("evasion_enabled", True),
            },
            "farm": {k: v for k, v in (acc.get("farm") or {}).items()},
            "training": {k: v for k, v in (acc.get("training") or {}).items() if k != "enabled"},
            "trade": {k: v for k, v in (acc.get("trade") or {}).items() if k != "npc_enabled"},
        }
        # нормализуем ключ порога NPC
        if "npc_threshold_pct" not in from_yaml["trade"] and "npc_threshold" in from_yaml["trade"]:
            from_yaml["trade"]["npc_threshold_pct"] = from_yaml["trade"].pop("npc_threshold")

        # Ночное окно: переносим из config.yaml sleep_hours=[start,end], если задано.
        sh = acc.get("sleep_hours")
        if isinstance(sh, (list, tuple)) and len(sh) >= 2:
            from_yaml["night"] = {"enabled": True, "start": int(sh[0]), "end": int(sh[1])}

        defaults = _deep_merge(DEFAULT_SETTINGS, from_yaml)

        with self._lock:
            existing = self._read_file()
            if existing is None:
                self._data = defaults
                self._write_file(self._data)
            else:
                # существующий файл главнее, дефолты — только для недостающих ключей
                self._data = _deep_merge(defaults, existing)
            try:
                self._mtime = self.path.stat().st_mtime
            except OSError:
                self._mtime = 0.0

    # ---------- файл ----------

    def _read_file(self):
        try:
            if self.path.exists() and self.path.stat().st_size > 0:
                return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as e:
            logging.warning(f"⚠️ SettingsStore: не удалось прочитать {self.path.name}: {e}")
        return None

    def _write_file(self, data: dict):
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception as e:
            logging.error(f"❌ SettingsStore: ошибка записи {self.path.name}: {e}")

    # ---------- API ----------

    def reload_if_changed(self):
        """Перечитывает файл, если он менялся (например, из дашборда)."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return
        # != вместо <=: на ФС с грубой гранулярностью mtime быстрая запись
        # из GUI могла получить тот же timestamp и не подхватиться
        if mtime == self._mtime:
            return
        with self._lock:
            fresh = self._read_file()
            if fresh is not None:
                self._data = _deep_merge(DEFAULT_SETTINGS, fresh)
                self._mtime = mtime
                logging.info("🔄 Настройки перезагружены (изменены в GUI).")

    def section(self, name: str) -> dict:
        """Актуальная секция настроек ('features', 'farm', 'training', 'trade')."""
        self.reload_if_changed()
        with self._lock:
            return dict(self._data.get(name, {}))

    def feature(self, name: str, default: bool = False) -> bool:
        return bool(self.section("features").get(name, default))

    def get_all(self) -> dict:
        self.reload_if_changed()
        with self._lock:
            return json.loads(json.dumps(self._data))

    def save(self, updates: dict):
        """Накладывает updates и атомарно сохраняет (используется дашбордом)."""
        with self._lock:
            self._data = _deep_merge(self._data, updates)
            self._write_file(self._data)
            self._mtime = time.time()
