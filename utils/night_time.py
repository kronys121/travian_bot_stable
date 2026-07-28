"""
Единый модуль работы с ночным окном (sleep_hours).

Формат sleep_hours: (start_hour, end_hour), например (23, 7) —
спать с 23:00 до 07:00 (поддерживается переход через полночь).
"""
from datetime import datetime, timedelta


def _normalize(sleep_hours) -> tuple[int, int] | None:
    """(start, end) в диапазоне 0..23 или None, если окно не задано/битое.

    ФИКС: раньше нормализация `% 24` была только в is_night(). В
    seconds_until_morning час брался как есть, поэтому вполне обычный
    конфиг с end=24 («спать до полуночи») ронял вызов
    datetime.replace(hour=24) -> ValueError прямо внутри job_build /
    job_village_round.
    """
    if not sleep_hours or len(sleep_hours) < 2:
        return None
    try:
        start = int(sleep_hours[0]) % 24
        end = int(sleep_hours[1]) % 24
    except (TypeError, ValueError):
        return None
    return start, end


def is_night(sleep_hours, now: datetime | None = None) -> bool:
    """True если текущий час попадает в ночное окно."""
    window = _normalize(sleep_hours)
    if window is None:
        return False
    start, end = window
    now = now or datetime.now()
    hour = now.hour
    if start == end:
        # Пустое окно, а не круглосуточная ночь. Раньше такой конфиг
        # проваливался в ветку «через полночь» и давала True всегда —
        # бот засыпал навсегда.
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # переход через полночь


def seconds_until_morning(sleep_hours, now: datetime | None = None,
                          default: int = 30 * 60) -> int:
    """
    Секунды до конца ночного окна (sleep_hours[1]:00).
    Если окно не задано или задано некорректно — возвращает default (30 минут).
    """
    window = _normalize(sleep_hours)
    if window is None:
        return default
    _, end_hour = window
    now = now or datetime.now()
    morning = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if morning <= now:
        morning += timedelta(days=1)
    return max(60, int((morning - now).total_seconds()))
