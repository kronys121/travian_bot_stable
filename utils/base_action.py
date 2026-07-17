import time
import random
import logging
from datetime import datetime
from playwright.sync_api import Page, Locator

# pip install fake-useragent
try:
    from fake_useragent import UserAgent

    _ua = UserAgent(browsers=['chrome', 'firefox', 'edge'])
except ImportError:
    _ua = None

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


def get_random_user_agent() -> str:
    """Возвращает случайный User-Agent."""
    if _ua:
        try:
            return _ua.random
        except Exception:
            logging.debug("suppressed error in utils/base_action:29", exc_info=True)
    return random.choice(USER_AGENTS)


def get_random_viewport() -> dict:
    """
    Возвращает случайный размер окна браузера.
    Имитирует реальные разрешения мониторов.
    """
    resolutions = [
        {'width': 1280, 'height': 720},
        {'width': 1366, 'height': 768},
        {'width': 1440, 'height': 900},
        {'width': 1536, 'height': 864},
        {'width': 1600, 'height': 900},
        {'width': 1920, 'height': 1080},
    ]
    return random.choice(resolutions)


class BaseAction:
    """
    Базовый класс для всех действий бота.
    Содержит общие методы для имитации поведения человека.

    УЛУЧШЕНИЯ:
    - Паузы на основе нормального распределения (human_pause)
    - Случайное смещение курсора при hover
    - Ночной режим (is_night_time)
    - Счётчик действий в час (для антибот-лимитов)
    """

    def __init__(self, page: Page, config):
        self.page = page
        self.config = config
        self._action_count = 0
        self._action_hour_start = time.time()
        self._tea_break_counter = 0

    # ========== ПАУЗЫ ==========

    def human_pause(self, base: float = 1.5, sigma: float = 0.5) -> float:
        """
        Генерирует паузу по нормальному распределению.
        Гораздо естественнее, чем random.uniform.
        """
        return max(0.3, random.gauss(base, sigma))

    def human_sleep(self, min_sec: float = 1.0, max_sec: float = 3.0):
        """Пауза. Использует нормальное распределение вместо uniform."""
        base = (min_sec + max_sec) / 2
        sigma = (max_sec - min_sec) / 4
        delay = max(min_sec, min(max_sec, random.gauss(base, sigma)))
        time.sleep(delay)

    # ========== КЛИК ==========

    def human_click(self, locator: Locator, timeout: int = 5000, **kwargs):
        """
        Имитирует наведение мыши и клик с микро-задержкой.
        Добавлено случайное смещение курсора (±3px) для обхода антибота.
        """
        try:
            locator.wait_for(state="visible", timeout=timeout)

            # Случайное смещение курсора в пределах элемента
            box = locator.bounding_box()
            if box:
                offset_x = random.randint(-3, 3)
                offset_y = random.randint(-3, 3)
                x = box['x'] + box['width'] / 2 + offset_x
                y = box['y'] + box['height'] / 2 + offset_y
                self.page.mouse.move(x, y)
                time.sleep(self.human_pause(0.15, 0.05))
            else:
                locator.hover()

            time.sleep(self.human_pause(0.2, 0.08))
            locator.click(**kwargs)
            self.human_sleep(0.5, 1.5)
            self._register_action()
            return True
        except Exception as e:
            logging.warning(f"⚠️ Не удалось кликнуть по элементу: {e}")
            return False

    # ========== НАВИГАЦИЯ ==========

    def _dismiss_cmp(self):
        """
        Закрывает GDPR/CMP-попап consentmanager.net если он присутствует.
        Попап блокирует рендер игрового контента до нажатия «Принять».
        Ищет кнопку согласия сначала в основном фрейме, затем во всех iframe.
        """
        # Selectors for the "Accept all" / "Agree" button used by consentmanager.net
        cmp_accept_selectors = [
            "#cmpbntyestxt",           # consentmanager "Я согласен"
            ".cmpboxbtnyes",           # consentmanager green accept btn
            "a.cmptxt_btn_yes",        # alternate class
            "[aria-label*='Accept']",
            "[aria-label*='Agree']",
            "button[title*='Accept']",
            "button[title*='Agree']",
        ]
        # Try main frame first
        for sel in cmp_accept_selectors:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.click(timeout=3000)
                    logging.info("[CMP] Закрыт GDPR-попап (основной фрейм).")
                    self.human_sleep(0.8, 1.5)
                    return
            except Exception:
                logging.debug("suppressed error in utils/base_action:143", exc_info=True)
        # Try all iframes (consentmanager loads inside a cross-domain iframe)
        for frame in self.page.frames:
            if frame == self.page.main_frame:
                continue
            for sel in cmp_accept_selectors:
                try:
                    loc = frame.locator(sel)
                    if loc.count() > 0:
                        loc.first.click(timeout=3000)
                        logging.info(f"[CMP] Закрыт GDPR-попап (iframe: {frame.url[:60]}).")
                        self.human_sleep(0.8, 1.5)
                        return
                except Exception:
                    logging.debug("suppressed error in utils/base_action:157", exc_info=True)

    def safe_goto(self, url: str):
        """
        Безопасный переход по URL с рандомной паузой после загрузки.
        Автоматически закрывает CMP/GDPR-попап если он появился.
        После навигации проверяет CAPTCHA — если найдена, бросает
        CaptchaDetectedError, чтобы бот остановился, а не долбил страницу.
        """
        if self.page.url != url:
            self.page.goto(url)
            self.page.wait_for_load_state("domcontentloaded")
            self.human_sleep(1.0, 2.5)
            # Если CMP-попап присутствует — закрываем его прежде чем продолжить
            if self.page.locator("#cmpwrapper, .cmpwrapper, #cmpbox, .cmpbox").count() > 0:
                self._dismiss_cmp()
                # Даём странице время перерендериться после закрытия попапа
                try:
                    self.page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    logging.debug("suppressed error in utils/base_action:177", exc_info=True)
                self.human_sleep(1.0, 2.0)
            if self.check_captcha():
                from utils.exceptions import CaptchaDetectedError
                raise CaptchaDetectedError("CAPTCHA обнаружена после навигации.")

    # ========== АНТИБОТ ==========

    def is_night_time(self) -> bool:
        """
        Проверяет, является ли текущее время «ночным» по настройкам конфига.
        Бот не работает ночью, имитируя реального игрока.
        """
        sleep_hours = getattr(self.config, 'sleep_hours', None)
        if not sleep_hours:
            return False
        start_h, end_h = sleep_hours  # Например: (23, 7)
        current_h = datetime.now().hour
        if start_h > end_h:  # Ночь через полночь: 23 → 7
            return current_h >= start_h or current_h < end_h
        return start_h <= current_h < end_h

    def _register_action(self):
        """Считает действия в час. Делает случайные 'перерывы на чай'."""
        self._action_count += 1
        self._tea_break_counter += 1

        # Сброс счётчика каждый час
        if time.time() - self._action_hour_start > 3600:
            self._action_count = 0
            self._action_hour_start = time.time()

        # Лимит действий в час (по конфигу).
        # ВАЖНО: не спим тут долго — длинные паузы делает планировщик.
        # Короткая пауза внутри действия не блокирует другие задачи надолго.
        max_actions = getattr(self.config, 'max_actions_per_hour', 0)
        if max_actions and self._action_count >= max_actions:
            wait = random.uniform(45, 90)
            logging.info(f"🛑 Лимит {max_actions} действий/час. Короткая пауза {int(wait)}с...")
            time.sleep(wait)
            self._action_count = 0
            self._action_hour_start = time.time()

        # Случайный «перерыв на чай» раз в 30-60 действий.
        # FIX: раньше спали 5–20 минут ПРЯМО ВНУТРИ задачи — это блокировало
        # фарм/стройку/мониторинг. Теперь пауза короткая (30–90с),
        # а длинные «человеческие» промежутки создаёт планировщик между задачами.
        if self._tea_break_counter >= random.randint(30, 60):
            wait = random.uniform(30, 90)
            logging.info(f"☕ Микро-перерыв: {int(wait)} сек...")
            time.sleep(wait)
            self._tea_break_counter = 0

    def check_captcha(self) -> bool:
        """
        Проверяет наличие CAPTCHA на странице.
        Если найдена — пишет в лог и уведомляет (если есть notifier).
        """
        captcha_selectors = [
            'iframe[src*="recaptcha"]',
            '.g-recaptcha',
            '#captcha',
            'input[name="captcha"]',
            '.captcha',
        ]
        for selector in captcha_selectors:
            if self.page.locator(selector).count() > 0:
                logging.error("💤 CAPTCHA обнаружена! Бот приостановлен.")
                notifier = getattr(self.config, 'notifier', None)
                if notifier:
                    acc = getattr(self.config, 'name', 'bot')
                    notifier.send(f"[{acc}] 💤 Обнаружена CAPTCHA! Требуется ручной вход.")
                return True
        return False
