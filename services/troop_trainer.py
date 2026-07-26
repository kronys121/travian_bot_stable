import logging
from bs4 import BeautifulSoup
from utils.base_action import BaseAction
from utils.exceptions import CaptchaDetectedError


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

    def _parse_owned_troops(self, html: str) -> dict | None:
        """
        Считает ВСЕ свои войска по типам со страницы обзора точки сбора (tt=1):
          - дома/в своих оазисах:  table.troop_details[data-did]
          - в пути (набеги):        table.troop_details.outRaid
          - возвращаются:           table.troop_details.inReturn
        В каждой таблице строка с числами — tbody.units.last > tr, ячейки td.unit
        по порядку (1..10 = tN, 11 = герой); класс none = 0.

        Возвращает {index: total} или None, если таблиц войск на странице нет
        (страница не та / не прогрузилась) — тогда лучше считать «неизвестно».
        """
        soup = BeautifulSoup(html or '', 'html.parser')
        tables = (soup.select('table.troop_details[data-did]')
                  + soup.select('table.troop_details.outRaid')
                  + soup.select('table.troop_details.inReturn'))
        if not tables:
            return None
        totals: dict = {}
        for table in tables:
            row = table.select_one('tbody.units.last tr') or table.select_one('tbody.units tr')
            if not row:
                continue
            for i, cell in enumerate(row.select('td.unit')):
                if 'none' in (cell.get('class') or []):
                    continue
                digits = ''.join(c for c in cell.get_text() if c.isdigit())
                if digits:
                    totals[i + 1] = totals.get(i + 1, 0) + int(digits)
        return totals

    def get_owned_count(self, troop_index: int) -> int:
        """
        ВСЕГО своих войск типа t{troop_index} = дома + в пути (набеги/возврат).
        Именно это надо сравнивать с целью тренировки, иначе бот, отправив
        войска на оазисы, видит «дома 0» и переобучает.

        Возвращает -1, если страницу разобрать не удалось (не заказываем вслепую).
        """
        try:
            self.safe_goto(f"{self.config.base_url}/{self.LOCATORS['rally_troops']}")
            self.human_sleep(1.0, 2.0)
            totals = self._parse_owned_troops(self.page.content())
            if totals is None:
                logging.info("[Train] Не удалось прочитать обзор войск (tt=1) — пропуск.")
                return -1
            return int(totals.get(int(troop_index), 0))
        except CaptchaDetectedError:
            # Капча должна дойти до runner._guard, иначе бот продолжает
            # ходить по страницам логин-редиректа и «не видит» проблему.
            raise
        except Exception as e:
            logging.debug(f"get_owned_count error: {e}")
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
            max_n = int(max_n)
            # Нереалистичное число = склеенные цифры из соседних узлов.
            # Лучше честное "неизвестно", чем заказ на 12 000 000 юнитов.
            if max_n > 100000:
                logging.warning(f"⚠️ Подозрительный максимум t{troop_index}: {max_n} — считаю неизвестным.")
                return -1
            return max_n
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
        elif spend_pct < 100:
            # -1 = максимум по ресурсам прочитать не удалось. Раньше бюджет
            # spend_pct в этом случае просто исчезал и заказывалось ВСЁ.
            if max_batch > 0:
                logging.warning(
                    f"⚠️ Максимум по ресурсам t{troop_index} не прочитан — "
                    f"бюджет {spend_pct}% применить не к чему, ограничиваюсь партией {max_batch}."
                )
            else:
                logging.warning(
                    f"⚠️ Максимум по ресурсам t{troop_index} не прочитан — "
                    f"бюджет {spend_pct}% применить не к чему, заказ отложен."
                )
                return False
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
                # Результат human_click раньше терялся: непрошедший клик
                # рапортовался как успешный заказ.
                if not self.human_click(submit_btn):
                    logging.warning("⚠️ Не удалось нажать кнопку тренировки — заказ не отправлен.")
                    return False
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

        Возвращает 0 если очередь пуста, -1 если определить не удалось
        («неизвестно» — вызывающий сам решает, что с этим делать).
        """
        try:
            build_url = self.LOCATORS.get(building, self.LOCATORS['barracks'])
            self.safe_goto(f"{self.config.base_url}/{build_url}")
            self.human_sleep(1.0, 1.5)

            size = self.page.evaluate(r'''
                () => {
                    // FIX: раньше складывались ВСЕ числа подряд, включая обратный
                    // отсчёт (00:12:34) и часы сервера — очередь «раздувалась» до
                    // тысяч и min_queue_size навсегда блокировал тренировку.
                    // Вырезаем таймеры ДО поиска чисел и берём ПЕРВОЕ число.
                    const clean = t => String(t || '').replace(/\d{1,2}:\d{2}:\d{2}/g, ' ');
                    // \u0420\u0430\u0437\u0434\u0435\u043B\u0438\u0442\u0435\u043B\u044C \u0442\u044B\u0441\u044F\u0447 \u0437\u0430\u0441\u0447\u0438\u0442\u044B\u0432\u0430\u0435\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u043F\u0435\u0440\u0435\u0434 \u0433\u0440\u0443\u043F\u043F\u043E\u0439 \u0438\u0437
                    // \u0440\u043E\u0432\u043D\u043E 3 \u0446\u0438\u0444\u0440, \u0438\u043D\u0430\u0447\u0435 \u0434\u0432\u0430 \u0447\u0438\u0441\u043B\u0430 \u043F\u043E\u0434\u0440\u044F\u0434 ("5 120") \u0441\u043D\u043E\u0432\u0430
                    // \u0441\u043A\u043B\u0435\u044F\u0442\u0441\u044F \u0432 \u043E\u0434\u043D\u043E.
                    const num = t => {
                        const m = clean(t).match(/\d{1,3}(?:[.,\s\u00A0]\d{3})+|\d+/);
                        if (!m) return NaN;
                        return parseInt(m[0].replace(/[.,\s\u00A0]/g, ''), 10);
                    };

                    let total = 0;
                    let found = false;
                    // Вариант 1: строки очереди. Количество лежит в отдельной
                    // ячейке (.amt/.units/.count); strong убран — там же
                    // рендерится таймер.
                    const rows = document.querySelectorAll('.trainList .trainUnit, .buildingList .item');
                    rows.forEach(row => {
                        const cell = row.querySelector('.amt, .units, .count');
                        if (!cell) return;
                        const n = num(cell.textContent);
                        if (!isNaN(n) && n > 0) { total += n; found = true; }
                    });
                    if (found) return total;
                    // Строки очереди есть, а количество не вычитали => разметка
                    // не та. Честнее вернуть "неизвестно", чем 0: на 0 бот
                    // закажет весь дефицит поверх уже строящегося.
                    if (rows.length) return -1;

                    // Вариант 2: текст вида "Обучается: 45"
                    const info = document.querySelector('.troopTraining, .trainInfo');
                    if (info) {
                        const n = num(info.textContent);
                        return isNaN(n) ? 0 : n;
                    }

                    // Контейнер очереди есть, заданий в нём нет => очередь пуста.
                    if (document.querySelector('.trainList, .buildingList')) return 0;
                    // Ни очереди, ни списка — страница не та / не прогрузилась.
                    return -1;
                }
            ''')
            return int(size)
        except CaptchaDetectedError:
            raise
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
          1. village_queues[village_name] — если КЛЮЧ есть, он ГЛАВНЫЙ:
             пустая очередь деревни = ничего не тренируем (без фолбэка).
          2. village_queues["*"]           — правило «все деревни»
          3. training.queue                — глобальная очередь
          4. Старый одиночный формат       — обратная совместимость
        """
        settings = self._current_settings()
        default_building = settings.get("building", "barracks")
        village_queues = settings.get("village_queues") or {}

        # 1. Очередь конкретной деревни. Ключ задан в GUI => он решающий.
        if (village_name and isinstance(village_queues, dict)
                and village_name in village_queues):
            raw = village_queues.get(village_name)
            norm = self._normalize_queue(raw, default_building) if isinstance(raw, list) else []
            if norm:
                logging.info(f"[Train] Деревня '{village_name}': своя очередь ({len(norm)} юн.)")
            else:
                logging.info(f"[Train] Деревня '{village_name}': очередь пуста — тренировка пропущена.")
            return norm

        # 2. Правило «все деревни» ("*")
        if isinstance(village_queues, dict):
            raw = village_queues.get("*")
            if isinstance(raw, list) and raw:
                norm = self._normalize_queue(raw, default_building)
                if norm:
                    logging.info(f"[Train] Деревня '{village_name}': очередь из village_queues['*'] ({len(norm)} юн.)")
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

        # Сколько типов войск очередь тренирует в каждом здании.
        # get_training_queue_size считает здание ЦЕЛИКОМ, без разбивки по типам,
        # поэтому вычитать его из цели конкретного типа можно только когда
        # в этом здании тренируется ровно один тип.
        from collections import Counter
        types_per_building = Counter(j.get("building") for j in queue)

        for job in queue:
            troop_idx = job["troop_type_index"]
            target    = job["target_count"]
            building  = job["building"]
            if target <= 0:
                continue

            # Сколько юнитов уже стоит в очереди здания.
            # FIX: раньше это читалось только при min_queue_size > 0 и никак
            # не влияло на размер заказа — бот каждые 15 минут заказывал
            # ВЕСЬ дефицит заново поверх уже строящегося.
            in_queue = self.get_training_queue_size(building)
            if in_queue < 0:
                logging.warning(
                    f"[{building}] Очередь тренировки не читается — считаю её пустой."
                )
                in_queue = 0
            if min_queue > 0 and in_queue >= min_queue:
                logging.info(
                    f"[{building}] t{troop_idx}: в очереди уже {in_queue} >= {min_queue} — пропуск."
                )
                continue

            # Всего войск этого типа = дома + в пути (набеги/возврат),
            # иначе после отправки на оазисы бот видит «дома 0» и переобучает.
            current = self.get_owned_count(troop_idx)
            if current < 0:
                logging.info(f"Не удалось определить кол-во войск t{troop_idx}. Пропуск.")
                continue

            logging.info(
                f"[{building}] Войск t{troop_idx} (всего, вкл. в пути): {current}/{target}"
                f"{f', в очереди {in_queue}' if in_queue else ''}"
            )

            if current >= target:
                logging.info(f"t{troop_idx}: цель достигнута.")
                continue

            # Очередь здания идёт в зачёт цели, но только если в этом здании
            # тренируется один тип войск. Иначе заказ первого типа списывался
            # со второго (обе фаланги и мечники стоят в одних казармах),
            # и второй тип не тренировался, пока очередь не опустеет.
            if types_per_building[building] > 1:
                counted_in_queue = 0
                if in_queue:
                    logging.debug(
                        f"[{building}] в очереди {in_queue} юнитов, но здание делят "
                        f"{types_per_building[building]} типа(ов) — в зачёт цели не идут."
                    )
            else:
                counted_in_queue = in_queue
            need = target - current - counted_in_queue
            if need <= 0:
                logging.info(
                    f"t{troop_idx}: цель закрыта с учётом очереди "
                    f"({current} + {counted_in_queue} >= {target})."
                )
                continue
            logging.info(f"t{troop_idx}: нужно дотренировать {need} юнитов.")
            self.train_troops(need, troop_idx, building=building)
            self.human_sleep(1.5, 3.0)
