"""
Расчёты для умного фарма оазисов: безопасность пачки, приоритет целей,
размер пачки.

Здесь НЕТ ни браузера, ни сети, ни файлов — только арифметика над уже
собранными данными. Поэтому логику можно проверить без игры и без аккаунта.

Главные идеи
---------------
1. Безопасность — это СРАВНЕНИЕ СИЛ, а не абсолютный порог.
   Пачка из 5 легионеров и пачка из 200 — это разные возможности,
   а старый max_animal_defense был один на любой случай.
   Формула та же, что уже работает для героя в FarmManager.run_hero_farm:
       атака * 100 >= защита * safety_pct
2. Животные защищаются от конницы ДРУГИМ числом (def_cav), чем от пехоты.
   Старый код всегда брал max(def_inf, def_cav) — перестраховка,
   из-за неё терялись вполне фармибельные цели.
3. Приоритет цели — не дистанция, а ЛУТ ЗА МИНУТУ ЗАНЯТОСТИ ВОЙСК.
   Данные для этого уже копились в farm_stats.json (секция "oases"),
   но фарм-цикл их никогда не читал.
4. Размер пачки — под ожидаемую добычу. Лишние юниты в пути —
   это юниты, которые не фармят другую цель.
"""
import math
import time
from datetime import datetime

from config import unit_stats as US

# Запас прочности по умолчанию: атака вдвое выше защиты животных.
# Меньше 150% ставить не стоит: бой считается не линейно, и даже
# при победе потери будут ощутимыми.
DEFAULT_SAFETY_PCT = 200
MIN_SAFETY_PCT = 120

# Сколько набегов по цели считаем "разведкой": пока их меньше,
# статистике не доверяем и цель не выкидываем за бедность.
EXPLORE_RAIDS = 3


def oasis_key(x, y) -> str:
    """Ключ цели в farm_stats — тот же формат, что в FarmStats.record_raid."""
    return f"{x}|{y}"


# --- БЕЗОПАСНОСТЬ -------------------------------------------------

def animal_defense(animals: dict, animal_stats: dict, vs_cavalry: bool = False) -> int:
    """Защита животных против НАШЕГО типа войск.

    animals      — {"u37": 2, ...} из скана;
    animal_stats — таблица FarmManager.ANIMAL_STATS (передаётся снаружи,
                   чтобы не держать вторую копию тех же цифр);
    vs_cavalry   — мы шлём конницу.
    """
    total = 0
    for code, count in (animals or {}).items():
        st = animal_stats.get(code)
        if not st:
            continue
        per = st['def_cav'] if vs_cavalry else st['def_inf']
        try:
            total += int(per) * int(count)
        except (TypeError, ValueError):
            continue
    return total


def safety_pct(value=None) -> int:
    """Нормализует запас прочности из настроек."""
    try:
        pct = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SAFETY_PCT
    return max(MIN_SAFETY_PCT, pct)


