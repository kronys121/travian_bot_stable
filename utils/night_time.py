"""
Единый модуль работы с ночным окном (sleep_hours).

Формат sleep_hours: (start_hour, end_hour), например (23, 7) —
спать с 23:00 до 07:00 (поддерживается переход через полночь).
"""
from datetime import datetime, timedelta


def is_night(sleep_hours, now: datetime | None = None) -> bool:
    """True если текущий час попадает в ночное окно."""
    if not sleep_hours or len(sleep_hours) < 2:
        return False
    now = now or datetime.now()
    hour = now.hour
    start, end = int(sleep_hours[0]), int(sleep_hours[1])
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # переход через полночь


def seconds_until_morning(sleep_hours, now: datetime | None = None,
                          default: int = 30 * 60) -> int:
    """
    Секунды до конца ночного окна (sleep_hours[1]:00).
    Если окно не задано — возвращает default (30 минут).
    """
    if not sleep_hours or len(sleep_hours) < 2:
        return default
    now = now or datetime.now()
    end_hour = int(sleep_hours[1])
    morning = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if morning <= now:
        morning += timedelta(days=1)
    return max(60, int((morning - now).total_seconds()))
