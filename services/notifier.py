import html
import logging
import os
import threading
import requests


TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_PHOTO_API = "https://api.telegram.org/bot{token}/sendPhoto"


def esc(value) -> str:
    """
    Экранирует значение перед подстановкой в HTML-разметку Telegram.

    Имена деревень и тексты исключений содержат & и <...> (например
    'build.php?id=39&gid=16'). Без экранирования Telegram отвечает 400
    и уведомление теряется молча.
    """
    return html.escape(str(value), quote=False)


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

    Все методы возвращают bool: True = сообщение ушло. utils/alerts.py
    опирается на это, чтобы не пометить непосланный алерт как отправленный.
    """

    def __init__(self, token: str, chat_id: str, account_name: str = "bot"):
        self.token        = token
        self.chat_id      = str(chat_id)
        self.account_name = account_name
        self._url         = TELEGRAM_API.format(token=token)
        self._lock        = threading.Lock()

    def _prefix(self) -> str:
        return f"[{self.account_name}]"

    def _scrub(self, text) -> str:
        """
        Вырезает токен бота из текста.

        urllib3 кладёт в сообщение об ошибке полный URL запроса, то есть
        .../bot<ТОКЕН>/sendMessage. Лог аккаунта дашборд отдаёт по HTTP,
        так что токен утекал бы наружу.
        """
        s = str(text)
        return s.replace(self.token, "***") if self.token else s

    def _post(self, text: str, parse_mode: str | None):
        """Один POST в sendMessage. Возвращает (ok, http_status|None)."""
        payload = {"chat_id": self.chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            with self._lock:
                resp = requests.post(self._url, json=payload, timeout=10)
        except requests.RequestException as e:
            logging.error(f"❌ Сеть Telegram: {type(e).__name__}: {self._scrub(e)}")
            return False, None
        except Exception as e:
            logging.error(f"❌ Неожиданная ошибка Notifier: {self._scrub(e)}")
            return False, None
        if resp.ok:
            logging.info("📨 Telegram отправлено.")
            return True, resp.status_code
        logging.error(f"❌ Ошибка Telegram {resp.status_code}: {self._scrub(resp.text)}")
        return False, resp.status_code

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Отправляет произвольное сообщение через requests.post()."""
        full_msg = f"{self._prefix()} {message}"
        ok, status = self._post(full_msg, parse_mode)
        if not ok and status == 400 and parse_mode:
            # 400 = Telegram не разобрал разметку. Повторяем обычным текстом,
            # иначе важный алерт (капча, гибель героя) пропадает совсем.
            logging.warning("↩️ Telegram 400 — повтор без parse_mode.")
            ok, _ = self._post(full_msg, None)
        return ok

    # ========== УДОБНЫЕ МЕТОДЫ ==========

    def photo(self, path: str, caption: str = "") -> bool:
        """Отправляет картинку (например скриншот CAPTCHA) через sendPhoto."""
        url = TELEGRAM_PHOTO_API.format(token=self.token)
        cap = f"{self._prefix()} {caption}".strip()
        try:
            with open(path, "rb") as f:
                blob = f.read()
        except Exception as e:
            # Уведомление не должно ронять бота даже при кривом пути (None и т.п.)
            logging.error(f"❌ Notifier.photo: не читается {path}: {e}")
            return False

        # Раньше self._lock держался ВСЮ загрузку (timeout=20): срочное
        # сообщение из потока мониторинга атак стояло в очереди эти 20 секунд.
        # requests.post потокобезопасен, блокировка здесь не нужна.
        filename = os.path.basename(str(path)) or "photo.png"
        for mode in ("HTML", None):
            data = {"chat_id": self.chat_id, "caption": cap}
            if mode:
                data["parse_mode"] = mode
            try:
                resp = requests.post(
                    url, data=data, files={"photo": (filename, blob)}, timeout=20,
                )
            except Exception as e:
                logging.error(f"❌ Notifier.photo: {type(e).__name__}: {self._scrub(e)}")
                return False
            if resp.ok:
                logging.info("📨 Telegram фото отправлено.")
                return True
            logging.error(f"❌ Ошибка Telegram photo {resp.status_code}: {self._scrub(resp.text)}")
            if resp.status_code != 400:
                return False
            logging.warning("↩️ Telegram 400 — повтор фото без parse_mode.")
        return False

    def attack(self, coords: tuple, arrival: str, troops_count: str = "?") -> bool:
        """Уведомление о входящей атаке."""
        return self.send(
            f"🚨 <b>АТАКА!</b>\n"
            f"📍 Откуда: ({esc(coords[0])}|{esc(coords[1])})\n"
            f"⏰ Прибытие: {esc(arrival)}\n"
            f"⚔️ Войск: {esc(troops_count)}"
        )

    def building_done(self, building_name: str, level: int) -> bool:
        """Уведомление о завершении строительства."""
        return self.send(f"✅ <b>{esc(building_name)}</b> → ур.{esc(level)} готово")

    def captcha(self, screenshot_path: str = None) -> bool:
        """Уведомление о CAPTCHA (со скриншотом, если он передан)."""
        msg = "💤 Обнаружена <b>CAPTCHA</b>! Требуется ручной вход."
        if screenshot_path and self.photo(screenshot_path, msg):
            return True
        return self.send(msg)

    def hero_died(self) -> bool:
        """Герой погиб."""
        return self.send("💀 <b>Герой погиб!</b> Проверь возрождение и шмот.")

    def crop_starving(self, village: str, prod: int) -> bool:
        """Отрицательное производство зерна — риск голода."""
        return self.send(
            f"🌾 <b>Голод по зерну</b> в «{esc(village)}»: производство {esc(prod)}/ч. "
            f"Войска/жители могут начать умирать."
        )

    def storage_full(self, village: str, resource: str) -> bool:
        """Склад/амбар переполнен — ресурсы теряются."""
        return self.send(
            f"📦 <b>Переполнение</b> в «{esc(village)}»: {esc(resource)}. "
            f"Ресурсы уходят впустую — включи NPC-обмен или переброску."
        )

    def cropper_found(self, coords: tuple, crop_type: int, distance: float) -> bool:
        """Уведомление о найденной пятнашке/девятке."""
        icon = "🌟" if crop_type == 15 else "✨"
        return self.send(
            f"{icon} <b>Найдена долина {esc(crop_type)}-кроп!</b>\n"
            f"📍 ({esc(coords[0])}|{esc(coords[1])}) [Дист: {esc(distance)}]"
        )

    def no_troops(self, village_id: str) -> bool:
        """Уведомление о закончании войск."""
        return self.send(f"⚠️ Фарм остановлен: нет войск в <code>{esc(village_id)}</code>")

    def error(self, context: str, err: Exception) -> bool:
        """Уведомление об ошибке."""
        return self.send(f"🔴 <b>Ошибка</b> [{esc(context)}]: <code>{esc(self._scrub(err))}</code>")


