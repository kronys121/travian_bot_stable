import logging
from utils.base_action import BaseAction


class TroopTrainer(BaseAction):
    """
    Авто-тренировка войск.

    Настройки приходят из SettingsStore (bot_settings_{acc}.json, секция training):
        troop_type_index: 1-11 (тип юнита)
        target_count: 100 (целевое кол-во)
        building: 'barracks' или 'stable'
    """

    LOCATORS = {
        'barracks': 'build.php?gid=19',
        'stable': 'build.php?gid=20',
        # Обзор своих войск в деревне (вкладка "Войска" точки сбора)
        'rally_troops': 'build.php?id=39&gid=16&tt=1',
        'train_input': 'input[name="t{index}"]',
        'train_btn': '.green.submit, button[type="submit"].green',
        'queue_info': '.buildingList .buildDuration',
        'in_training': '.trainInfo, .troopTraining',
    }

    def __init__(self, page, config, settings_store=None):
        super().__init__(page, config)
        self.settings_store = settings_store
        # Локальные настройки — используются, если store не передан
        self.settings = {
            "troop_type_index": 1,
            "target_count": 100,
            "building": "barracks",
        }

    def _current_settings(self) -> dict:
        """Актуальные настройки: из SettingsStore (live) или локальные."""
        if self.settings_store:
            merged = dict(self.settings)
            merged.update(self.settings_store.section("training"))
            return merged
        return self.settings

    def get_current_count(self, troop_index: int) -> int:
        """
        Читает кол-во своих войск типа t{troop_index} из вкладки "Войска"
        точки сбора (build.php?id=39&gid=16&tt=1).

        Разметка Travian:
          - блок домашних войск = .troop_details БЕЗ доп. классов
            (варианты .troop_details.outHero и т.п. пропускаем — это чужие/движущиеся);
          - внутри .units.last > tr идут ячейки .unit по порядку (1-я = t1, 2-я = t2, ...);
          - если войск данного типа нет — ячейка имеет класс .unit.none.

        Возвращает -1, если таблицу/тип определить не удалось (не путать с 0).
        """
        try:
            self.safe_goto(f"{self.config.base_url}/{self.LOCATORS['rally_troops']}")
            self.human_sleep(1.0, 2.0)

            count = self.page.evaluate(f'''
                () => {{
                    // Берём ТОЛЬКО блок с классом ровно "troop_details"
                    // (пропускаем troop_details outHero и прочие варианты)
                    const blocks = document.querySelectorAll('.troop_details');
                    let home = null;
                    for (const b of blocks) {{
                        const cls = (b.getAttribute('class') || '').trim().split(/\\s+/);
                        if (cls.length === 1 && cls[0] === 'troop_details') {{ home = b; break; }}
                    }}
                    // fallback: первый troop_details без outHero
                    if (!home) {{
                        for (const b of blocks) {{
                            if (!b.classList.contains('outHero')) {{ home = b; break; }}
                        }}
                    }}
                    if (!home) return -1;

                    const row = home.querySelector('.units.last tr') ||
                                home.querySelector('.units tr');
                    if (!row) return -1;

                    const cells = row.querySelectorAll('.unit');
                    if (!cells.length) return -1;

                    // t{troop_index}: 1-based позиция ячейки .unit
                    const idx = {troop_index} - 1;
                    if (idx < 0 || idx >= cells.length) return -1;

                    const cell = cells[idx];
                    // "none" = войск этого типа нет
                    if (cell.classList.contains('none')) return 0;

                    const n = parseInt(cell.textContent.replace(/\\D/g, ''), 10);
                    return isNaN(n) ? 0 : n;
                }}
            ''')
            return int(count)
        except Exception as e:
            # -1 = "неизвестно": бот НЕ должен заказывать полную тренировку вслепую
            logging.debug(f"Ошибка чтения войск: {e}")
            return -1

    def get_max_affordable(self, troop_index: int) -> int:
        """
        Максимум юнитов, доступных к тренировке на ТЕКУЩИЕ ресурсы.
        Читается из ссылки "/N" рядом с полем ввода — Travian сам
        считает этот максимум по стоимости юнита и складам.
        Возвращает -1, если определить не удалось.
        """
        try:
            max_n = self.page.evaluate(f'''
                () => {{
                    const inp = document.querySelector('input[name="t{troop_index}"]');
                    if (!inp) return -1;
                    const cell = inp.closest('td') || inp.parentElement;
                    if (!cell) return -1;
                    const link = cell.querySelector('a');
                    const src = link ? link.textContent : cell.textContent;
                    const m = String(src).replace(/[\\u00A0\\s.,]/g, '').match(/\\/?(\\d+)$/) ||
                              String(src).match(/(\\d+)/);
                    return m ? parseInt(m[1], 10) : -1;
                }}
            ''')
            return int(max_n)
        except Exception as e:
            logging.debug(f"max affordable error: {e}")
            return -1

    def train_troops(self, count: int, troop_index: int, building: str = None) -> bool:
        """
        Заказывает тренировку {count} юнитов типа t{troop_index}
        С УЧЁТОМ БЮДЖЕТА:
          spend_pct  — тратить не более N% от доступных ресурсов (по умолч. 100)
          max_batch  — не более N юнитов за один заказ (0 = без лимита)
        building — казарма/конюшня; если не задан, берётся из настроек.
        Возвращает True при успехе.
        """
        if count <= 0:
            return False

        settings = self._current_settings()
        if building is None:
            building = settings.get("building", "barracks")
        build_url = self.LOCATORS.get(building, self.LOCATORS['barracks'])
        self.safe_goto(f"{self.config.base_url}/{build_url}")
        self.human_sleep(1.5, 2.5)

        # --- Бюджет: режем заказ по проценту ресурсов и размеру партии ---
        spend_pct = max(1, min(100, int(settings.get("spend_pct", 100) or 100)))
        max_batch = int(settings.get("max_batch", 0) or 0)

        affordable = self.get_max_affordable(troop_index)
        original = count
        if affordable >= 0:
            # affordable — макс. на ВСЕ ресурсы; ограничиваем долей spend_pct
            budget_cap = affordable * spend_pct // 100
            count = min(count, budget_cap)
        if max_batch > 0:
            count = min(count, max_batch)

        if count <= 0:
            logging.info(
                f"💰 Бюджет исчерпан: доступно {max(affordable, 0)} юнитов, "
                f"лимит {spend_pct}% => 0. Тренировка отложена."
            )
            return False
        if count < original:
            logging.info(
                f"💰 Заказ урезан бюджетом: {original} -> {count} "
                f"(лимит {spend_pct}% ресурсов{f', партия <= {max_batch}' if max_batch else ''})"
            )

        input_selector = f'input[name="t{troop_index}"]'
        try:
            t_input = self.page.locator(input_selector).first
            if not t_input.is_visible() or t_input.is_disabled():
                logging.warning(f"⚠️ Поле t{troop_index} недоступно.")
                return False

            t_input.fill(str(count))
            self.human_sleep(0.5, 1.0)

            submit_btn = self.page.locator(self.LOCATORS['train_btn']).first
            if submit_btn.is_visible() and submit_btn.is_enabled():
                self.human_click(submit_btn)
                logging.info(f"⚔️ Отправлено в тренировку: {count} юнитов t{troop_index}.")
                return True
            else:
                logging.warning("⚠️ Кнопка тренировки недоступна (недостаточно ресурсов?).")
                return False
        except Exception as e:
            logging.error(f"❌ Ошибка тренировки: {e}")
            return False

    def get_training_queue_size(self, building: str) -> int:
        """
        Считает количество юнитов, уже стоящих в очереди тренировки здания.
        Открывает казарму/конюшню и суммирует все числа из .buildDuration
        (или аналогичных элементов списка очереди).
        Возвращает 0 если очередь пуста, -1 если определить не удалось.
        """
        try:
            build_url = self.LOCATORS.get(building, self.LOCATORS['barracks'])
            self.safe_goto(f"{self.config.base_url}/{build_url}")
            self.human_sleep(1.0, 1.5)

            size = self.page.evaluate(r'''
                () => {
                    // Travian показывает очередь в .buildingList li или .trainUnit
                    // Каждая запись содержит количество в .details или в заголовке
                    let total = 0;
                    // Вариант 1: .trainList .trainUnit .amt / .units / число в тексте
                    document.querySelectorAll('.trainList .trainUnit, .buildingList .item').forEach(row => {
                        const txt = row.querySelector('.amt, .units, .count, strong');
                        const n = txt ? parseInt(txt.textContent.replace(/\D/g, ''), 10) : NaN;
                        if (!isNaN(n) && n > 0) total += n;
                    });
                    if (total > 0) return total;
                    // Вариант 2: текст вида "Обучается: 45" в .troopTraining / .trainInfo
                    const info = document.querySelector('.troopTraining, .trainInfo');
                    if (info) {
                        const m = info.textContent.match(/(\d+)/g);
                        if (m) return m.reduce((s, x) => s + parseInt(x, 10), 0);
                    }
                    return 0;
                }
            ''')
            return int(size)
        except Exception as e:
            logging.debug(f"get_training_queue_size error: {e}")
            return -1

    def _normalize_queue(self, raw: list, default_building: str = "barracks") -> list:
        """Нормализует сырой список заданий в единый формат."""
        norm = []
        for item in (raw or []):
            try:
                norm.append({
                    "troop_type_index": int(item.get("troop_type_index", 1)),
                    "target_count":     int(item.get("target_count", 0)),
                    "building":         item.get("building", default_building),
                })
            except Exception:
                continue
        return norm

    def _get_train_queue(self, village_name: str = None) -> list:
        """
        Возвращает очередь тренировки для деревни.

        Приоритет:
          1. training.village_queues[village_name] — если задано для деревни
          2. training.village_queues["*"]           — правило «все деревни»
          3. training.queue                         — глобальная очередь
          4. Старый одиночный формат               — обратная совместимость
        """
        settings = self._current_settings()
        default_building = settings.get("building", "barracks")

        # 1+2. Очередь конкретной деревни или "*"
        village_queues = settings.get("village_queues") or {}
        if isinstance(village_queues, dict) and village_queues:
            candidates = []
            if village_name:
                candidates.append(village_name)
            candidates.append("*")
            for key in candidates:
                raw = village_queues.get(key)
                if isinstance(raw, list) and raw:
                    norm = self._normalize_queue(raw, default_building)
                    if norm:
                        logging.info(f"[Train] Деревня '{village_name}': очередь из village_queues['{key}'] ({len(norm)} юн.)")
                        return norm

        # 3. Глобальная очередь
        global_queue = settings.get("queue")
        if isinstance(global_queue, list) and global_queue:
            norm = self._normalize_queue(global_queue, default_building)
            if norm:
                return norm

        # 4. Старый одиночный формат
        return [{
            "troop_type_index": int(settings.get("troop_type_index", 1)),
            "target_count":     int(settings.get("target_count", 100)),
            "building":         default_building,
        }]

    def auto_train(self, village_name: str = None):
        """
        Главный метод: дотренировывает все типы войск из очереди до целей.
        Поддерживает разные очереди по деревням и порог уже стоящих в очереди.

        village_name — имя активной деревни (из сайдбара), используется для
        выбора нужной очереди из training.village_queues.
        """
        if self.settings_store and not self.settings_store.feature('train_enabled', False):
            logging.info("Тренировка выключена в настройках — пропуск.")
            return

        settings = self._current_settings()
        min_queue = int(settings.get("min_queue_size", 0) or 0)

        queue = self._get_train_queue(village_name)
        label = f"'{village_name}'" if village_name else "глобальная"
        logging.info(f"Очередь тренировки [{label}]: {len(queue)} тип(ов) войск.")

        for job in queue:
            troop_idx = job["troop_type_index"]
            target    = job["target_count"]
            building  = job["building"]
            if target <= 0:
                continue

            # Пункт 2: проверяем сколько уже стоит в очереди здания
            if min_queue > 0:
                in_queue = self.get_training_queue_size(building)
                if in_queue >= min_queue:
                    logging.info(
                        f"[{building}] t{troop_idx}: в очереди уже {in_queue} >= {min_queue} — пропуск."
                    )
                    continue

            # Сколько войск уже есть дома
            current = self.get_current_count(troop_idx)
            if current < 0:
                logging.info(f"Не удалось определить кол-во войск t{troop_idx}. Пропуск.")
                continue

            logging.info(f"[{building}] Войск t{troop_idx}: {current}/{target}")

            if current >= target:
                logging.info(f"t{troop_idx}: цель достигнута.")
                continue

            need = target - current
            logging.info(f"t{troop_idx}: нужно дотренировать {need} юнитов.")
            self.train_troops(need, troop_idx, building=building)
            self.human_sleep(1.5, 3.0)
