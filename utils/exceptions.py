class TravianBotError(Exception):
    """Базовое исключение бота."""
    pass


class CaptchaDetectedError(TravianBotError):
    """Обнаружена CAPTCHA. Бот должен остановиться и уведомить."""
    pass

# NoBuildingsError / NoTroopsError / LoginError / ServerUnavailableError удалены:
# их никто не бросал и не ловил — код обходился обычными Exception и кодами
# возврата, а «объявленные» исключения только создавали иллюзию контракта.
