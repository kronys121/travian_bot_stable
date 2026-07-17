# ============================================================
# Готовые шаблоны планов застройки для назначения деревням.
# Каждый шаблон — список шагов (location / gid / name / target_level).
# Поле gid соответствует ID здания в Travian Legends.
#
# Шаблон выбирается в GUI для конкретной деревни и сохраняется
# в bot_settings_<acc>.json → build.village_plans.<village_key>.
# _get_build_plan_for_village() в menu_manager приоритизирует
# runtime-настройку из settings над глобальным config.BUILD_PLAN.
# ============================================================

# ------------------------------------------------------------------
# ГАЛЛЫ x1 — стратегия "3 Party Farming" by Caim.
# Цель: основать вторую деревню за 3 вечеринки, попутно фармя оазисы.
# Источник: https://docs.google.com/spreadsheets/d/1A2ku0fdzpJDOefjG8ryUyyxYbXD2_z76IxMUhSERjtE
# gid для галлов: Palisade=33, Stable=20(Pathfinder/TT), Barracks=19
# ------------------------------------------------------------------
PLAN_GAULS_X1 = [
    # --- Ранняя экономика ---
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",    "target_level": 1},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",      "target_level": 2},   # 1x to 2
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",        "target_level": 2},   # 1x to 2
    {"location": "dorf2.php", "gid": "16", "name": "Rally Point",      "target_level": 1},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",        "target_level": 2},   # 1x to 2
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",       "target_level": 2},   # 1x to 2
    {"location": "dorf2.php", "gid": "11", "name": "Granary",          "target_level": 1},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",        "target_level": 1},
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",    "target_level": 3},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",          "target_level": 3},
    {"location": "dorf2.php", "gid": "17", "name": "Marketplace",      "target_level": 1},
    {"location": "dorf2.php", "gid": "17", "name": "Marketplace",      "target_level": 3},
    # все пашни до 2
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",        "target_level": 2},
    # посольство + маскировка
    {"location": "dorf2.php", "gid": "18", "name": "Embassy",          "target_level": 1},
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",           "target_level": 1},
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",           "target_level": 3},
    {"location": "dorf2.php", "gid": "33", "name": "Palisade",         "target_level": 1},   # галльская стена
    {"location": "dorf2.php", "gid": "33", "name": "Palisade",         "target_level": 3},
    # все лесорубы / глина / железо до 2
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",      "target_level": 2},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",        "target_level": 2},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",       "target_level": 2},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",        "target_level": 3},
    # --- Первые войска и экономика 4-го уровня ---
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",         "target_level": 1},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",      "target_level": 4},   # 1x to 4
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",        "target_level": 4},   # 1x to 4
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",        "target_level": 4},   # 1x to 4
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",       "target_level": 4},   # 1x to 4
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",           "target_level": 6},
    # --- Сильное ГЗ + Академия + Кузница ---
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",    "target_level": 7},
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",         "target_level": 3},
    {"location": "dorf2.php", "gid": "22", "name": "Academy",          "target_level": 1},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",        "target_level": 3},   # 1x to 3
    {"location": "dorf2.php", "gid": "13", "name": "Smithy",           "target_level": 1},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",       "target_level": 3},   # all to 3
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",        "target_level": 3},   # all to 3
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",      "target_level": 3},   # all to 3
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",        "target_level": 3},   # all to 3
    # --- Конюшня + Гром + Резиденция ---
    {"location": "dorf2.php", "gid": "20", "name": "Stable",           "target_level": 1},
    {"location": "dorf2.php", "gid": "22", "name": "Academy",          "target_level": 5},
    {"location": "dorf2.php", "gid": "20", "name": "Stable",           "target_level": 3},
    {"location": "dorf2.php", "gid": "25", "name": "Residence",        "target_level": 1},
    # --- Все поля до 5 ---
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",        "target_level": 5},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",        "target_level": 5},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",      "target_level": 5},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",       "target_level": 5},
    # --- КО-машина: Ратуша, Рынок, Посольство ---
    {"location": "dorf2.php", "gid": "17", "name": "Marketplace",      "target_level": 7},
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",           "target_level": 10},
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",           "target_level": 3},   # 7x to 3
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",    "target_level": 12},
    {"location": "dorf2.php", "gid": "22", "name": "Academy",          "target_level": 10},
    {"location": "dorf2.php", "gid": "21", "name": "Workshop",         "target_level": 1},
    {"location": "dorf2.php", "gid": "24", "name": "Town Hall",        "target_level": 1},
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",           "target_level": 7},   # 7x to 7
    {"location": "dorf2.php", "gid": "18", "name": "Embassy",          "target_level": 6},
    {"location": "dorf2.php", "gid": "17", "name": "Marketplace",      "target_level": 12},
    {"location": "dorf2.php", "gid": "25", "name": "Residence",        "target_level": 3},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",          "target_level": 7},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",        "target_level": 7},
    # --- Warehouse до 8 + вечеринки ---
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",        "target_level": 8},
    # Party 1 (action=celebrate — обрабатывается отдельно в execute_plan)
    {"location": "dorf2.php", "gid": "24", "name": "Town Hall",        "target_level": 1,
     "action": "celebrate"},
    {"location": "dorf2.php", "gid": "25", "name": "Residence",        "target_level": 10},
    # Party 3
    {"location": "dorf2.php", "gid": "24", "name": "Town Hall",        "target_level": 1,
     "action": "celebrate"},
    # Поселенцы x3 (action=train_settler)
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",         "target_level": 3,
     "action": "train_settler"},
    # Party 4
    {"location": "dorf2.php", "gid": "24", "name": "Town Hall",        "target_level": 1,
     "action": "celebrate"},
]

