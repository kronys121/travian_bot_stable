import logging
import time
import random

from playwright.sync_api import Page

# gid Ратуши в Travian Legends
TOWN_HALL_GID = "24"

# Селекторы кнопок запуска праздника
# Малый праздник — первая кнопка .green внутри .celebration
# Большой праздник — вторая (доступен позже)
SEL_CELEBRATE_BTN   = ".celebration .green, .start .green, button.green"
SEL_ALREADY_RUNNING = ".celebration .inProgress, .gold .inProgress, .timer"


class CelebrationAction:
    """
    Авто-праздники в Ратуше (Town Hall, gid=24).

    Логика:
    - Переходим в каждую деревню, открываем Ратушу.
    - Если праздник уже идёт — пропускаем деревню.
    - Если кнопка запуска доступна — нажимаем (малый праздник).
    - Запись в лог: деревня, тип праздника, время до конца.

    Вызывается из runner как отдельная задача по расписанию.
    """

    def __init__(self, page: Page, config, villages_fn=None):
        """
        Args:
            page:        Playwright-страница (управляется runner).
            config:      Конфиг бота (base_url, headless и т.д.).
            villages_fn: Callable без аргументов → [{'id': str, 'name': str}].
                         Если None — бот работает только с текущей деревней.
        """
        self.page        = page
        self.config      = config
        self.villages_fn = villages_fn

    # ------------------------------------------------------------------
    # Публичный метод — вызывается из runner
    # ------------------------------------------------------------------

    def run(self):
        """
        Обходит все деревни аккаунта и запускает праздник там, где он не идёт.
        Если villages_fn не задан — обрабатывает только текущую активную деревню.
        """
        villages = []
        if self.villages_fn:
            try:
                villages = self.villages_fn() or []
            except Exception as e:
                logging.warning(f"[Celebration] Не удалось получить список деревень: {e}")

        if not villages:
            # Только текущая деревня
            self._celebrate_in_current()
            return

        started = 0
        for v in villages:
            vid  = v.get("id")
            name = v.get("name", vid or "?")
            try:
                url = self.config.base_url + "/dorf2.php"
                if vid:
                    url += f"?newdid={vid}"
                self.page.goto(url)
                self._sleep(1.0, 2.0)
                if self._celebrate_in_current(village_name=name):
                    started += 1
            except Exception as e:
                logging.error(f"[Celebration] Ошибка в деревне {name}: {e}")

        logging.info(f"[Celebration] Готово. Праздников запущено: {started}/{len(villages)}")

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _celebrate_in_current(self, village_name: str = "текущая") -> bool:
        """
        Открывает Ратушу в текущей деревне и запускает праздник если возможно.
        Возвращает True если праздник был запущен.
        """
        try:
            # Ищем ссылку на Ратушу в сайдбаре или на dorf2
            th_link = self._find_town_hall_link()
            if not th_link:
                logging.info(f"[Celebration] {village_name}: Ратуша не построена — пропуск.")
                return False

            self.page.goto(th_link)
            self._sleep(1.0, 1.5)

            # Праздник уже идёт?
            if self._is_running():
                logging.info(f"[Celebration] {village_name}: праздник уже идёт.")
                return False

            # Кнопка запуска праздника
            btn = self._find_celebrate_btn()
            if not btn:
                logging.info(f"[Celebration] {village_name}: кнопка праздника недоступна (нет ресурсов или не построена).")
                return False

            btn.click()
            self._sleep(0.8, 1.5)

            # Подтверждение (некоторые сервера показывают диалог)
            self._confirm_if_needed()

            logging.info(f"[Celebration] {village_name}: праздник запущен.")
            return True

        except Exception as e:
            logging.error(f"[Celebration] {village_name}: {e}")
            return False

    def _find_town_hall_link(self) -> str | None:
        """
        Ищет ссылку на Ратушу среди зданий dorf2.
        Сначала пробует через JavaScript (data-gid), потом через href.
        """
        base = self.config.base_url
        try:
            link = self.page.evaluate(f"""
            () => {{
                // Ратуша в Travian — gid=24
                const a = document.querySelector(
                    'a[href*="gid=24"], [data-gid="24"] a, .buildingSlot[data-gid="24"] a'
                );
                return a ? a.href : null;
            }}
            """)
            if link:
                return link
        except Exception:
            logging.debug("suppressed error in actions/celebration_action:142", exc_info=True)

        # Перейти на dorf2 и поискать там
        try:
            self.page.goto(f"{base}/dorf2.php")
            self._sleep(0.8, 1.2)
            link = self.page.evaluate("""
            () => {
                const a = document.querySelector(
                    'a[href*="gid=24"], [data-gid="24"] a, .buildingSlot[data-gid="24"] a'
                );
                return a ? a.href : null;
            }
            """)
            return link
        except Exception:
            return None

    def _is_running(self) -> bool:
        """Проверяет есть ли активный праздник на странице Ратуши."""
        try:
            # Таймер обратного отсчёта — знак что праздник идёт
            timers = self.page.locator(".timer, .countDown, .inProgress").all()
            if timers:
                return True
            # Кнопка старта задизейблена тоже означает что что-то идёт
            btn = self.page.locator(SEL_CELEBRATE_BTN).first
            if btn.count() and btn.is_disabled():
                return True
        except Exception:
            logging.debug("suppressed error in actions/celebration_action:172", exc_info=True)
        return False

    def _find_celebrate_btn(self):
        """Возвращает Locator зелёной кнопки праздника или None."""
        try:
            for sel in [
                ".celebration .green",
                ".start .green",
                "button.green",
                ".buildingDetails .green",
            ]:
                loc = self.page.locator(sel).first
                try:
                    if loc.is_visible() and loc.is_enabled():
                        return loc
                except Exception:
                    continue
        except Exception:
            logging.debug("suppressed error in actions/celebration_action:191", exc_info=True)
        return None

    def _confirm_if_needed(self):
        """Подтверждает диалог если он появился после нажатия кнопки праздника."""
        try:
            ok = self.page.locator(
                ".dialogButtonOk, .green.dialogButton, button.green"
            ).first
            if ok.is_visible():
                ok.click()
                self._sleep(0.5, 1.0)
        except Exception:
            logging.debug("suppressed error in actions/celebration_action:204", exc_info=True)

    def _sleep(self, lo: float, hi: float):
        time.sleep(random.uniform(lo, hi))
