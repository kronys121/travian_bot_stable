import os

# ==========================================
# ПЛАН ДЛЯ x1 (СТАНДАРТ)
# Упор на экономику (поля до 5-6 уровня).
# Ратуша не строится. Склады средние.
# ==========================================
PLAN_X1 = [
    {"location": "dorf2.php", "gid": "15", "name": "Main Building", "target_level": 3},
    {"location": "dorf1.php", "gid": "1", "name": "Woodcutters", "target_level": 2},
    {"location": "dorf1.php", "gid": "2", "name": "Clay Pits", "target_level": 2},
    {"location": "dorf1.php", "gid": "3", "name": "Iron Mines", "target_level": 2},
    {"location": "dorf1.php", "gid": "4", "name": "Croplands", "target_level": 2},
    {"location": "dorf2.php", "gid": "16", "name": "Rally Point", "target_level": 1},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse", "target_level": 3},
    {"location": "dorf2.php", "gid": "11", "name": "Granary", "target_level": 3},
    {"location": "dorf2.php", "gid": "23", "name": "Cranny", "target_level": 3},

    # Поднимаем ресурсы до 3
    {"location": "dorf1.php", "gid": "1", "name": "Woodcutters", "target_level": 3},
    {"location": "dorf1.php", "gid": "2", "name": "Clay Pits", "target_level": 3},
    {"location": "dorf1.php", "gid": "3", "name": "Iron Mines", "target_level": 3},
    {"location": "dorf1.php", "gid": "4", "name": "Croplands", "target_level": 3},

    {"location": "dorf2.php", "gid": "15", "name": "Main Building", "target_level": 5},
    {"location": "dorf2.php", "gid": "17", "name": "Marketplace", "target_level": 1},

    # Поднимаем ресурсы до 4
    {"location": "dorf1.php", "gid": "1", "name": "Woodcutters", "target_level": 4},
    {"location": "dorf1.php", "gid": "2", "name": "Clay Pits", "target_level": 4},
    {"location": "dorf1.php", "gid": "3", "name": "Iron Mines", "target_level": 4},
    {"location": "dorf1.php", "gid": "4", "name": "Croplands", "target_level": 4},

    {"location": "dorf2.php", "gid": "10", "name": "Warehouse", "target_level": 6},
    {"location": "dorf2.php", "gid": "11", "name": "Granary", "target_level": 5},

    # Поднимаем ресурсы до 5
    {"location": "dorf1.php", "gid": "1", "name": "Woodcutters", "target_level": 5},
    {"location": "dorf1.php", "gid": "2", "name": "Clay Pits", "target_level": 5},
    {"location": "dorf1.php", "gid": "3", "name": "Iron Mines", "target_level": 5},
    {"location": "dorf1.php", "gid": "4", "name": "Croplands", "target_level": 5},

    {"location": "dorf2.php", "gid": "23", "name": "Crannies", "target_level": 7},
    {"location": "dorf2.php", "gid": "18", "name": "Embassy", "target_level": 3},

    # Пуш к резиденции
    {"location": "dorf2.php", "gid": "15", "name": "Main Building", "target_level": 10},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse", "target_level": 8},
    {"location": "dorf2.php", "gid": "11", "name": "Granary", "target_level": 7},
    {"location": "dorf2.php", "gid": "25", "name": "Residence", "target_level": 5},
    {"location": "dorf2.php", "gid": "25", "name": "Residence", "target_level": 8},
    {"location": "dorf2.php", "gid": "25", "name": "Residence", "target_level": 10}
]

