"""
Табличные характеристики юнитов (Travian T4).

Зачем нужны:
  * attack — сравнить силу пачки с защитой животных в оазисе и не слить войска;
  * carry  — понять, сколько юнитов реально нужно, чтобы унести добычу
                 (лишние юниты в пути — это нефармящиеся юниты);
  * speed  — посчитать время полёта туда-обратно для кулдауна цели;
  * cav    — конница ли. Важно: животные защищаются ОТ КОННИЦЫ другим
                 числом (def_cav), чем от пехоты (def_inf). Медведь против
                 пехоты — 140, против конницы — 200.

Индекс юнита = его позиция в точке сбора (t1..t10) — та же нумерация,
что в настройках бота (troop_type_index / farm_troop_indices).

Цифры — классический T4 без бонусов. Скорость НЕ учитывает сапоги героя,
ТС и артефакты. Если сервер отличается (спид, модификации) — правьте
ЗДЕСЬ: это единственное место, откуда фарм берёт цифры.
"""
from typing import NamedTuple, Optional


class UnitStat(NamedTuple):
    name: str
    attack: int
    carry: int
    speed: int   # клеток в час
    cav: bool


# Ключи — канонические имена племён (см. normalize_tribe).
TRIBES: dict[str, dict[int, UnitStat]] = {
    "romans": {
        1:  UnitStat("Легионер",           40,   50,  6, False),
        2:  UnitStat("Преторианец",        30,   20,  5, False),
        3:  UnitStat("Императорец",        70,   50,  7, False),
        4:  UnitStat("Конный разведчик",    0,    0, 16, True),
        5:  UnitStat("Конница Императора", 120,  100, 14, True),
        6:  UnitStat("Конница Цезаря",     180,   70, 10, True),
        7:  UnitStat("Таран",               60,    0,  4, False),
        8:  UnitStat("Огненная катапульта", 75,    0,  3, False),
        9:  UnitStat("Сенатор",             50,    0,  4, False),
        10: UnitStat("Поселенец",            0, 3000,  5, False),
    },
    "teutons": {
        1:  UnitStat("Дубинщик",            40,   60,  7, False),
        2:  UnitStat("Копейщик",            10,   40,  7, False),
        3:  UnitStat("Топорщик",            60,   50,  6, False),
        4:  UnitStat("Скаут",                0,    0,  9, False),
        5:  UnitStat("Паладин",             55,  110, 10, True),
        6:  UnitStat("Тевтонский рыцарь", 150,   80,  9, True),
        7:  UnitStat("Таран",               65,    0,  4, False),
        8:  UnitStat("Катапульта",          50,    0,  3, False),
        9:  UnitStat("Предводитель",       40,    0,  4, False),
        10: UnitStat("Поселенец",           10, 3000,  5, False),
    },
    "gauls": {
        1:  UnitStat("Фаланга",             15,   35,  7, False),
        2:  UnitStat("Мечник",              65,   45,  6, False),
        3:  UnitStat("Разведчик",            0,    0, 17, True),
        4:  UnitStat("Тевтатский гром",    90,   75, 19, True),
        5:  UnitStat("Друид-всадник",       45,   35, 16, True),
        6:  UnitStat("Аэдуй",             140,   65, 13, True),
        7:  UnitStat("Таран",               50,    0,  4, False),
        8:  UnitStat("Требушет",            70,    0,  3, False),
        9:  UnitStat("Вождь",               40,    0,  5, False),
        10: UnitStat("Поселенец",            0, 3000,  5, False),
    },
    "egyptians": {
        1:  UnitStat("Ополченец",           10,   20,  7, False),
        2:  UnitStat("Страж Аша",          30,   45,  6, False),
        3:  UnitStat("Воин с хопешем",     65,   55,  7, False),
        4:  UnitStat("Следопыт Сопду",      0,    0, 16, True),
        5:  UnitStat("Страж Анхура",       50,  110, 15, True),
        6:  UnitStat("Колесница Решефа", 110,   80, 10, True),
        7:  UnitStat("Таран",               55,    0,  4, False),
        8:  UnitStat("Каменная катапульта", 65,   0,  3, False),
        9:  UnitStat("Номарх",              40,    0,  4, False),
        10: UnitStat("Поселенец",            0, 3000,  5, False),
    },
    "huns": {
        1:  UnitStat("Наёмник",             35,   50,  6, False),
        2:  UnitStat("Лучник",              50,   30,  6, False),
        3:  UnitStat("Разведчик",            0,    0, 19, True),
        4:  UnitStat("Степной всадник",   120,   40, 16, True),
        5:  UnitStat("Стрелок",            115,   50, 12, True),
        6:  UnitStat("Мараудёр",           180,   70, 14, True),
        7:  UnitStat("Таран",               60,    0,  4, False),
        8:  UnitStat("Катапульта",          75,    0,  3, False),
        9:  UnitStat("Логад",               50,    0,  4, False),
        10: UnitStat("Поселенец",            0, 3000,  5, False),
    },
    "spartans": {
        1:  UnitStat("Гоплит",              40,   45,  7, False),
        2:  UnitStat("Стражник",            10,   20,  9, False),
        3:  UnitStat("Щитоносец",           35,   50,  6, False),
        4:  UnitStat("Двустальный терион", 90,  55,  7, False),
        5:  UnitStat("Всадник Эльпиды",    55,  110, 16, True),
        6:  UnitStat("Коринфский крушитель", 195, 80,  9, True),
        7:  UnitStat("Таран",               65,    0,  4, False),
        8:  UnitStat("Баллиста",            50,    0,  3, False),
        9:  UnitStat("Эфор",                40,    0,  4, False),
        10: UnitStat("Поселенец",            0, 3000,  5, False),
    },
}

