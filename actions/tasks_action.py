import logging
from utils.base_action import BaseAction

class TasksAction(BaseAction):
    LOCATORS = {
        'tasks_container': '.taskOverview',
        'collect_btn': '.task.achieved.group .progress .textButtonV2',
        # Ежедневные квесты (на главной dorf1.php)
        'daily_quests': '.dailyQuests',
        'daily_indicator': '.dailyQuests .indicator',
        # Шаг 1: textButtonV2 buttonFramed collectRewards rectangle withText green
        'daily_collect_rewards_btn': '.textButtonV2.buttonFramed.collectRewards, '
                                     'button.collectRewards',
        # Шаг 2: textButtonV2 buttonFramed collect collectable rectangle withText green
        'daily_collect_btn': '.textButtonV2.buttonFramed.collect.collectable, '
                             'button.collect.collectable',
    }

    def __init__(self, page, config):
        super().__init__(page, config)

    def collect_daily_quests(self):
        """
        Сбор наград за ежедневные квесты. Делается на главной странице:
          1) на dorf1.php ищем блок .dailyQuests
          2) если у него есть .indicator (значит есть готовая награда) — клик
          3) в открывшемся окне жмём кнопку collectRewards (зелёная "Забрать")
        Возвращает число собранных наград.
        """
        logging.info("📅 Проверка ежедневных квестов...")
        self.safe_goto(self.config.login_url)  # dorf1.php

        try:
            self.page.locator(self.LOCATORS['daily_quests']).first.wait_for(timeout=5000)
        except Exception:
            logging.info("📅 Блок ежедневных квестов не найден — пропуск.")
            return 0

        # Индикатор = есть готовая награда. Нет индикатора — собирать нечего.
        indicator = self.page.locator(self.LOCATORS['daily_indicator']).first
        try:
            if indicator.count() == 0 or not indicator.is_visible():
                logging.info("📅 Готовых ежедневных наград нет.")
                return 0
        except Exception:
            logging.info("📅 Готовых ежедневных наград нет.")
            return 0

        # Открываем окно ежедневных квестов кликом по блоку/индикатору
        try:
            if not self.human_click(indicator):
                self.human_click(self.page.locator(self.LOCATORS['daily_quests']).first)
        except Exception:
            self.human_click(self.page.locator(self.LOCATORS['daily_quests']).first)
        self.human_sleep(1.0, 2.0)

        collected = 0
        while True:
            # Шаг 1: кнопка collectRewards — открывает список наград
            rewards_btn = self.page.locator(self.LOCATORS['daily_collect_rewards_btn']).first
            try:
                if rewards_btn.count() > 0 and rewards_btn.is_visible() and rewards_btn.is_enabled():
                    self.human_click(rewards_btn)
                    logging.info("📅 Нажата кнопка collectRewards, жду collect...")
                    self.human_sleep(0.8, 1.5)
            except Exception:
                logging.debug("suppressed error in actions/tasks_action:67", exc_info=True)

            # Шаг 2: кнопка collect collectable — забираем награду
            btn = self.page.locator(self.LOCATORS['daily_collect_btn']).first
            try:
                if btn.count() == 0 or not btn.is_visible() or not btn.is_enabled():
                    break
                if self.human_click(btn):
                    collected += 1
                    logging.info(f"Ежедневная награда #{collected} собрана!")
                    self.human_sleep(1.0, 1.8)
                else:
                    break
            except Exception:
                break

        if collected == 0:
            logging.info("Кнопка получения ежедневной награды не найдена.")
        else:
            logging.info(f"Ежедневных наград собрано: {collected}")

        self.human_sleep(0.8, 1.5)
        self.safe_goto(self.config.login_url)
        return collected

    def collect_tasks(self):
        logging.info("🚀 Перехожу в меню заданий...")
        self.safe_goto(self.config.tasks_url)

        try:
            self.page.locator(self.LOCATORS['tasks_container']).wait_for(timeout=5000)
        except Exception:
            logging.warning("⚠️ Меню заданий не прогрузилось.")
            return 0

        collected_count = 0

        while True:
            buttons = self.page.locator(self.LOCATORS['collect_btn']).all()

            if not buttons:
                break

            clicked_in_this_round = False

            for btn in buttons:
                try:
                    if btn.is_visible() and btn.is_enabled():
                        if self.human_click(btn):
                            collected_count += 1
                            logging.info(f"✅ Награда #{collected_count} собрана!")
                            clicked_in_this_round = True
                            break
                except Exception:
                    continue

            if not clicked_in_this_round:
                break

        if collected_count == 0:
            logging.info("🤷‍♂️ Нет открытых заданий для сбора.")
        else:
            logging.info(f"🎉 Сбор завершен! Успешных нажатий: {collected_count}")

        self.human_sleep(1.0, 2.0)
        logging.info("🏠 Возвращаюсь в главную деревню...")
        self.safe_goto(self.config.login_url)

        return collected_count