# ------------------------------------------------------------------
# ФАРМЕР (6-кроп) — акцент на ресурсы, минимум зданий.
# Цель: быстрое поле 5+5, склады на 10+, дать войска для фарма.
# Подходит для вторичных деревень без Резиденции / Дворца.
# ------------------------------------------------------------------
PLAN_FARMER = [
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",  "target_level": 3},
    {"location": "dorf2.php", "gid": "16", "name": "Rally Point",    "target_level": 1},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 3},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 3},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 3},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 3},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 5},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 5},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 5},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 5},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 5},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 5},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 8},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 8},
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",       "target_level": 3},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 7},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 7},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 7},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 7},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 10},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 10},
]

# ------------------------------------------------------------------
# СТОЛИЦА / КАПИТАЛКА (9-кроп или обычная) — полное развитие.
# Цель: Дворец/Резиденция, максимальные склады, Ратуша, полная экономика.
# ------------------------------------------------------------------
PLAN_CAPITAL = [
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",  "target_level": 5},
    {"location": "dorf2.php", "gid": "16", "name": "Rally Point",    "target_level": 1},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 3},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 3},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 3},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 3},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 5},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 5},
    {"location": "dorf2.php", "gid": "17", "name": "Marketplace",    "target_level": 3},
    {"location": "dorf2.php", "gid": "18", "name": "Embassy",        "target_level": 1},
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",         "target_level": 5},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 5},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 5},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 5},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 5},
    {"location": "dorf2.php", "gid": "22", "name": "Academy",        "target_level": 5},
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",       "target_level": 5},
    {"location": "dorf2.php", "gid": "20", "name": "Stable",         "target_level": 3},
    {"location": "dorf2.php", "gid": "13", "name": "Smithy",         "target_level": 3},
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",  "target_level": 10},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 10},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 10},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 7},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 7},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 7},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 7},
    {"location": "dorf2.php", "gid": "24", "name": "Town Hall",      "target_level": 5},
    {"location": "dorf2.php", "gid": "22", "name": "Academy",        "target_level": 10},
    {"location": "dorf2.php", "gid": "26", "name": "Palace",         "target_level": 5},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 15},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 15},
    {"location": "dorf2.php", "gid": "24", "name": "Town Hall",      "target_level": 10},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 10},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 10},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 10},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 10},
    {"location": "dorf2.php", "gid": "26", "name": "Palace",         "target_level": 10},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 18},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 18},
]

# ------------------------------------------------------------------
# ОФФНИК — деревня для производства атакующих войск.
# Цель: быстрые казармы / конюшня / мастерская + экономика под тренировку.
# ------------------------------------------------------------------
PLAN_OFFENSE = [
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",  "target_level": 5},
    {"location": "dorf2.php", "gid": "16", "name": "Rally Point",    "target_level": 1},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 5},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 5},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 5},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 5},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 8},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 8},
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",       "target_level": 10},
    {"location": "dorf2.php", "gid": "20", "name": "Stable",         "target_level": 10},
    {"location": "dorf2.php", "gid": "22", "name": "Academy",        "target_level": 10},
    {"location": "dorf2.php", "gid": "13", "name": "Smithy",         "target_level": 10},
    {"location": "dorf2.php", "gid": "21", "name": "Workshop",       "target_level": 5},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 12},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 12},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 8},
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",       "target_level": 15},
    {"location": "dorf2.php", "gid": "20", "name": "Stable",         "target_level": 15},
    {"location": "dorf2.php", "gid": "13", "name": "Smithy",         "target_level": 15},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 18},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 18},
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",       "target_level": 20},
    {"location": "dorf2.php", "gid": "20", "name": "Stable",         "target_level": 20},
]

