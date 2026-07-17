import time
import logging
import functools


def retry(max_attempts: int = 3, delay: float = 5.0, exceptions: tuple = (Exception,)):
    """
    Декоратор для автоматического повтора функции при ошибке.

    Args:
        max_attempts: Максимальное количество попыток.
        delay: Базовая задержка между попытками (умножается на номер попытки).
        exceptions: Tuple исключений, которые нужно перехватывать.

    Example:
        @retry(max_attempts=3, delay=5)
        def my_func():
            ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    wait = delay * attempt
                    logging.warning(
                        f"⚠️ [{func.__name__}] Попытка {attempt}/{max_attempts} провалилась: {e}. "
                        f"Жду {wait:.1f} сек..."
                    )
                    if attempt < max_attempts:
                        time.sleep(wait)
            logging.error(f"❌ [{func.__name__}] Все {max_attempts} попытки провалились.")
            return None

        return wrapper

    return decorator