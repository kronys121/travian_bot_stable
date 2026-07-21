import logging
import threading
import requests


TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_PHOTO_API = "https://api.telegram.org/bot{token}/sendPhoto"


class Notifier:
    """
    Отправляет уведомления в Telegram.

    Не использует asyncio/python-telegram-bot —
    работает напрямую через requests.post(),
    что безопасно из любого потока и event loop.

    Установка:
        pip install requests

    Использование:
        notifier = Notifier(token="...", chat_id="...", account_name="acc1")
        notifier.send("Обнаружена атака!")
    """

    def __init__(self, token: str, chat_id: str, account_name: str = "bot"):
        self.token        = token
        self.chat_id      = str(chat_id)
        self.account_name = account_name
        self._url         = TELEGRAM_API.format(token=token)
        self._lock        = threading.Lock()

    def _prefix(self) -> str:
        return f"[{self.account_name}]"

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Отправляет произвольное сообщение через requests.post()."""
        full_msg = f"{self._prefix()} {message}"
        payload  = {
            "chat_id":    self.chat_id,
            "text":       full_msg,
            "parse_mode": parse_mode,
        }
        try:
            with self._lock:
                resp = requests.post(self._url, json=payload, timeout=10)
            if resp.ok:
                logging.info("📨 Telegram отправлено.")
                return True
            else:
                logging.error(f"❌ Ошибка Telegram {resp.status_code}: {resp.text}")
                return False
        except requests.RequestException as e:
            logging.error(f"❌ Сеть Telegram: {e}")
            return False
        except Exception as e:
            logging.error(f"❌ Неожиданная ошибка Notifier: {e}")
            return False

    # ========== УДОБНЫЕ МЕТОДЫ ==========

    def photo(self, path: str, caption: str = "") -> bool:
        """Отправляет картинку (например скриншот CAPTCHA) через sendPhoto."""
        url = TELEGRAM_PHOTO_API.format(token=self.token)
        cap = f"{self._prefix()} {caption}".strip()
        try:
            with self._lock, open(path, "rb") as f:
                resp = requests.post(
                    url,
                    data={"chat_id": self.chat_id, "caption": cap, "parse_mode": "HTML"},
                    files={"photo": f}, timeout=20,
                )
            if resp.ok:
                logging.info("📨 Telegram фото отправлено.")
                return True
            logging.error(f"❌ Ошибка Telegram photo {resp.status_code}: {resp.text}")
            return False
        except Exception as e:
            logging.error(f"❌ Notifier.photo: {e}")
            return False

    def attack(self, coords: tuple, arrival: str, troops_count: str = "?"):
        """Уведомление о входящей атаке."""
        self.send(
            f"🚨 <b>АТАКА!</b>\n"
            f"📍 Откуда: ({coords[0]}|{coords[1]})\n"
            f"⏰ Прибытие: {arrival}\n"
            f"⚔️ Войск: {troops_count}"
        )

    def building_done(self, building_name: str, level: int):
        """Уведомление о завершении строительства."""
        self.send(f"✅ <b>{building_name}</b> → ур.{level} готово")

    def captcha(self, screenshot_path: str = None):
        """Уведомление о CAPTCHA (со скриншотом, если он передан)."""
        msg = "💤 Обнаружена <b>CAPTCHA</b>! Требуется ручной вход."
        if screenshot_path and self.photo(screenshot_path, msg):
            return
        self.send(msg)

    def hero_died(self):
        """Герой погиб."""
        self.send("💀 <b>Герой погиб!</b> Проверь возрождение и шмот.")

    def crop_starving(self, village: str, prod: int):
        """Отрицательное производство зерна — риск голода."""
        self.send(
            f"🌾 <b>Голод по зерну</b> в «{village}»: производство {prod}/ч. "
            f"Войска/жители могут начать умирать."
        )

    def storage_full(self, village: str, resource: str):
        """Склад/амбар переполнен — ресурсы теряются."""
        self.send(
            f"📦 <b>Переполнение</b> в «{village}»: {resource}. "
            f"Ресурсы уходят впустую — включи NPC-обмен или переброску."
        )

    def cropper_found(self, coords: tuple, crop_type: int, distance: float):
        """Уведомление о найденной пятнашке/девятке."""
        icon = "🌟" if crop_type == 15 else "✨"
        self.send(
            f"{icon} <b>Найдена долина {crop_type}-кроп!</b>\n"
            f"📍 ({coords[0]}|{coords[1]}) [Дист: {distance}]"
        )

    def no_troops(self, village_id: str):
        """Уведомление о закончании войск."""
        self.send(f"⚠️ Фарм остановлен: нет войск в <code>{village_id}</code>")

    def error(self, context: str, err: Exception):
        """Уведомление об ошибке."""
        self.send(f"🔴 <b>Ошибка</b> [{context}]: <code>{err}</code>")


class NullNotifier:
    """
    Заглушка — используется, если токен Telegram не задан.
    Все вызовы игнорируются без ошибок.
    """
    def send(self, *a, **kw): pass
    def photo(self, *a, **kw): pass
    def attack(self, *a, **kw): pass
    def building_done(self, *a, **kw): pass
    def captcha(self, *a, **kw): pass
    def hero_died(self, *a, **kw): pass
    def crop_starving(self, *a, **kw): pass
    def storage_full(self, *a, **kw): pass
    def cropper_found(self, *a, **kw): pass
    def no_troops(self, *a, **kw): pass
    def error(self, *a, **kw): pass


def create_notifier(config) -> "Notifier | NullNotifier":
    """
    Фабрика для создания Notifier или NullNotifier.
    Вызывается в TravianBot.__init__.
    """
    token   = getattr(config, 'telegram_token',   None)
    chat_id = getattr(config, 'telegram_chat_id', None)
    name    = getattr(config, 'name', 'bot')
    if token and chat_id:
        logging.info(f"📨 Telegram уведомления активны (акк: {name}).")
        return Notifier(token=token, chat_id=chat_id, account_name=name)
    logging.info("🔕 Telegram не настроен — использую NullNotifier.")
    return NullNotifier()