# ------------------------------------------------------------------
# ДЕФЕР — деревня для производства защитников.
# Цель: казармы / конюшня для деф-юнитов + стена, склады под сток ресов.
# ------------------------------------------------------------------
PLAN_DEFENSE = [
    {"location": "dorf2.php", "gid": "15", "name": "Main Building",  "target_level": 5},
    {"location": "dorf2.php", "gid": "16", "name": "Rally Point",    "target_level": 1},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 5},
    {"location": "dorf1.php", "gid": "1",  "name": "Woodcutters",    "target_level": 5},
    {"location": "dorf1.php", "gid": "2",  "name": "Clay Pits",      "target_level": 5},
    {"location": "dorf1.php", "gid": "3",  "name": "Iron Mines",     "target_level": 5},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 8},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 8},
    {"location": "dorf2.php", "gid": "33", "name": "City Wall",      "target_level": 10},
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",       "target_level": 10},
    {"location": "dorf2.php", "gid": "20", "name": "Stable",         "target_level": 10},
    {"location": "dorf2.php", "gid": "22", "name": "Academy",        "target_level": 10},
    {"location": "dorf2.php", "gid": "13", "name": "Smithy",         "target_level": 10},
    {"location": "dorf2.php", "gid": "23", "name": "Cranny",         "target_level": 7},
    {"location": "dorf2.php", "gid": "33", "name": "City Wall",      "target_level": 15},
    {"location": "dorf1.php", "gid": "4",  "name": "Croplands",      "target_level": 8},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 12},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 12},
    {"location": "dorf2.php", "gid": "19", "name": "Barracks",       "target_level": 15},
    {"location": "dorf2.php", "gid": "20", "name": "Stable",         "target_level": 15},
    {"location": "dorf2.php", "gid": "33", "name": "City Wall",      "target_level": 20},
    {"location": "dorf2.php", "gid": "10", "name": "Warehouse",      "target_level": 18},
    {"location": "dorf2.php", "gid": "11", "name": "Granary",        "target_level": 18},
]

# ------------------------------------------------------------------
# Реестр шаблонов — используется GUI и бэкендом.
# ключ → (название для UI, описание, список шагов)
# ------------------------------------------------------------------
TEMPLATES = {
    "x1":        ("Стандарт x1",      "Экономика, поля 5+5, Резиденция. Для обычных серверов.",                    None),
    "x3":        ("Non-raid x3/x5",   "Гайд Tikiii971: герой в ресурсы, поля до 3, Ратуша+вечеринка → 2я деревня.", None),
    "gauls_x1":  ("Галлы x1 (Caim)",  "3 Party Farming: Ратуша, Гром, Резиденция 10, поселенцы. Точно по гайду.", PLAN_GAULS_X1),
    "farmer":    ("Фармер",           "Упор на поля и склады. Минимум зданий. Для фарм-деревни.",                  PLAN_FARMER),
    "capital":   ("Столица",          "Дворец, Ратуша, полная экономика, поля 10+10.",                             PLAN_CAPITAL),
    "offense":   ("Оффник",           "Казармы / конюшня 20 ур. Максимум атакующих войск.",                        PLAN_OFFENSE),
    "defense":   ("Дефер",            "Казармы / конюшня + стена 20 ур. Максимум защиты.",                         PLAN_DEFENSE),
    "none":      ("Без плана",        "Не строить ничего в этой деревне.",                                         []),
}


def get_template_plan(template_id: str, fallback_x1=None, fallback_x3=None) -> list:
    """
    Возвращает список шагов для шаблона.
    x1/x3 используют легаси-планы из config.py (передаются как fallback).
    """
    if template_id not in TEMPLATES:
        return fallback_x3 or fallback_x1 or []
    _, _, steps = TEMPLATES[template_id]
    if steps is None:
        # x1 / x3 — возвращаем легаси-план
        if template_id == "x1":
            return fallback_x1 or []
        return fallback_x3 or []
    return steps
