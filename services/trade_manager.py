import logging
from utils.base_action import BaseAction


class TradeManager(BaseAction):
    """
    Авто-торговля ресурсами.

    Модули:
        npc_trade()  — обмен через NPC (в маркетплейсе)
        send_resources()  — отправка ресурсов в другую деревню
        check_warehouse_capacity()  — проверка заполненности склада
    """

    LOCATORS = {
        'marketplace': 'build.php?gid=17',
        'npc_tab': '.npcTrader, [href*="npc"], #npcTrade',
        'resource_inputs': '#npc_market_result input, .npcTrader input[type="text"]',
        'npc_submit': '#btn_trade, .npcTrader button.green',
        'npc_confirm': '#dialogContent button.green, #btn_ok',
        'warehouse_bar': '#stockBar .warehouse, .resourceWrapper .warehouse',
        'granary_bar': '#stockBar .granary, .resourceWrapper .granary',
        'current_resources': '#stockBar .value, .stockBar .value',
        'max_resources': '#stockBar .max, .stockBar .max',
        'send_merchant': 'build.php?gid=17&tt=5',
    }

    def check_warehouse_capacity(self) -> dict:
        """
        Читает текущие запасы и емкость складов.

        Возвращает:
            {
                'wood': (current, max),
                'clay': (current, max),
                'iron': (current, max),
                'crop': (current, max),
                'warehouse_full_pct': 85.5,
                'granary_full_pct': 92.0,
            }
        """
        try:
            result = self.page.evaluate(r'''
                () => {
                    const keys = ['wood', 'clay', 'iron', 'crop'];
                    const res = {};

                    // 1) Основной путь: Travian Legends кладёт данные в window.resources
                    //    { storage: {l1..l4}, maxStorage: {l1..l4} }
                    const R = window.resources;
                    if (R && R.storage && R.maxStorage) {
                        keys.forEach((k, i) => {
                            const id = 'l' + (i + 1);
                            res[k] = [
                                Math.floor(R.storage[id] || 0),
                                Math.floor(R.maxStorage[id] || 1),
                            ];
                        });
                    } else {
                        // 2) Fallback: #l1..#l4 — это ТЕКУЩИЕ значения (не x/y!),
                        //    ёмкость берём из #stockBarWarehouse / #stockBarGranary
                        // FIX: раньше вырезались ВСЕ не-цифры, и "1.200/2.000"
                        // склеивалось в 12002000 — склад «заполнен на 0%»,
                        // NPC-обмен не запускался, а склад тем временем тёк.
                        // Берём ПЕРВОЕ число и убираем разделители тысяч.
                        // \u0420\u0430\u0437\u0434\u0435\u043B\u0438\u0442\u0435\u043B\u044C \u0442\u044B\u0441\u044F\u0447 \u0437\u0430\u0441\u0447\u0438\u0442\u044B\u0432\u0430\u0435\u043C, \u0442\u043E\u043B\u044C\u043A\u043E \u0435\u0441\u043B\u0438 \u0437\u0430 \u043D\u0438\u043C
                        // \u0440\u043E\u0432\u043D\u043E 3 \u0446\u0438\u0444\u0440\u044B: \u0438\u043D\u0430\u0447\u0435 \u0443\u0437\u0435\u043B \u0432\u0438\u0434\u0430 "1200 2000" (\u0442\u0435\u043A\u0443\u0449\u0435\u0435
                        // \u0438 \u0451\u043C\u043A\u043E\u0441\u0442\u044C \u0447\u0435\u0440\u0435\u0437 \u043F\u0440\u043E\u0431\u0435\u043B) \u0441\u043D\u043E\u0432\u0430 \u0441\u043A\u043B\u0435\u0438\u043B\u0441\u044F \u0431\u044B \u0432 12002000.
                        const parseNum = el => {
                            if (!el) return 0;
                            const m = (el.textContent || '')
                                .match(/\d{1,3}(?:[.,\s\u00A0]\d{3})+|\d+/);
                            if (!m) return 0;
                            return parseInt(m[0].replace(/[.,\s\u00A0]/g, ''), 10) || 0;
                        };
                        // FIX: querySelector со списком селекторов отдаёт первый
                        // в порядке ДЕРЕВА, поэтому предок #stockBarWarehouse
                        // всегда выигрывал у вложенного .capacity. Явные фолбэки:
                        const pick = (...sels) => {
                            for (const s of sels) {
                                const el = document.querySelector(s);
                                if (el) return el;
                            }
                            return null;
                        };
                        const whCap = parseNum(pick(
                            '#stockBarWarehouse .capacity .value',
                            '#stockBarWarehouse .capacity',
                            '.warehouse .capacity .value',
                            '.warehouse .capacity',
                            '#stockBarWarehouse'
                        )) || 1;
                        const grCap = parseNum(pick(
                            '#stockBarGranary .capacity .value',
                            '#stockBarGranary .capacity',
                            '.granary .capacity .value',
                            '.granary .capacity',
                            '#stockBarGranary'
                        )) || 1;
                        keys.forEach((k, i) => {
                            const cur = parseNum(document.getElementById('l' + (i + 1)));
                            res[k] = [cur, i === 3 ? grCap : whCap];
                        });
                    }

                    // Склад: каждый из wood/clay/iron имеет свою ёмкость = ёмкость склада,
                    // поэтому % заполнения = максимальный из трёх.
                    const whMax = res.wood[1] || 1;
                    const worst = Math.max(res.wood[0], res.clay[0], res.iron[0]);
                    res.warehouse_full_pct = Math.round(worst / whMax * 100);
                    res.granary_full_pct = Math.round(res.crop[0] / (res.crop[1] || 1) * 100);
                    return res;
                }
                ''')
            return result or {}
        except Exception as e:
            logging.error(f"❌ Ошибка чтения склада: {e}")
            return {}

    def get_gold(self) -> int:
        """
        Читает баланс золота игрока. NPC-обмен стоит золота (или требует
        активного Travian Plus), поэтому без золота открывать таб бессмысленно.
        Возвращает -1, если определить не удалось (тогда обмен не блокируем).
        """
        try:
            gold = self.page.evaluate(r'''
                () => {
                    // Наиболее надёжно — глобальная переменная клиента
                    if (typeof window.gold === 'number') return window.gold;
                    // Фолбэк по DOM: значок золота в шапке
                    const el = document.querySelector(
                        '.gold .ajaxReplaceableGoldAmount, #gold, .gold value, .goldAmount'
                    );
                    if (el) {
                        const n = parseInt((el.textContent || '').replace(/\D/g, ''), 10);
                        if (!isNaN(n)) return n;
                    }
                    return -1;
                }
            ''')
            return int(gold)
        except Exception as e:
            logging.debug(f"get_gold error: {e}")
            return -1

    def npc_trade(self, target_ratio: dict = None, threshold_pct: int = 85,
                  min_gold: int = 3) -> bool:
        """
        Обмен ресурсами через NPC при переполнении склада.

        Args:
            target_ratio: Целевое соотношение, например:
                {'wood': 1, 'clay': 1, 'iron': 1, 'crop': 2}
            threshold_pct: Порог заполненности (в %), при котором запускается обмен.
            min_gold: Минимум золота для попытки обмена (NPC стоит золота).
        """
        if target_ratio is None:
            target_ratio = {'wood': 1, 'clay': 1, 'iron': 1, 'crop': 1}

        # Проверяем заполненность склада
        self.safe_goto(f"{self.config.base_url}/dorf1.php")
        self.human_sleep(1.0, 2.0)
        capacity = self.check_warehouse_capacity()

        wh_pct = capacity.get('warehouse_full_pct', 0)
        gr_pct = capacity.get('granary_full_pct', 0)

        if wh_pct < threshold_pct and gr_pct < threshold_pct:
            logging.info(f"📦 Склад {wh_pct}%, зернохранилище {gr_pct}% — обмен не нужен.")
            return False

        logging.info(f"🔄 Обмен NPC: склад {wh_pct}%, зернохранилище {gr_pct}%")

        # Проверяем золото ДО перехода в маркет: без золота NPC недоступен.
        gold = self.get_gold()
        if 0 <= gold < min_gold:
            logging.warning(f"🪙 Недостаточно золота для NPC ({gold} < {min_gold}) — обмен пропущен.")
            notifier = getattr(self.config, 'notifier', None)
            if notifier:
                try:
                    acc = getattr(self.config, 'name', 'bot')
                    notifier.send(
                        f"[{acc}] 🪙 Склад заполнен ({wh_pct}%/{gr_pct}%), "
                        f"но золота нет ({gold}) — NPC-обмен невозможен."
                    )
                except Exception as ne:
                    logging.debug(f"notifier gold alert error: {ne}")
            return False

        # Переходим на NPC
        self.safe_goto(f"{self.config.base_url}/{self.LOCATORS['marketplace']}")
        self.human_sleep(1.5, 2.5)

        npc_btn = self.page.locator(self.LOCATORS['npc_tab']).first
        if not npc_btn.is_visible():
            logging.warning("⚠️ Таб NPC недоступен (возможно, нет МП или нет золота).")
            return False

        self.human_click(npc_btn)
        self.human_sleep(1.5, 2.5)

        # Вычисляем целевое распределение
        # FIX: NPC-обмен требует, чтобы СУММА после = СУММЕ до.
        # Раньше бралась ёмкость склада (capacity[1]) — обмен никогда не проходил.
        try:
            keys_order = ['wood', 'clay', 'iron', 'crop']
            total_resources = sum(capacity.get(k, [0, 1])[0] for k in keys_order)
            ratio_sum = sum(target_ratio.values())
            new_values = {
                k: int(total_resources * (v / ratio_sum))
                for k, v in target_ratio.items()
            }
            # Остаток от округления кидаем в crop, чтобы сумма сошлась точно
            diff = total_resources - sum(new_values.values())
            new_values['crop'] = new_values.get('crop', 0) + diff

            inputs = self.page.locator(self.LOCATORS['resource_inputs']).all()
            for i, inp in enumerate(inputs[:4]):
                key = keys_order[i]
                val = new_values.get(key, 0)
                inp.fill(str(val))
                self.human_sleep(0.3, 0.7)

            submit_btn = self.page.locator(self.LOCATORS['npc_submit']).first
            if not (submit_btn.is_visible() and submit_btn.is_enabled()):
                logging.warning("⚠️ Кнопка NPC-обмена недоступна.")
                return False
            # Результат клика раньше игнорировался — обмен «выполнялся» в логе.
            if not self.human_click(submit_btn):
                logging.warning("⚠️ Не удалось нажать кнопку NPC-обмена.")
                return False
            self.human_sleep(1.0, 2.0)

            confirm_btn = self.page.locator(self.LOCATORS['npc_confirm']).first
            if confirm_btn.is_visible() and self.human_click(confirm_btn):
                logging.info(f"✅ NPC-обмен выполнен: {new_values}")
                return True
            logging.warning("⚠️ Подтверждение NPC-обмена не выполнено.")
        except Exception as e:
            logging.error(f"❌ Ошибка NPC-обмена: {e}")
        return False

    def _active_village_name(self):
        """Имя активной деревни из сайдбара (проверка, что newdid сработал)."""
        try:
            return self.page.evaluate(r'''
            () => {
                const active = document.querySelector(
                    '.listEntry.village.active, .villageList .active, #sidebarBoxVillages .active'
                );
                if (!active) return null;
                const el = active.querySelector('.name') || active.querySelector('a') || active;
                return el ? el.textContent.trim().slice(0, 40) : null;
            }
            ''')
        except Exception:
            return None

    @staticmethod
    def _same_village(active: str, expected: str) -> bool:
        """Сравнение имён деревень «по-человечески».

        Имена приходят из РАЗНЫХ парсеров: name_to_id собирает
        menu_manager.get_villages_detailed (querySelector('.name, a .name, a')
        — в порядке дерева обычно выигрывает <a> вместе с координатами),
        а здесь читается .name. Строгое != отменяло бы правило даже при
        правильной деревне, то есть выключало бы переброску целиком.
        """
        a = ' '.join(str(active).split()).lower()
        b = ' '.join(str(expected).split()).lower()
        if not a or not b:
            return True
        return a in b or b in a

    def run_transfers(self, rules: list, name_to_id: dict) -> int:
        """
        Переброска ресурсов между своими деревнями по ручным правилам.

        Args:
            rules: [{'from': '<имя деревни-донора>', 'to_x': int, 'to_y': int,
                     'res': ['wood','clay','iron','crop'], 'reserve': int}, ...]
            name_to_id: {'<имя деревни>': '<id или None>'} для навигации к донору.

        Для каждого правила: переходим в деревню-донора, читаем текущие ресурсы,
        по каждому ВЫБРАННОМУ ресурсу считаем (текущее - резерв) и шлём в цель.
        Возвращает число успешно выполненных правил.
        """
        base = getattr(self.config, 'base_url', None) or self.config.server_url
        keys = ('wood', 'clay', 'iron', 'crop')
        sent = 0
        for rule in (rules or []):
            try:
                src = rule.get('from')
                tx, ty = rule.get('to_x'), rule.get('to_y')
                res_keys = rule.get('res') or []
                reserve = int(rule.get('reserve') or 0)
                if src is None or tx is None or ty is None or not res_keys:
                    logging.info(f"↔️ Пропуск правила (неполные данные): {rule}")
                    continue

                # Переходим в деревню-донора СТРОГО по id.
                # FIX: раньше при нераспознанном доноре url был голым dorf1.php —
                # запасы читались из ТЕКУЩЕЙ активной деревни, и всё, что выше
                # резерва, уезжало не из той деревни (в логе — «успех»).
                vid = name_to_id.get(src)
                if not vid:
                    logging.warning(f"↔️ Донор '{src}' не найден среди деревень — правило пропущено.")
                    continue
                self.page.goto(f"{base}/dorf1.php?newdid={vid}")
                self.human_sleep(1.0, 2.0)

                # Контроль: после перехода активна именно деревня-донор.
                active = self._active_village_name()
                if active and not self._same_village(active, src):
                    logging.warning(
                        f"↔️ После перехода активна '{active}', а не донор '{src}' — правило пропущено."
                    )
                    continue

                cap = self.check_warehouse_capacity()
                amounts = {}
                for k in keys:
                    if k in res_keys:
                        cur = (cap.get(k) or [0, 0])[0]
                        amt = max(0, int(cur) - reserve)
                        if amt > 0:
                            amounts[k] = amt

                if not amounts:
                    logging.info(f"↔️ {src}→({tx}|{ty}): нечего слать (всё ниже резерва {reserve}).")
                    continue

                if self.send_resources(int(tx), int(ty), amounts):
                    sent += 1
                    self.human_sleep(1.0, 2.0)
            except Exception as e:
                logging.error(f"❌ Переброска, правило {rule}: {e}")
        logging.info(f"↔️ Переброска завершена. Успешно правил: {sent}/{len(rules or [])}")
        return sent

    def send_resources(self, target_x: int, target_y: int, resources: dict) -> bool:
        """
        Отправка ресурсов в другую деревню.

        Args:
            target_x, target_y: Координаты цели.
            resources: {'wood': 1000, 'clay': 500, 'iron': 0, 'crop': 0}
        """
        self.safe_goto(f"{self.config.base_url}/{self.LOCATORS['send_merchant']}")
        self.human_sleep(1.5, 2.5)
        try:
            self.page.locator('input[name="x"]').fill(str(target_x))
            self.page.locator('input[name="y"]').fill(str(target_y))

            res_map = {
                'wood': 'input[name="r1"]',
                'clay': 'input[name="r2"]',
                'iron': 'input[name="r3"]',
                'crop': 'input[name="r4"]',
            }
            for key, selector in res_map.items():
                val = resources.get(key, 0)
                if val > 0:
                    inp = self.page.locator(selector).first
                    if inp.is_visible():
                        inp.fill(str(val))
                        self.human_sleep(0.2, 0.5)

            submit = self.page.locator('#btn_ok, button[type="submit"].green').first
            if not (submit.is_visible() and submit.is_enabled()):
                logging.warning("⚠️ Кнопка отправки недоступна — ресурсы не отправлены.")
                return False
            try:
                submit_id = submit.get_attribute('id') or ''
            except Exception:
                submit_id = ''
            # FIX: результат human_click раньше терялся — непрокликнутая кнопка
            # считалась успехом.
            if not self.human_click(submit):
                logging.warning("⚠️ Не удалось нажать «Отправить» — ресурсы не отправлены.")
                return False
            self.human_sleep(1.0, 2.0)

            # FIX: в локаторе подтверждения стоял #btn_ok — на части серверов это
            # ТА ЖЕ кнопка отправки, и форма «подтверждала» сама себя (бот
            # рапортовал об отправке, не отправив ничего). Поэтому #btn_ok
            # принимаем как подтверждение только если отправляли НЕ им.
            confirm_sel = '#dialogContent button.green'
            if submit_id != 'btn_ok':
                confirm_sel += ', #btn_ok'
            confirm = self.page.locator(confirm_sel).first
            try:
                confirm.wait_for(state="visible", timeout=5000)
            except Exception:
                logging.warning(
                    f"⚠️ Диалог подтверждения не появился — отправка в ({target_x}|{target_y}) не выполнена."
                )
                return False
            if not self.human_click(confirm):
                logging.warning("⚠️ Не удалось подтвердить отправку.")
                return False
            logging.info(f"📦 Ресурсы отправлены в ({target_x}|{target_y}): {resources}")
            return True
        except Exception as e:
            logging.error(f"❌ Ошибка отправки: {e}")
        return False