def safe_defense_limit(tribe, troop_index: int, count: int, pct=None) -> int:
    """Максимальная защита животных, при которой пачка ещё безопасна.

    Годится как max_defense для FarmManager.attack_oasis(allow_occupied=True):
    там такая же проверка делается по СВЕЖИМ животным перед отправкой.

    0 = таблица атаки неизвестна — значит решать нельзя, только пустые оазисы.
    """
    attack = US.attack_of(tribe, troop_index, count)
    if attack <= 0:
        return 0
    return int(attack * 100 // safety_pct(pct))


def can_beat(tribe, troop_index: int, count: int, defense: int, pct=None) -> bool:
    """Одолеет ли пачка такую защиту с запасом."""
    if defense <= 0:
        return True
    limit = safe_defense_limit(tribe, troop_index, count, pct)
    return limit > 0 and defense <= limit


def units_needed_for(tribe, troop_index: int, defense: int, pct=None) -> int:
    """Сколько юнитов надо, чтобы безопасно вынести такую защиту.

    0 = животных нет; -1 = невозможно посчитать (нет таблицы/атака 0).
    """
    if defense <= 0:
        return 0
    per_unit = US.attack_of(tribe, troop_index, 1)
    if per_unit <= 0:
        return -1
    return int(math.ceil(defense * safety_pct(pct) / (100.0 * per_unit)))


# --- ВРЕМЯ ПОЛЁТА ------------------------------------------------

def effective_speed(tribe, troop_index: int, configured_tph=0) -> float:
    """Скорость для расчётов.

    Приоритет у значения из настроек (troop_speed_tph): игрок мог вбить
    туда скорость с бонусами (сапоги, ТС, артефакты). Если там 0 —
    берём табличную скорость КОНКРЕТНОГО типа юнита, а не одну на всех.
    """
    try:
        cfg = float(configured_tph or 0)
    except (TypeError, ValueError):
        cfg = 0.0
    if cfg > 0:
        return cfg
    return float(US.speed_of(tribe, troop_index) or 0)


def round_trip_minutes(distance: float, speed_tph: float) -> float:
    """Время туда-обратно в минутах. При неизвестной скорости считаем,
    что время пропорционально дистанции (10 мин/клетка) — ранжирование
    от абсолютной точности не зависит, важен порядок.
    """
    d = max(0.0, float(distance or 0))
    if speed_tph and speed_tph > 0:
        return max(1.0, (2 * d / float(speed_tph)) * 60.0)
    return max(1.0, 2 * d * 10.0)


# --- ИСТОРИЯ ЦЕЛИ ------------------------------------------------

def history_of(stats_data: dict, x, y) -> dict:
    """Запись о цели из farm_stats.data["oases"] (пустой dict, если нет)."""
    oases = (stats_data or {}).get("oases") or {}
    entry = oases.get(oasis_key(x, y))
    return entry if isinstance(entry, dict) else {}


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def avg_loot(entry: dict):
    """Средний лут за набег или None, если отчётов ещё не было.

    Важно: loot появляется только после разбора боевых отчётов
    (FarmStats.record_report). Если сбор отчётов выключен, лута не будет
    никогда — тогда ранжирование молча откатится к дистанции.
    """
    raids = _int(entry.get("raids"))
    loot = _int(entry.get("loot"))
    if raids <= 0 or loot <= 0:
        return None
    return loot / float(raids)


def hours_since_last(entry: dict, now=None):
    """Сколько часов прошло с последнего набега (None — неизвестно)."""
    raw = entry.get("last")
    if not raw:
        return None
    try:
        last = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    ref = now or datetime.now()
    return max(0.0, (ref - last).total_seconds() / 3600.0)


def expected_loot(entry: dict, ref_hours: float = 1.0, now=None):
    """Ожидаемая добыча с цели СЕЙЧАС или None.

    Модель простая и нарочно консервативная: оазис накапливает
    ресурсы примерно линейно. Средний лут (avg) был получен при
    типичном интервале визитов ref_hours; если с прошлого раза
    прошло больше — накопилось больше, меньше — меньше.
    Множитель зажат в [0.25, 1.5]: без знания капа оазиса считать,
    что за сутки там накопилось в 24 раза больше — самообман.
    """
    avg = avg_loot(entry)
    if avg is None:
        return None
    hours = hours_since_last(entry, now=now)
    ref = max(0.25, float(ref_hours or 1.0))
    if hours is None:
        return avg
    growth = hours / ref
    growth = min(1.5, max(0.25, growth))
    return avg * growth


# --- РАНЖИРОВАНИЕ -----------------------------------------------

def rank_targets(targets, stats_data: dict, *, speed_tph: float = 0.0,
                 ref_hours: float = 1.0, min_loot: int = 0,
                 explore_raids: int = EXPLORE_RAIDS, now=None):
    """Сортирует цели по прибыльности и отбрасывает бесполезные.

    Возвращает (ranked, dropped). Каждая цель — КОПИЯ исходного dict
    с добавленными полями: exp_loot, score, raids, lost, rt_min.

    Оценка = ожидаемый лут / минуты занятости войск. Цели без истории
    получают медианный ожидаемый лут известных — так они не вытесняют
    доказанно жирные, но и не тонут в конце списка навсегда.
    """
    prepared = []
    known = []
    for t in targets or []:
        entry = history_of(stats_data, t.get("x"), t.get("y"))
        exp = expected_loot(entry, ref_hours=ref_hours, now=now)
        item = dict(t)
        item["raids"] = _int(entry.get("raids"))
        item["lost"] = _int(entry.get("lost"))
        item["exp_loot"] = exp
        item["rt_min"] = round_trip_minutes(t.get("distance", 0), speed_tph)
        prepared.append(item)
        if exp is not None:
            known.append(exp)

    # Приор для неизвестных целей — медиана по известным.
    if known:
        known.sort()
        prior = known[len(known) // 2]
    else:
        prior = None

    ranked, dropped = [], []
    for item in prepared:
        exp = item["exp_loot"]
        # Цели, которые уже достаточно проверены и стабильно бедные.
        if min_loot > 0 and item["raids"] >= explore_raids:
            if exp is not None and exp < min_loot:
                item["drop_reason"] = f"лут ~{int(exp)} < {min_loot}"
                dropped.append(item)
                continue
        basis = exp if exp is not None else prior
        if basis is None:
            # Статистики нет вообще (первый запуск / отчёты выключены):
            # откат к старому поведению — ближе значит раньше.
            item["score"] = 1000.0 / item["rt_min"]
            item["score_src"] = "distance"
        else:
            item["score"] = basis / item["rt_min"]
            item["score_src"] = "history" if exp is not None else "prior"
        ranked.append(item)

    ranked.sort(key=lambda i: (-i["score"], i.get("distance", 999)))
    return ranked, dropped


def recommended_count(exp_loot, carry: int, *, default_count: int,
                      min_count: int = 1, max_count: int = 0,
                      need_units: int = 0) -> int:
    """Сколько юнитов слать на цель.

    exp_loot   — ожидаемая добыча (None — нет данных);
    carry      — носимость одного юнита (0 — неизвестно);
    need_units — минимум по боевой необходимости (животные в оазисе).

    Без данных возвращает default_count — то есть старое поведение.
    """
    ceiling = int(max_count or default_count)
    if exp_loot is None or carry <= 0:
        want = int(default_count)
    else:
        want = int(math.ceil(float(exp_loot) / float(carry)))
    want = max(want, int(min_count), int(max(0, need_units)))
    return max(1, min(want, max(1, ceiling)))


# --- ЭВАКУАЦИЯ ---------------------------------------------------

def evade_candidates(farm_list, occupied=None, limit: int = 5):
    """Кандидаты для эвакуации войск, от лучшего к худшему.

    Сначала ближайшие ПУСТЫЕ оазисы, потом — занятые с САМОЙ СЛАБОЙ
    защитой (на случай, если все пустые окажутся заняты при проверке).
    Оазисы с войсками игрока исключаются всегда.

    Вызывающая сторона ОБЯЗАНА проверить клетку перед отправкой:
    списки — слепок на момент скана, а в эвакуацию уходит вся армия.
    """
    out = []
    for o in sorted(farm_list or [], key=lambda i: i.get("distance", 999)):
        out.append({"x": o.get("x"), "y": o.get("y"),
                    "distance": o.get("distance", 0), "kind": "empty"})
    weak = [
        o for o in (occupied or [])
        if not o.get("has_player_troops") and _int(o.get("def_inf")) > 0
    ]
    weak.sort(key=lambda i: (_int(i.get("def_inf")), i.get("distance", 999)))
    for o in weak:
        out.append({"x": o.get("x"), "y": o.get("y"),
                    "distance": o.get("distance", 0), "kind": "weak",
                    "def_inf": _int(o.get("def_inf"))})
    return out[:max(1, int(limit))]


def stats_summary(stats_data: dict) -> dict:
    """Короткая сводка для лога: есть ли вообще данные по луту."""
    oases = (stats_data or {}).get("oases") or {}
    with_loot = sum(1 for e in oases.values()
                    if isinstance(e, dict) and _int(e.get("loot")) > 0)
    return {"targets": len(oases), "with_loot": with_loot,
            "reports": _int(((stats_data or {}).get("totals") or {}).get("reports"))}