# Герой — отдельный случай: атака берётся со страницы атрибутов
# (FarmManager.get_hero_power), носимость и скорость зависят от предметов.
# Скорость 7 — пеший герой; на лошади — 14.
HERO_INDEX = 11
HERO = UnitStat("Герой", 0, 0, 7, False)

# Синонимы названий племён: в настройках и конфигах они встречаются
# по-разному: по-английски, по-русски, в единственном числе, цифрой.
_ALIASES = {
    "1": "romans", "roman": "romans", "romans": "romans",
    "рим": "romans", "римляне": "romans", "римлянин": "romans",
    "2": "teutons", "teuton": "teutons", "teutons": "teutons", "german": "teutons",
    "германцы": "teutons", "германец": "teutons", "тевтоны": "teutons",
    "3": "gauls", "gaul": "gauls", "gauls": "gauls",
    "галлы": "gauls", "галл": "gauls",
    "6": "egyptians", "egyptian": "egyptians", "egyptians": "egyptians",
    "египтяне": "egyptians", "египет": "egyptians",
    "7": "huns", "hun": "huns", "huns": "huns",
    "гунны": "huns", "гунн": "huns",
    "8": "spartans", "spartan": "spartans", "spartans": "spartans",
    "спартанцы": "spartans", "спарта": "spartans",
}

DEFAULT_TRIBE = "romans"


def normalize_tribe(value) -> str:
    """Любое написание племени — в канонический ключ TRIBES.

    Неизвестное значение даёт DEFAULT_TRIBE, а не исключение: ошибка в
    настройках не должна ронять фарм-цикл.
    """
    key = str(value or "").strip().lower()
    if key in TRIBES:
        return key
    return _ALIASES.get(key, DEFAULT_TRIBE)


def unit(tribe, index: int) -> Optional[UnitStat]:
    """Характеристики юнита или None, если индекс неизвестен."""
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None
    if idx == HERO_INDEX:
        return HERO
    return TRIBES.get(normalize_tribe(tribe), {}).get(idx)


def attack_of(tribe, index: int, count: int) -> int:
    """Суммарная атака пачки. 0 = таблицы нет, решать нельзя."""
    st = unit(tribe, index)
    if not st:
        return 0
    return int(st.attack) * max(0, int(count))


def carry_of(tribe, index: int) -> int:
    """Носимость одного юнита. 0 = неизвестно."""
    st = unit(tribe, index)
    return int(st.carry) if st else 0


def speed_of(tribe, index: int) -> int:
    """Скорость юнита (клеток/час) без бонусов. 0 = неизвестно."""
    st = unit(tribe, index)
    return int(st.speed) if st else 0


def is_cavalry(tribe, index: int) -> bool:
    st = unit(tribe, index)
    return bool(st.cav) if st else False


def name_of(tribe, index: int) -> str:
    st = unit(tribe, index)
    return st.name if st else f"t{index}"