# ==========================================
# ПЛАН ДЛЯ x3 / x5 (СКОРОСТЬ)
# Упор на быстрые склады (до 18 ур.), Ратушу (до 10 ур.)
# для генерации Единиц Культуры (ЕК).
# ==========================================
# FIX: план очищен от десятков повторяющихся шагов —
# каждый дубль (например, "Woodcutters → 2" пять раз подряд)
# заставлял бота впустую прогонять dorf1 на каждом круге.
# SmartBuilder поднимает ВСЕ здания gid до target_level за один шаг плана.
# ------------------------------------------------------------------
# PLAN_X3 — "Non-raiding x3/x5" by Tikiii971 / Drillbit (2025-01).
# Источник: https://unofficialtravian.com/2025/01/guide-start-x3-x5-non-raiding-version/
# Герой качается в ресурсы, не фармит — доход сопоставим с фармом на 5x,
# но без случайных событий. Цель — основать вторую деревню за 1 вечеринку.
# Примечания к gid:
#   Wall (gid 33 = Palisade у Галлов, 31 = Earth Wall у Тевтов, 32 = City Wall у Римлян)
#   — здесь используем 32 как нейтральный; Smart Builder подберёт нужный gid по племени.
# ------------------------------------------------------------------
PLAN_X3 = [
    # 1. Все поля до уровня 2 (по одному каждого типа)
    {"location": "dorf1.php", "gid": "1", "name": "Woodcutters", "target_level": 2},
    {"location": "dorf1.php", "gid": "2", "name": "Clay Pits",   "target_level": 2},
    {"location": "dorf1.php", "gid": "3", "name": "Iron Mines",  "target_level": 2},
    {"location": "dorf1.php", "gid": "4", "name": "Croplands",   "target_level": 2},
    # 2. Склад
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",  "target_level": 1},
    # 3. Амбар
    {"location": "dorf2.php", "gid": "11", "name": "Granary",    "target_level": 1},
    # 4. Посольство
    {"location": "dorf2.php", "gid": "18", "name": "Embassy",    "target_level": 1},
    # 5. Маскировка lv3 (квест 50 КО)
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",     "target_level": 3},
    # 6. ГЗ lv3 (квест / ускорение стройки)
    {"location": "dorf2.php", "gid": "15", "name": "Main Building", "target_level": 3},
    # 7. Стена lv3 (у каждого племени своя — Smart Builder подберёт нужный gid)
    {"location": "dorf2.php", "gid": "32", "name": "City Wall",  "target_level": 3},
    # 8. Рынок lv3
    {"location": "dorf2.php", "gid": "17", "name": "Marketplace", "target_level": 3},
    # 9. Все пашни до 2
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",  "target_level": 2},
    # 10. Все леса до 2
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters", "target_level": 2},
    # 11. Вся глина до 2
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",  "target_level": 2},
    # 12. Всё железо до 2 (квест 50 CP при первом Iron 1)
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines", "target_level": 2},
    # 13-16. По одному полю каждого типа до 4
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",  "target_level": 4},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters", "target_level": 4},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",  "target_level": 4},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines", "target_level": 4},
    # 17. Казармы lv1
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",   "target_level": 1},
    # 18. ГЗ lv7
    {"location": "dorf2.php", "gid": "15", "name": "Main Building", "target_level": 7},
    # 19. Склад lv3
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",  "target_level": 3},
    # 20. Амбар lv3
    {"location": "dorf2.php", "gid": "11", "name": "Granary",    "target_level": 3},
    # 21. Все леса до 3 (квест 50 CP при первом Wood 3)
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters", "target_level": 3},
    # 22. Всё железо до 3
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines", "target_level": 3},
    # 23. Вся глина до 3
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",  "target_level": 3},
    # 24. Казармы lv3 (квест 100 Pop)
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",   "target_level": 3},
    # 25. Академия lv1
    {"location": "dorf2.php", "gid": "22", "name": "Academy",    "target_level": 1},
    # 26. Все пашни до 3
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",  "target_level": 3},
    # 27. Резиденция lv1
    {"location": "dorf2.php", "gid": "25", "name": "Residence",  "target_level": 1},
    # 28. Маскировка lv10
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",     "target_level": 10},
    # 29. Рынок lv7
    {"location": "dorf2.php", "gid": "17", "name": "Marketplace", "target_level": 7},
    # 30. ГЗ lv10 (требуется для Ратуши)
    {"location": "dorf2.php", "gid": "15", "name": "Main Building", "target_level": 10},
    # 31. Академия lv10
    {"location": "dorf2.php", "gid": "22", "name": "Academy",    "target_level": 10},
    # 32. Мастерская lv1
    {"location": "dorf2.php", "gid": "21", "name": "Workshop",   "target_level": 1},
    # 33. Ратуша lv1 (требует ГЗ lv10)
    {"location": "dorf2.php", "gid": "24", "name": "Town Hall",  "target_level": 1},
    # 34. Резиденция lv10
    {"location": "dorf2.php", "gid": "25", "name": "Residence",  "target_level": 10},
    # 35. Нанять 3 поселенцев (action=train_settler)
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",   "target_level": 3,
     "action": "train_settler"},
    # 36. Малая вечеринка → основать вторую деревню
    {"location": "dorf2.php", "gid": "24", "name": "Town Hall",  "target_level": 1,
     "action": "celebrate"},
]


class BotConfig:
    def __init__(self):
        self._base_url = None
        self.server = "ts30.x3.international.travian.com"
        self.cookie_file = "cookies.json"
        self.headless = False

        # По умолчанию ставим пустой план. Он будет заполнен при старте.
        self.BUILD_PLAN = []

    def set_rate(self, rate: str):
        """Устанавливает план постройки в зависимости от скорости сервера."""
        if rate == '1':
            self.BUILD_PLAN = PLAN_X1
        else:
            self.BUILD_PLAN = PLAN_X3

    @property
    def base_url(self):
        if self._base_url:
            return self._base_url
        return f"https://{self.server}"

    @base_url.setter
    def base_url(self, value):
        self._base_url = value

    @property
    def login_url(self):
        return f"{self.base_url}/dorf1.php"

    @property
    def tasks_url(self):
        return f"{self.base_url}/tasks"

    @property
    def hero_attributes_url(self):
        return f"{self.base_url}/hero/attributes"

    @property
    def hero_adventure_url(self):
        return f"{self.base_url}/hero/adventures"
