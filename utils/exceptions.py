class TravianBotError(Exception):
    """Базовое исключение бота."""
    pass


class CaptchaDetectedError(TravianBotError):
    """Обнаружена CAPTCHA. Бот должен остановиться и уведомить."""
    pass


class NoBuildingsError(TravianBotError):
    """Не найдено здание для постройки. Вернуться в цикл."""
    pass


class NoTroopsError(TravianBotError):
    """Войска закончились. Остановить фарм для этой деревни."""
    pass


class LoginError(TravianBotError):
    """Ошибка авторизации."""
    pass


class ServerUnavailableError(TravianBotError):
    """Сервер недоступен. Повторить позже."""
    pass