class NullNotifier:
    """
    Заглушка — используется, если токен Telegram не задан.
    Все вызовы игнорируются без ошибок.

    Возвращает True: «уведомлять некуда» — это не сбой доставки, иначе
    utils/alerts.py будет бесконечно перепосылать один и тот же алерт.
    """
    def send(self, *a, **kw): return True
    def photo(self, *a, **kw): return True
    def attack(self, *a, **kw): return True
    def building_done(self, *a, **kw): return True
    def captcha(self, *a, **kw): return True
    def hero_died(self, *a, **kw): return True
    def crop_starving(self, *a, **kw): return True
    def storage_full(self, *a, **kw): return True
    def cropper_found(self, *a, **kw): return True
    def no_troops(self, *a, **kw): return True
    def error(self, *a, **kw): return True


def create_notifier(config) -> "Notifier | NullNotifier":
    """
    Фабрика для создания Notifier или NullNotifier.
    Вызывается в TravianBot.__init__.
    """
    # Фолбэк на .env: runner.py уже так делает, а main.py --interactive нет —
    # из-за этого в ручном режиме уведомления всегда были выключены.
    token   = getattr(config, 'telegram_token',   None) or os.getenv('TELEGRAM_TOKEN')
    chat_id = getattr(config, 'telegram_chat_id', None) or os.getenv('TELEGRAM_CHAT_ID')
    name    = getattr(config, 'name', 'bot')
    if token and chat_id:
        logging.info(f"📨 Telegram уведомления активны (акк: {name}).")
        return Notifier(token=token, chat_id=chat_id, account_name=name)
    logging.info("🔕 Telegram не настроен — использую NullNotifier.")
    return NullNotifier()
