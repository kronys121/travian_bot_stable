import re
import json
import time
import random
import logging
from pathlib import Path
from urllib.parse import urljoin
from utils.base_action import BaseAction
from utils.locators import BUILD, DIALOG, HERO_INVENTORY, RES_ITEM_CLASS


class SmartBuilder(BaseAction):
    # Селекторы собираются из центрального реестра utils/locators.py.
    # Ключи сохранены для обратной совместимости с существующим кодом.
    LOCATORS = {
        **BUILD,
        'inventory_res_max': HERO_INVENTORY['res_max_btn'],
        'dialog_confirm': DIALOG['confirm'],
        'dialog_close': DIALOG['close'],
    }

    # сколько секунд крутится реклама перед начислением бонуса
    AD_WAIT_SECONDS = 40
    # сколько раз пробуем стройку через рекламу перед откатом на section1
    AD_MAX_ATTEMPTS = 3

    def __init__(self, page, config, tasks_action=None, settings_store=None):
        super().__init__(page, config)
        self.tasks_action = tasks_action
        self.settings_store = settings_store
        # Последняя зафиксированная нехватка ресурсов (dict или None)
        self._last_missing = None
        # Невыполненное требование постройки (строка или None)
        self._last_unmet_prereq = None
        # Строить через рекламу (section2, -25% времени). Управляется из настроек.
        self.use_ad_boost = True
        # Файл прогресса стройки: {village_key: step}
        from utils.paths import account_file
        acc = getattr(config, 'name', 'default')
        self._progress_path = account_file(acc, 'build_progress')
        self._history_path = account_file(acc, 'build_history')

    # --- ПРОГРЕСС (переживает перезапуск) --------------------------

    def _load_progress(self) -> dict:
        try:
            if self._progress_path.exists():
                return json.loads(self._progress_path.read_text(encoding="utf-8"))
        except Exception as e:
            logging.debug(f"build progress load error: {e}")
        return {}

    def get_saved_step(self, village_key: str) -> int:
        """С какого шага плана продолжать для этой деревни (1 = с начала)."""
        return int(self._load_progress().get(str(village_key), 1))

    def save_step(self, village_key: str, step: int):
        """Запоминает шаг, на котором остановилась стройка деревни."""
        try:
            data = self._load_progress()
            data[str(village_key)] = int(step)
            tmp = self._progress_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._progress_path)
        except Exception as e:
            logging.debug(f"build progress save error: {e}")

    def reset_progress(self, village_key: str = None):
        """
        Сбрасывает прогресс стройки на шаг 1.
        Если village_key указан — сбрасывает только эту деревню.
        Если None — сбрасывает прогресс по ВСЕМ деревням (весь файл удаляется).
        """
        try:
            if village_key is None:
                if self._progress_path.exists():
                    self._progress_path.unlink()
                    logging.info("Прогресс стройки сброшен для всех деревень.")
            else:
                data = self._load_progress()
                data.pop(str(village_key), None)
                tmp = self._progress_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self._progress_path)
                logging.info(f"Прогресс стройки сброшен для деревни {village_key}.")
        except Exception as e:
            logging.debug(f"reset_progress error: {e}")

    def log_history(self, village_key: str, building: str, level=None):
        """
        Пишет запись в build_history_<acc>.json — лог завершённых заказов
        стройки с временем. Хранит последние 200 записей.
        """
        try:
            from datetime import datetime
            hist_path = self._history_path
            history = []
            if hist_path.exists():
                try:
                    history = json.loads(hist_path.read_text(encoding="utf-8"))
                except Exception:
                    history = []
            history.append({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "village": str(village_key),
                "building": str(building),
                "level": level,
            })
            history = history[-200:]  # не растим файл бесконечно
            tmp = hist_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(hist_path)
        except Exception as e:
            logging.debug(f"build history save error: {e}")

    def _has_premium(self) -> bool:
        """
        Проверяет активен ли Travian Plus (= 2 слота очереди) по последнему
        stats_{name}.json. Если файл не найден или поле отсутствует — False
        (безопасно: ставим только 1 постройку).
        """
        try:
            from utils.paths import account_file
            acc = getattr(self.config, 'name', 'default')
            with open(account_file(acc, 'stats'), "r", encoding="utf-8") as f:
                data = json.load(f)
            return bool(data.get("account", {}).get("premium", False))
        except Exception:
            return False

    def _queue_limit(self) -> int:
        """Максимальный размер очереди стройки: 2 с Premium, 1 без."""
        return 2 if self._has_premium() else 1

    def is_queue_free(self) -> bool:
        """
        True если в очереди есть свободный слот.
        С Travian Plus очередь может содержать 2 постройки одновременно.
        """
        count = self.page.locator(self.LOCATORS['queue']).count()
        limit = self._queue_limit()
        free = count < limit
        logging.info(f"[build] Очередь: {count}/{limit} слотов занято — {'свободно' if free else 'занято'}.")
        return free

    def get_queue_finish_seconds(self) -> int | None:
        """
        Читает оставшееся время постройки из очереди стройки.
        Реальная структура DOM Travian:
            .buildDuration > span.timer[value=N]  — N = секунды до конца.
        Возвращает время ПЕРВОЙ (ближайшей) постройки — min.
        Когда она завершится, слот освободится и сразу ставим следующую.
        С Premium в очереди 2 здания — возвращаем min (первое освобождение).
        Без Premium одна постройка — min == max, разницы нет.
        """
        try:
            seconds = self.page.evaluate(r'''
                () => {
                    const timers = document.querySelectorAll(
                        '.buildDuration span.timer[value]'
                    );
                    const vals = [];
                    timers.forEach(t => {
                        const v = parseInt(t.getAttribute('value'), 10);
                        if (!isNaN(v)) vals.push(v);
                    });
                    if (vals.length === 0) return null;
                    return { min: Math.min(...vals), max: Math.max(...vals), count: vals.length };
                }
            ''')
            if not seconds:
                return None
            # Берём min — ближайшее освобождение слота.
            # Как только первая постройка завершится — сразу ставим следующую.
            s = int(seconds['min'])
            logging.info(
                f"[build] Очередь: {seconds['count']} шт., "
                f"первая заканчивается через {s}с ({s//60}м {s%60}с) "
                f"(вторая через {seconds['max']//60}м {seconds['max']%60}с)."
            )
            return s
        except Exception as e:
            logging.debug(f"get_queue_finish_seconds: {e}")
            return None

    def get_free_crop(self) -> int:
        """
        Свободное зерно (прокорм) деревни с главной страницы.
        Разметка stockBar: .granary.stockBarButton > #stockBarFreeCrop (значение).
        Значение может содержать юникод-символы направления текста
        (U+202D/U+202C), точки-разделители и юникод-минус — вычищаем.
        Возвращает большое число (10**9), если определить не удалось,
        чтобы НЕ блокировать стройку ложно.
        """
        try:
            # Проверка идёт на главной странице деревни
            if 'dorf1.php' not in self.page.url and 'dorf2.php' not in self.page.url:
                self.safe_goto(f"{self.config.base_url}/dorf1.php")
                self.human_sleep(0.8, 1.5)

            raw = self.page.evaluate(r'''
                () => {
                    // Основной путь: .granary.stockBarButton > #stockBarFreeCrop
                    let el = document.querySelector('.granary.stockBarButton #stockBarFreeCrop')
                          || document.querySelector('#stockBarFreeCrop')
                          || document.querySelector('.freeCrop_small .value, .freeCrop .value');
                    return el ? el.textContent : null;
                }
            ''')
            if raw is None:
                return 10 ** 9
            # заменяем юникод-минус на обычный, убираем всё кроме цифр и минуса
            cleaned = re.sub(r'[^\d-]', '', str(raw).replace('\u2212', '-'))
            if cleaned in ('', '-'):
                return 10 ** 9
            return int(cleaned)
        except Exception as e:
            logging.debug(f"free crop read error: {e}")
            return 10 ** 9

    def _get_required_crop(self) -> int:
        """
        Читает на открытой карточке здания потребление прокорма (свободное
        зерно населения), которое требует эта постройка.
        Структура DOM:
            <div class="inlineIcon resource">
                <i class="cropConsumptionBig"></i>
                <span class="value value">2</span>
            </div>
        Ищем именно тот .inlineIcon.resource, внутри которого есть
        <i class="cropConsumptionBig"> — это единственный надёжный признак.
        Возвращает -1 если не найдено.
        """
        try:
            raw = self.page.evaluate(r'''
                () => {
                    // Ищем блок .inlineIcon.resource который содержит cropConsumptionBig
                    const blocks = document.querySelectorAll('.inlineIcon.resource');
                    for (const b of blocks) {
                        if (!b.querySelector('i.cropConsumptionBig, .cropConsumptionBig'))
                            continue;
                        const val = b.querySelector('span.value.value')
                                 || b.querySelector('.value.value')
                                 || b.querySelector('.value');
                        if (val) return val.textContent;
                    }
                    return null;
                }
            ''')
            if raw is None:
                return -1
            cleaned = re.sub(r'[^\d-]', '', str(raw).replace('\u2212', '-'))
            if cleaned in ('', '-'):
                return -1
            return int(cleaned)
        except Exception as e:
            logging.debug(f"required crop read error: {e}")
            return -1

    def _get_transfer_needed(self) -> dict | None:
        """
        Читает на открытой карточке здания точную нехватку ресурсов из
        кнопок трансфера героя.

        Travian рендерит элементы .inlineIcon.resource.transfer только для
        тех ресурсов, которых не хватает. В атрибуте onclick каждой такой
        кнопки лежит targetResourceAmount со значениями для ВСЕХ 4 ресурсов:
            onclick="window.Travian.React.Hero.openResourceTransfer({
                targetResourceAmount: {lumber:165, clay:135, iron:50, crop:100},
                ...
            })"

        Возвращает dict {lumber, clay, iron, crop} если нехватка есть,
        None если кнопок трансфера нет (ресурсов хватает на постройку).
        """
        try:
            result = self.page.evaluate(r'''
                () => {
                    const btn = document.querySelector(
                        '.inlineIconList .inlineIcon.resource.transfer[onclick], ' +
                        '.resourceWrapper .inlineIcon.resource.transfer[onclick], ' +
                        '.inlineIcon.resource.transfer[onclick]'
                    );
                    if (!btn) return null;
                    const onclick = btn.getAttribute('onclick') || '';
                    // Вырываем JSON-объект targetResourceAmount из строки onclick.
                    const m = onclick.match(/targetResourceAmount\s*:\s*(\{[^}]+\})/);
                    if (!m) return { found: true, parsed: null };
                    try {
                        // Ключи в Travian без кавычек — eval-safe через Function
                        const obj = (new Function('return ' + m[1]))();
                        return { found: true, parsed: obj };
                    } catch(e) {
                        return { found: true, parsed: null };
                    }
                }
            ''')

            if result is None:
                # Нет кнопок трансфера — ресурсов хватает
                logging.info("[build] Кнопок трансфера нет — ресурсов достаточно.")
                return None

            if result.get('parsed'):
                needed = result['parsed']
                logging.info(
                    f"[build] Нехватка ресурсов (targetResourceAmount): "
                    f"lumber={needed.get('lumber',0)} clay={needed.get('clay',0)} "
                    f"iron={needed.get('iron',0)} crop={needed.get('crop',0)}"
                )
                return needed

            # Кнопка есть, но парсинг не удался — считаем что ресурсы нужны
            logging.info("[build] Кнопки трансфера найдены, targetResourceAmount не распарсить.")
            return {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}

        except Exception as e:
            logging.debug(f"_get_transfer_needed error: {e}")
            return None

    def _is_blocked_by_crop(self) -> bool:
        """
        Определяет ПРЯМО НА КАРТОЧКЕ ЗДАНИЯ, что постройка заблокирована
        нехваткой свободного зерна (а не обычных ресурсов):
          1) Travian пишет сообщение вида "мало продовольствия /
             расширьте фермы / crop supply";
          2) либо в контракте потребление зерна (иконка r5 / cropConsumption)
             больше текущего свободного зерна из stockBar.
        """
        try:
            info = self.page.evaluate(r'''
                () => {
                    const clean = (s) => parseInt((s || '').replace(/[^\d-]/g, ''), 10);

                    // Основной сигнал: блок апгрейда с сообщением об ошибке.
                    const blockEl = document.querySelector(
                        '.upgradeBlocked .errorMessage, #contract .upgradeBlocked .errorMessage'
                    );
                    const anyErr = document.querySelector(
                        '#contract .errorMessage, .upgradeBlocked, .errorMessage, .buildingWrapper .error'
                    );
                    const errText = ((blockEl || anyErr || {}).textContent || '').toLowerCase().trim();

                    const cropWords  = /(продовольст|фермы|расширьте|crop supply|cropland|freecrop|прокорм)/i;
                    // ВАЖНО: "ресурс/resource" включено — генеричная нехватка ресурсов
                    // НЕ является блокировкой по зерну!
                    const otherWords = /(древесин|дерев|глин|желез|склад|ресурс|wood|clay|iron|warehouse|resource)/i;

                    // Потребление зерна (upkeep) из контракта
                    let upkeepEl = null;
                    const resCandidates = document.querySelectorAll('.inlineIcon.resource');
                    for (const b of resCandidates) {
                        if (b.querySelector('i.cropConsumptionBig, .cropConsumptionBig')) {
                            upkeepEl = b.querySelector('span.value.value, .value.value, .value');
                            break;
                        }
                    }
                    if (!upkeepEl) {
                        upkeepEl = document.querySelector(
                            '#contract .inlineIcon.cropConsumption .value, ' +
                            '#contract .cropConsumption .value, ' +
                            '#contract i.r5 + .value, #contract .r5 ~ .value'
                        );
                    }
                    const freeEl = document.querySelector(
                        '.granary.stockBarButton #stockBarFreeCrop, #stockBarFreeCrop, ' +
                        '.freeCrop_small .value, .freeCrop .value'
                    );
                    const upkeep   = upkeepEl ? clean(upkeepEl.textContent) : null;
                    const freeCrop = freeEl ? clean(freeEl.textContent) : null;

                    // 1) Явное упоминание прокорма/продовольствия в ошибке
                    if (cropWords.test(errText)) {
                        return { blocked: true, rule: 1, errText, upkeep, freeCrop };
                    }

                    // 2) Числовая проверка: свободного зерна меньше чем потребление
                    if (upkeep !== null && freeCrop !== null &&
                        !isNaN(upkeep) && !isNaN(freeCrop) && freeCrop < upkeep) {
                        return { blocked: true, rule: 2, errText, upkeep, freeCrop };
                    }

                    // Правило 3 УДАЛЕНО: раньше "любая ошибка без слов дерево/глина/железо"
                    // считалась зерном — это давало ложные срабатывания на
                    // генеричном "Недостаточно ресурсов".
                    return { blocked: false, rule: 0, errText, upkeep, freeCrop };
                }
            ''')
            if info:
                logging.info(
                    f"[crop:debug] blocked={info.get('blocked')} rule={info.get('rule')} "
                    f"upkeep(потребление)={info.get('upkeep')} "
                    f"freeCrop(свободное зерно)={info.get('freeCrop')} "
                    f"errText='{(info.get('errText') or '')[:120]}'"
                )
            return bool(info and info.get('blocked'))
        except Exception as e:
            logging.debug(f"crop block check error: {e}")
            return False

    def _log_contract_resources(self, name: str, missing: dict | None = None):
        """
        Диагностика ресурсов на странице контракта здания:
        - стоимость (из #contract .resourceWrapper .value / .inlineIcon.resource)
        - текущие запасы (из stockBar)
        - что передано в missing (из transfer-кнопок)
        Также заполняет self._last_missing стоимостью из контракта, если
        transfer-кнопки не дали данных (missing пуст).
        """
        try:
            cost = self.page.evaluate(r'''
                () => {
                    const clean = (s) => parseInt((s || '').replace(/[^\d]/g, ''), 10) || 0;
                    const order = ['lumber', 'clay', 'iron', 'crop'];
                    const result = {};
                    // Стоимость: первые 4 .value в блоке ресурсов контракта
                    const scopes = ['#contract', '.upgradeBuilding', '.buildingWrapper', 'body'];
                    for (const scope of scopes) {
                        const root = document.querySelector(scope);
                        if (!root) continue;
                        const vals = root.querySelectorAll(
                            '.resourceWrapper .value, .resource .value, .inlineIcon.resource .value'
                        );
                        if (vals.length >= 4) {
                            order.forEach((r, i) => { result[r] = clean(vals[i].textContent); });
                            return result;
                        }
                    }
                    return null;
                }
            ''')
            current = self._read_current_resources()
            labels = [('lumber', 'дерево'), ('clay', 'глина'), ('iron', 'железо'), ('crop', 'зерно')]
            logging.warning(f"[res:debug] {name} — диагностика ресурсов:")
            logging.warning(f"[res:debug]   стоимость из контракта: {cost}")
            logging.warning(f"[res:debug]   текущие запасы (stockBar): {current}")
            logging.warning(f"[res:debug]   missing из transfer-кнопок: {missing}")
            if cost:
                for res, label in labels:
                    have = current.get(res, 0)
                    need = cost.get(res, 0)
                    diff = need - have
                    logging.warning(
                        f"[res:debug]   {label}: есть {have}, стоит {need}"
                        + (f" — НЕ ХВАТАЕТ {diff}" if diff > 0 else " — хватает")
                    )
                # Если transfer-кнопки пусты — используем стоимость из контракта
                if not missing or not any(v > 0 for v in missing.values()):
                    self._last_missing = dict(cost)
                    logging.warning(f"[res:debug]   _last_missing установлен из контракта: {cost}")
                else:
                    self._last_missing = missing
            elif missing:
                self._last_missing = missing
        except Exception as e:
            logging.debug(f"_log_contract_resources: {e}")

    def _upgrade_cropland(self) -> bool:
        """
        Апгрейд самого низкого поля-фермы (gid 4) для увеличения
        свободного зерна. Вызывается когда зерна не хватает на постройку.
        Возвращает True, если апгрейд поставлен в очередь.
        """
        logging.info("🌾 Мало свободного зерна — пробую улучшить ферму (Cropland).")
        self.safe_goto(f"{self.config.base_url}/dorf1.php")
        self.human_sleep(1.0, 2.0)

        # Ищем поле-ферму с минимальным уровнем, чтобы дешевле поднять зерно
        elements = self.page.locator(self.LOCATORS['fields']).all()
        crop_fields = []  # (level, href)
        for el in elements:
            try:
                if str(el.get_attribute('data-gid')) != '4':
                    continue
                href = el.get_attribute('href') or el.locator('a').first.get_attribute('href')
                lvl_txt = el.locator(self.LOCATORS['level_label']).first.text_content() or '0'
                lvl_m = re.search(r'\d+', lvl_txt)
                lvl = int(lvl_m.group()) if lvl_m else 0
                if href:
                    crop_fields.append((lvl, href))
            except Exception:
                continue

        if not crop_fields:
            logging.info("🌾 Поля-фермы не найдены.")
            return False

        crop_fields.sort(key=lambda x: x[0])  # самое низкое поле первым
        _, href = crop_fields[0]

        self.safe_goto(urljoin(self.page.url, href))
        self.human_sleep(1.0, 2.0)
        btn = self.page.locator(self.LOCATORS['upgrade_btn']).first
        try:
            if btn.is_visible() and btn.is_enabled() and 'disabled' not in (btn.get_attribute('class') or ''):
                self.human_click(btn, force=True)
                logging.info("🌾 Ферма отправлена на улучшение — зерно вырастет.")
                self.human_sleep(1.5, 2.5)
                return True
        except Exception as e:
            logging.debug(f"cropland upgrade error: {e}")
        logging.info("🌾 Улучшить ферму сейчас нельзя (нет ресурсов или очередь).")
        return False

    def _get_building_action(self, target_gid: str, target_lvl: int) -> tuple:
        elements = self.page.locator(self.LOCATORS['fields']).all()
        empty_slot_href = None
        existing_levels = []

        # --- debug: дамп всех найденных элементов ---
        logging.debug(
            f"[gba:debug] target_gid={target_gid} target_lvl={target_lvl} "
            f"selector='{self.LOCATORS['fields']}' found={len(elements)} elements "
            f"url={self.page.url!r}"
        )
        all_gids = []
        for _e in elements:
            _g = _e.get_attribute("data-gid") or "?"
            _a = _e.get_attribute("data-aid") or "?"
            all_gids.append(f"gid={_g}/aid={_a}")
        logging.debug(f"[gba:debug] elements: {all_gids}")
        # --- end debug ---

        for elem in elements:
            gid = elem.get_attribute("data-gid")
            aid = elem.get_attribute("data-aid")
            if not gid or not aid:
                continue

            slot_href = f"build.php?id={aid}"

            if gid == target_gid:
                raw_level = elem.locator(self.LOCATORS['level_label']).text_content() or "0"
                lvl_m = re.search(r'\d+', raw_level)
                lvl = int(lvl_m.group()) if lvl_m else 0

                # ВАЖНО: если слот уже строится (класс underConstruction),
                # считаем уровень с учётом очереди (+1). Иначе бот, пока идёт
                # стройка 5→6, видел уровень 5 и ставил ЛИШНИЙ апгрейд 6→7
                # во второй слот очереди (премиум позволяет 2 постройки).
                try:
                    elem_cls = elem.get_attribute('class') or ''
                    under_construction = (
                        'underConstruction' in elem_cls
                        or elem.locator('.underConstruction').count() > 0
                    )
                    if under_construction:
                        lvl += 1
                        logging.info(
                            f"⏳ Слот {slot_href} (gid {gid}) уже строится — "
                            f"эффективный уровень: {lvl}"
                        )
                except Exception:
                    logging.debug("suppressed error in services/smart_builder:570", exc_info=True)

                existing_levels.append((lvl, slot_href))

            if gid == "0" and not empty_slot_href:
                if aid not in ["39", "40"]:
                    empty_slot_href = slot_href

        if existing_levels:
            MULTIPLE_ALLOWED = ["10", "11", "23", "36"]
            is_resource_field = int(target_gid) <= 4

            if not is_resource_field and target_gid not in MULTIPLE_ALLOWED:
                highest_level = max(lvl for lvl, href in existing_levels)
                if highest_level >= target_lvl:
                    return ("done", None)
                else:
                    _, href = existing_levels[0]
                    return ("upgrade", href)

            elif is_resource_field:
                # Шаг плана "Woodcutters до 2" = ВСЕ поля этого типа должны быть >= target_lvl.
                # Шаг считается done только когда каждое поле уже на нужном уровне.
                # Апгрейдируем по одному за раз — то поле, которое ниже всех (round-robin),
                # чтобы поднимать все поля равномерно, а не одно до максимума.
                below_target = [(lvl, href) for lvl, href in existing_levels if lvl < target_lvl]
                if not below_target:
                    # все поля достигли цели
                    return ("done", None)
                # апгрейдируем поле с наименьшим уровнем (равномерный подъём)
                below_target.sort(key=lambda x: x[0])
                _, href = below_target[0]
                return ("upgrade", href)

            else:
                max_lvl = 10 if target_gid == "23" else 20
                existing_levels.sort(key=lambda x: x[0])
                non_maxed = [b for b in existing_levels if b[0] < max_lvl]

                if non_maxed:
                    active_lvl, active_href = non_maxed[0]
                    if active_lvl < target_lvl:
                        return ("upgrade", active_href)
                    else:
                        return ("done", None)
                else:
                    if target_lvl >= max_lvl:
                        return ("done", None)

        if target_gid == "16":
            logging.debug(f"[gba:debug] result=(build_new, build.php?id=39) [wall]")
            return ("build_new", "build.php?id=39")
        elif target_gid in ["31", "32", "33", "37", "38"]:
            # Определяем реальный gid стены по племени/DOM.
            real_wall_gid = self._detect_wall_gid() or target_gid
            if real_wall_gid != target_gid:
                logging.info(
                    f"[gba] Стена: в плане gid={target_gid}, "
                    f"реальный gid={real_wall_gid} — использую реальный."
                )
            # Стена уже построена — ищем её слот в DOM
            for elem in elements:
                gid = elem.get_attribute("data-gid")
                aid = elem.get_attribute("data-aid")
                if gid == real_wall_gid and aid:
                    href = f"build.php?id={aid}"
                    logging.debug(f"[gba:debug] result=(upgrade, {href}) [wall existing gid={gid}]")
                    return ("upgrade", href)
            # Стена ещё не построена — используем пустой слот, но с правильным gid
            if empty_slot_href:
                logging.debug(f"[gba:debug] result=(build_new, {empty_slot_href}, real_gid={real_wall_gid}) [wall new]")
                return ("build_new", empty_slot_href, real_wall_gid)
            logging.debug(f"[gba:debug] result=(build_new, build.php?id=40, gid={real_wall_gid}) [wall fallback]")
            return ("build_new", "build.php?id=40", real_wall_gid)
        elif empty_slot_href:
            logging.debug(f"[gba:debug] result=(build_new, {empty_slot_href}) [empty slot]")
            return ("build_new", empty_slot_href)

        logging.warning(
            f"[gba:debug] result=(full, None) — gid={target_gid} не найден и нет пустых слотов. "
            f"existing_levels={existing_levels} empty_slot_href={empty_slot_href}"
        )
        return ("full", None)

    def _construct_from_scratch(self, gid: str, section: str = "section1") -> bool:
        """
        Ищет карточку #contract_buildingN на странице пустого слота,
        проверяет ресурсы и нажимает нужную кнопку.

        DOM (из реального Travian):
          #contract_buildingN > .upgradeBuilding
            .upgradeButtonsContainer
              .section1 > button.textButtonV1.green.new        — обычная
              .section2 > button.textButtonV1.purple.new.videoFeatureButton — реклама
        Ресурсы нехватки: .inlineIcon.resource.transfer[onclick] -> targetResourceAmount
        """
        logging.info(f"[cfs] gid={gid} section={section} url={self.page.url!r}")

        tabs = self.page.locator(self.LOCATORS['tabs']).all()
        logging.info(f"[cfs] вкладок: {len(tabs)}")
        if not tabs:
            tabs = [None]

        for tab_idx, tab in enumerate(tabs):
            if tab:
                tab_text = (tab.text_content() or '').strip()
                logging.info(f"[cfs] вкладка [{tab_idx}]: '{tab_text}'")
                self.human_click(tab, force=True)
                self.human_sleep(1.0, 2.0)

            # Дамп всех contract_building* для диагностики
            all_contracts = self.page.evaluate(r'''
                () => {
                    return Array.from(
                        document.querySelectorAll('[id^="contract_building"]')
                    ).map(e => ({
                        id: e.id,
                        visible: e.offsetParent !== null,
                        greenBtn: (e.querySelector('.section1 button.green') || {}).className || null,
                        purpleBtn: (e.querySelector('.section2 button.purple') || {}).className || null,
                    }));
                }
            ''')
            logging.info(f"[cfs] tab={tab_idx} contracts={all_contracts}")

            card = self.page.locator(f'#contract_building{gid}').first
            if not card.is_visible():
                logging.info(f"[cfs] #contract_building{gid} не видна на вкладке {tab_idx}")
                continue

            logging.info(f"[cfs] #contract_building{gid} найдена на вкладке {tab_idx}")

            # Проверяем требования к постройке (prerequisites).
            # Невыполненное условие рендерится с классом "buildingCondition error":
            #   <span class="buildingCondition error"><a>Академия</a> <span>Уровень 10</span></span>
            # Выполненное — просто "buildingCondition" без error.
            unmet = card.evaluate(r'''
                (card) => {
                    const bad = card.querySelectorAll('.upgradeButtonsContainer .buildingCondition.error');
                    return Array.from(bad).map(el => (el.textContent || '').trim().replace(/\s+/g, ' '));
                }
            ''')
            if unmet:
                logging.warning(
                    f"[cfs] gid={gid}: не выполнены требования: {'; '.join(unmet)} — откладываем шаг."
                )
                self._last_unmet_prereq = '; '.join(unmet)
                return False
            self._last_unmet_prereq = None

            # Читаем стоимость постройки прямо из DOM карточки.
            # Travian рендерит .inlineIcon.resource[onclick] с targetResourceAmount
            # или .value внутри .resourceWrapper .resources.
            cost = card.evaluate(r'''
                (card) => {
                    const result = {};
                    const order = ['lumber','clay','iron','crop'];
                    // Способ 1: span.value внутри иконок ресурсов (индекс 0-3)
                    const vals = card.querySelectorAll('.resourceWrapper .value, .resources .value');
                    if (vals.length >= 4) {
                        order.forEach((r, i) => {
                            result[r] = parseInt((vals[i].textContent || '0').replace(/[^\d]/g,'')) || 0;
                        });
                        return result;
                    }
                    // Способ 2: data-cost атрибут кнопки
                    const btn = card.querySelector('button[data-cost]');
                    if (btn) {
                        try { return JSON.parse(btn.getAttribute('data-cost')); } catch(e) {}
                    }
                    return null;
                }
            ''')
            current = self._read_current_resources()
            logging.info(f"[cfs] стоимость постройки gid={gid}: {cost}")
            logging.info(f"[cfs] текущие ресурсы: {current}")
            if cost:
                short = {r: cost[r] - current.get(r, 0)
                         for r in self._RES_ORDER
                         if cost.get(r, 0) > current.get(r, 0)}
                if short:
                    logging.warning(f"[cfs] Не хватает: {short} — откладываем.")
                    self._last_missing = {r: cost.get(r, 0) for r in self._RES_ORDER}
                    return False
                logging.info(f"[cfs] Ресурсов хватает — строим.")

            # Выбираем кнопку в нужной секции
            # section1: button.textButtonV1.green.new
            # section2: button.textButtonV1.purple.new.videoFeatureButton
            if section == "section2":
                btn = card.locator('.section2 button.videoFeatureButton').first
            else:
                btn = card.locator('.section1 button.green.new').first

            btn_cls = btn.get_attribute('class') if btn.count() > 0 else 'NOT FOUND'
            logging.info(f"[cfs] btn section={section} visible={btn.is_visible()} cls={btn_cls!r}")

            if btn.count() == 0 or not btn.is_visible():
                logging.warning(f"[cfs] Кнопка section={section} не найдена.")
                return False

            btn_class = btn.get_attribute('class') or ''
            if 'disabled' in btn_class or not btn.is_enabled():
                logging.warning(f"[cfs] Кнопка заблокирована. cls={btn_class!r}")
                return False

            self.human_click(btn, force=True)
            logging.info(f"[cfs] Кнопка нажата — постройка запущена!")
            self._last_missing = None  # сбрасываем нехватку — постройка прошла
            return True

        logging.warning(f"[cfs] #contract_building{gid} не найдена ни в одной вкладке.")
        return False

    # Порядок resourceRowBody совпадает с порядком ресурсов в Travian:
    # 0=lumber, 1=clay, 2=iron, 3=crop
    _RES_ORDER = ['lumber', 'clay', 'iron', 'crop']

    # Маппинг gid стены по племени
    _WALL_GID_BY_TRIBE = {
        'roman':    '32',  # City Wall
        'teuton':   '31',  # Earth Wall
        'gaul':     '33',  # Palisade
        'egyptians':'38',  # Stone Wall
        'huns':     '37',  # Makeshift Wall
    }

    def _detect_wall_gid(self) -> str | None:
        """
        Определяет gid стены двумя способами:
        1. По DOM на dorf2 — ищет какой из [31,32,33,37,38] уже построен (data-gid != 0).
        2. По племени из settings_store (farm.tribe или tribe).
        Возвращает строку gid или None если не удалось определить.
        """
        # Способ 1: DOM — стена уже построена
        try:
            wall_gids = ['31', '32', '33', '37', '38']
            for elem in self.page.locator('[data-aid][data-gid]').all():
                g = elem.get_attribute('data-gid')
                if g in wall_gids:
                    logging.info(f"[wall] Стена определена по DOM: gid={g}")
                    return g
        except Exception:
            logging.debug("suppressed error in services/smart_builder:813", exc_info=True)

        # Способ 2: по племени из настроек
        try:
            settings = getattr(self, 'settings_store', None)
            if settings:
                tribe = (
                    settings.section('farm').get('tribe')
                    or settings.get_all().get('tribe', '')
                ).lower()
            else:
                # Читаем из config если нет settings_store
                tribe = getattr(self.config, 'tribe', '').lower()
            gid = self._WALL_GID_BY_TRIBE.get(tribe)
            if gid:
                logging.info(f"[wall] Стена определена по племени '{tribe}': gid={gid}")
                return gid
        except Exception:
            logging.debug("suppressed error in services/smart_builder:831", exc_info=True)

        logging.warning("[wall] Не удалось определить gid стены — используем gid из плана.")
        return None

    def _read_current_resources(self) -> dict:
        """
        Читает текущие ресурсы деревни из stockbar.
        Возвращает dict {lumber, clay, iron, crop} -> int.
        Ключ 'lumber' соответствует 'wood' в stats_collector (l1).
        """
        try:
            raw = self.page.evaluate(r'''
                () => {
                    const num = t => {
                        if (t == null) return 0;
                        const s = String(t)
                            .replace(/[\u202C\u202D\u200E\u200F\u200B\uFEFF\u00A0\s,.]/g, '')
                            .replace(/\u2212/g, '-');
                        const m = s.match(/-?\d+/);
                        return m ? parseInt(m[0], 10) : 0;
                    };
                    const stockSel = i => (
                        document.getElementById('l' + i) ||
                        document.querySelector('#stockBarResource' + i + ' .value') ||
                        document.querySelector('.stockBarButton:nth-of-type(' + i + ') .value')
                    );
                    return {
                        lumber: num(stockSel(1)?.textContent),
                        clay:   num(stockSel(2)?.textContent),
                        iron:   num(stockSel(3)?.textContent),
                        crop:   num(stockSel(4)?.textContent),
                    };
                }
            ''')
            return raw if raw else {'lumber': 0, 'clay': 0, 'iron': 0, 'crop': 0}
        except Exception as e:
            logging.debug(f"_read_current_resources: {e}")
            return {'lumber': 0, 'clay': 0, 'iron': 0, 'crop': 0}

    def _use_inventory_resources(self, needed: dict | None = None) -> bool:
        """
        Переносит ресурсы из инвентаря героя в деревню.

        needed: dict с ключами lumber/clay/iron/crop и количеством нехватки,
                или None — тогда жмём глобальный максимум по всем ресурсам.

        Логика:
        - Если needed=None или нехватают все 4 ресурса — жмём глобальный
          fillup (.actionButton button:nth-child(1)) как раньше.
        - Если нехватают только отдельные ресурсы — открываем диалог,
          для каждого нужного resourceRowBody нажимаем fillup строки
          (textButtonV2.buttonFramed.fillup) чтобы взять максимум именно
          этого ресурса, остальные строки не трогаем, затем жмём подтверждение
          (.actionButton .textButtonV2.withLoadingIndicator).
        """
        logging.info("Проверка ресурсов в инвентаре героя...")
        logging.debug(
            f"[inv:debug] _use_inventory_resources вызван: "
            f"needed={needed!r} "
            f"self._last_missing={getattr(self, '_last_missing', 'NOT SET')!r}"
        )
        try:
            self.safe_goto(f"{self.config.base_url}/hero/inventory")
            self.human_sleep(2.0, 3.0)

            # Определяем какие ресурсы нужны
            needed_keys: set[str] = set()
            if needed:
                needed_keys = {k for k, v in needed.items() if isinstance(v, (int, float)) and v > 0}
            use_global_max = (not needed_keys) or (needed_keys == set(self._RES_ORDER))
            logging.debug(
                f"[inv:debug] needed_keys={needed_keys!r} "
                f"use_global_max={use_global_max} "
                f"RES_ORDER={self._RES_ORDER!r}"
            )

            # Точный перенос: по каждому нужному ресурсу — свой диалог
            if not use_global_max:
                return self._transfer_resources_exact(needed, needed_keys)

            # Находим любой ресурсный ящик чтобы открыть диалог
            resource_classes = ['item145', 'item146', 'item147', 'item148']
            item_to_click = None
            for res_class in resource_classes:
                item = self.page.locator(f'.heroItems .item.{res_class}').first
                if item.is_visible():
                    item_to_click = item
                    break

            if not item_to_click:
                logging.info("Ресурсных ящиков не найдено.")
                return False

            self.human_click(item_to_click, force=True)

            try:
                # Ждём появления диалога
                self.page.wait_for_selector('.resourceRowBody', timeout=5000)
                self.human_sleep(0.5, 1.0)

                # --- Глобальный максимум (нехватка всех 4 или needed=None) ---
                res_max_btn = self.page.locator(self.LOCATORS['inventory_res_max']).first
                max_btn_class = res_max_btn.get_attribute('class') or ''
                if 'disabled' in max_btn_class:
                    logging.warning("Кнопка 'Максимум' заблокирована (склад полон или герой недоступен).")
                    self._close_dialog()
                    return False
                self.human_click(res_max_btn, force=True)
                logging.info("Выбран глобальный максимум ресурсов.")
                self.human_sleep(0.8, 1.5)
                return self._confirm_transfer_dialog()

            except Exception as e:
                logging.warning(f"Ошибка при взаимодействии с диалогом ресурсов: {e}")
            return False
        except Exception as e:
            logging.error(f"Ошибка инвентаря: {e}")
            return False

    # Ящики ресурсов в инвентаре героя: класс предмета по имени ресурса
    # Ящики ресурсов в инвентаре героя — из центрального реестра локаторов
    _RES_ITEM_CLASS = RES_ITEM_CLASS

    def _transfer_resources_exact(self, needed: dict, needed_keys: set) -> bool:
        """
        Переносит ресурсы ПО ОДНОМУ: для каждого нужного ресурса кликает
        по ЕГО ящику в инвентаре (item145..item148), в открывшемся диалоге
        вводит точное количество в input и подтверждает. Повторяет для
        каждого нужного ресурса.
        """
        transferred = []
        for res_name in self._RES_ORDER:
            if res_name not in needed_keys:
                continue
            need_amount = int(needed.get(res_name, 0))
            if need_amount <= 0:
                continue

            item_class = self._RES_ITEM_CLASS[res_name]
            item = self.page.locator(f'.heroItems .item.{item_class}').first
            try:
                if not item.is_visible():
                    logging.info(f"[inv] {res_name}: ящика {item_class} нет в инвентаре — пропускаю.")
                    continue
            except Exception:
                continue

            # Открываем диалог именно этого ресурса
            self.human_click(item, force=True)
            try:
                self.page.wait_for_selector('.resourceRowBody', timeout=5000)
            except Exception:
                logging.warning(f"[inv] {res_name}: диалог не открылся.")
                continue
            self.human_sleep(0.5, 1.0)

            row = self.page.locator('.resourceRowBody').first

            # Сколько доступно у героя
            available = 0
            try:
                raw = row.locator('.count').first.text_content() or '0'
                available = int(re.sub(r'[^\d]', '', raw) or '0')
            except Exception:
                logging.debug("suppressed error in services/smart_builder:1000", exc_info=True)

            amount = min(need_amount, available)
            logging.info(
                f"[inv] {res_name}: нужно {need_amount}, у героя {available} — "
                f"переношу {amount}."
            )
            if amount <= 0:
                self._close_dialog()
                self.human_sleep(0.5, 1.0)
                continue

            # Вводим количество в поле ввода
            inp = row.locator('.resourceInput.formV2 input, .resourceInput input, input[type="text"], input[type="number"]').first
            filled_ok = False
            try:
                if inp.count() > 0 and inp.is_visible():
                    inp.fill(str(amount))
                    self.human_sleep(0.3, 0.6)
                    filled_ok = True
                    logging.info(f"[inv] {res_name}: ввёл {amount} в поле ввода.")
            except Exception as e:
                logging.debug(f"[inv] {res_name}: ошибка ввода: {e}")

            if not filled_ok:
                # Поля нет — fallback на fillup строки (возьмёт максимум ресурса)
                fillup = row.locator('button.textButtonV2.buttonFramed.fillup').first
                try:
                    if fillup.count() > 0 and 'disabled' not in (fillup.get_attribute('class') or ''):
                        self.human_click(fillup, force=True)
                        self.human_sleep(0.3, 0.6)
                        filled_ok = True
                        logging.info(f"[inv] {res_name}: поля ввода нет — нажал fillup.")
                except Exception:
                    logging.debug("suppressed error in services/smart_builder:1034", exc_info=True)

            if not filled_ok:
                logging.warning(f"[inv] {res_name}: не смог указать количество — закрываю диалог.")
                self._close_dialog()
                self.human_sleep(0.5, 1.0)
                continue

            # Подтверждаем перенос этого ресурса
            if self._confirm_transfer_dialog():
                transferred.append(res_name)
            self.human_sleep(0.8, 1.5)

        if transferred:
            logging.info(f"[inv] Перенесены ресурсы: {', '.join(transferred)}.")
            return True
        logging.info("[inv] Ничего не перенесено.")
        return False

    def _confirm_transfer_dialog(self) -> bool:
        """Нажимает кнопку подтверждения в открытом диалоге переноса ресурсов."""
        confirm_selectors = [
            '.actionButton .textButtonV2.withLoadingIndicator',
            '.actionButton button:nth-child(2)',
            self.LOCATORS['dialog_confirm'],
            '#dialogContent button[type="submit"], .dialogVisible button[type="submit"]',
            'button[value="ok"], button[value="OK"]',
        ]
        confirm_btn = None
        deadline = time.time() + 4
        while time.time() < deadline and confirm_btn is None:
            for sel in confirm_selectors:
                loc = self.page.locator(sel).first
                try:
                    if loc.is_visible():
                        confirm_btn = loc
                        break
                except Exception:
                    continue
            if confirm_btn is None:
                self.human_sleep(0.4, 0.7)

        if confirm_btn is not None:
            confirm_class = confirm_btn.get_attribute('class') or ''
            if 'disabled' in confirm_class:
                logging.warning("Кнопка подтверждения заблокирована.")
                self._close_dialog()
                return False
            self.human_click(confirm_btn, force=True)
            logging.info("Ресурсы перенесены.")
            self.human_sleep(1.5, 2.5)
            return True

        # Нет кнопки — возможно диалог закрылся автоматически
        try:
            still_open = self.page.locator('.resourceRowBody').first.is_visible()
        except Exception:
            still_open = False
        if not still_open:
            logging.info("Ресурсы перенесены (диалог закрылся автоматически).")
            self.human_sleep(1.0, 1.8)
            return True

        logging.warning("Не нашёл кнопку подтверждения переноса ресурсов.")
        self._close_dialog()
        return False

    def _close_dialog(self):
        """Закрывает открытый диалог если есть кнопка закрытия."""
        try:
            close_btn = self.page.locator(self.LOCATORS['dialog_close']).first
            if close_btn.is_visible():
                self.human_click(close_btn, force=True)
        except Exception:
            logging.debug("suppressed error in services/smart_builder:1108", exc_info=True)

    # --- СТРОЙКА ЧЕРЕЗ РЕКЛАМУ (section2, -25% времени) ------------

    def _handle_ad_consent(self):
        """
        При ПЕРВОМ просмотре рекламы Travian показывает окно согласия внутри iframe:
        контейнер .buttonWrapper.formV2 c чекбоксом .checkbox — ставим галку,
        затем жмём кнопку .textButtonV2.buttonFramed.dialogButtonOk.rectangle.withText.green.
        Используем _find_in_frames чтобы найти элементы в любом iframe на странице.
        """
        try:
            checkbox_loc, where = self._find_in_frames(
                self.LOCATORS['ad_consent_checkbox'], timeout_ms=4000
            )
            if checkbox_loc is None:
                return  # окно согласия не появилось — пропускаем

            logging.info(f"☑️ Обнаружено окно согласия на рекламу ({where}), принимаю...")
            try:
                checkbox_loc.click(force=True)
            except Exception:
                checkbox_loc.dispatch_event("click")
            self.human_sleep(0.4, 0.8)

            ok_loc, _ = self._find_in_frames(
                self.LOCATORS['ad_consent_ok'], timeout_ms=3000
            )
            if ok_loc is not None:
                try:
                    ok_loc.click(force=True)
                except Exception:
                    ok_loc.dispatch_event("click")
                logging.info("✅ Окно согласия закрыто.")
                self.human_sleep(0.8, 1.5)
        except Exception as e:
            logging.debug(f"ad consent check: {e}")

    def _wait_for_ad(self):
        """
        Ждёт прокрутку рекламы (~AD_WAIT_SECONDS). После рекламы иногда
        остаётся кнопка получения/закрытия бонуса — пробуем её нажать.
        """
        secs = self.AD_WAIT_SECONDS
        logging.info(f"⏳ Смотрю рекламу (~{secs}с)...")
        self.human_sleep(secs, secs + 6)
        # закрыть/подтвердить пост-рекламный диалог, если появился
        for sel in [
            self.LOCATORS['ad_consent_ok'],
            '#dialogButtonOk', '.dialogButtonOk',
            self.LOCATORS['dialog_confirm'],
        ]:
            try:
                b = self.page.locator(sel).first
                if b.is_visible():
                    self.human_click(b, force=True)
                    self.human_sleep(0.5, 1.0)
                    break
            except Exception:
                continue

        # Страховка: если плеер завис и всё ещё на экране — закрываем его.
        try:
            player_visible = self.page.evaluate(r'''
                () => {
                    const p = document.querySelector('[id^="player"], .atg-gima-video-container');
                    return p && p.offsetParent !== null;
                }
            ''')
            if player_visible:
                logging.warning("[ad] Плеер всё ещё открыт после ожидания — закрываю принудительно.")
                # Пробуем кнопки закрытия, потом Escape
                for close_sel in ['.atg-gima-close-button', '[class*="close"]', 'button[aria-label="Close"]']:
                    try:
                        c = self.page.locator(close_sel).first
                        if c.is_visible():
                            self.human_click(c, force=True)
                            self.human_sleep(0.5, 1.0)
                            break
                    except Exception:
                        continue
                self.page.keyboard.press('Escape')
                self.human_sleep(0.5, 1.0)
        except Exception as e:
            logging.debug(f"ad player cleanup: {e}")

    def _open_building_contract(self, gid: str) -> bool:
        """
        Открывает карточку чертежа здания (#contract_building{gid}), перебирая
        вкладки постройки. Нужно, чтобы стала видна кнопка видео-рекламы
        для постройки нового здания через section2.
        """
        tabs = self.page.locator(self.LOCATORS['tabs']).all() or [None]
        for tab in tabs:
            if tab:
                self.human_click(tab, force=True)
                self.human_sleep(1.0, 2.0)
            if self.page.locator(f'#contract_building{gid}').first.is_visible():
                return True
        return False

    def _find_in_frames(self, selector: str, timeout_ms: int = 15000):
        """
        Ищет элемент по селектору на главной странице И во всех iframe.
        Рекламный плеер (GIMA) обычно рендерится внутри iframe, поэтому
        обычный page.locator его не видит. Возвращает (locator, where) или (None, None).
        """
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            # 1) главная страница
            try:
                loc = self.page.locator(selector).first
                if self.page.locator(selector).count() > 0 and loc.is_visible():
                    return loc, "page"
            except Exception:
                logging.debug("suppressed error in services/smart_builder:1223", exc_info=True)

            # 2) все фреймы
            try:
                for fr in self.page.frames:
                    if fr == self.page.main_frame:
                        continue
                    try:
                        if fr.locator(selector).count() > 0:
                            loc = fr.locator(selector).first
                            if loc.is_visible():
                                return loc, f"frame:{fr.url[:60]}"
                    except Exception:
                        continue
            except Exception:
                logging.debug("suppressed error in services/smart_builder:1238", exc_info=True)

            time.sleep(0.5)
        return None, None

    def _click_video_feature_btn(self, gid: str | None = None) -> bool:
        """
        Жмёт фиолетовую кнопку запуска видео-рекламы (videoFeatureButton)
        внутри section2. Если передан gid — ищет кнопку внутри #contract_buildingN
        (для build_new), иначе глобально по странице (для upgrade).
        """
        try:
            if gid:
                # build_new: кнопка внутри карточки конкретного здания
                card = self.page.locator(f'#contract_building{gid}').first
                btn = card.locator(self.LOCATORS['ad_video_btn']).first
            else:
                # upgrade: кнопка глобально на странице здания
                btn = self.page.locator(self.LOCATORS['ad_video_btn']).first
            btn_cls = btn.get_attribute('class') if btn.count() > 0 else 'NOT FOUND'
            logging.info(f"[ad] videoFeatureButton gid={gid} cls={btn_cls!r} visible={btn.is_visible()}")
            if not (btn.is_visible() and 'disabled' not in (btn.get_attribute('class') or '')):
                return False
            self.human_click(btn, force=True)
            logging.info("Нажал кнопку видео-рекламы (videoFeatureButton).")
        except Exception as e:
            logging.debug(f"video feature button click error: {e}")
            return False

        self.human_sleep(1.5, 2.5)

        # ждём появления кнопки воспроизведения (в т.ч. внутри iframe) и жмём её
        play_loc, _ = self._find_in_frames(self.LOCATORS['ad_play_btn'], timeout_ms=15000)
        if play_loc is not None:
            try:
                self.human_sleep(0.5, 1.2)
                play_loc.click(force=True)
                logging.info("▶️ Запустил воспроизведение видео.")
            except Exception as e:
                logging.debug(f"big-play click failed: {e}")

        # иногда основная кнопка не запускает видео — пробуем запасную (в контролбаре)
        try:
            self.human_sleep(1.0, 2.0)
            small_loc, _ = self._find_in_frames(self.LOCATORS['ad_play_btn_small'], timeout_ms=8000)
            if small_loc is not None:
                small_loc.click(force=True)
                logging.info("▶️ Нажал запасную кнопку воспроизведения.")
        except Exception as e:
            logging.debug(f"small play button error: {e}")

        # отключаем звук рекламы
        try:
            self.human_sleep(1.0, 2.0)
            mute_loc, _ = self._find_in_frames(self.LOCATORS['ad_mute_btn'], timeout_ms=8000)
            if mute_loc is not None:
                mute_loc.click(force=True)
                logging.info("🔇 Отключил звук рекламы.")
        except Exception as e:
            logging.debug(f"mute button error: {e}")
        return True

    def _click_section(self, section: str, gid: str, action: str) -> bool:
        """
        Кликает кнопку стройки/апгрейда в конкретной секции карточки:
        section1 — обычная (зелёная кнопка),
        section2 — с рекламой: жмём фиолетовую videoFeatureButton (-25% времени).
        """
        # section2: для любого действия (апгрейд/новое здание) триггер — фиолетовая
        # кнопка видео-рекламы. Для build_new сначала открываем карточку чертежа.
        if section == "section2":
            if action == "build_new":
                # переключаемся на вкладку с нужной карточкой
                self._open_building_contract(gid)
                # gid передаём чтобы кнопка искалась внутри #contract_buildingN
                return self._click_video_feature_btn(gid=gid)
            # upgrade: кнопка находится глобально на странице здания
            return self._click_video_feature_btn(gid=None)

        # section1: обычная стройка
        if action == "upgrade":
            btn = self.page.locator(self.LOCATORS['upgrade_btn']).first
            try:
                if btn.is_visible() and btn.is_enabled() and 'disabled' not in (btn.get_attribute('class') or ''):
                    self.human_click(btn, force=True)
                    return True
            except Exception as e:
                logging.debug(f"{section} upgrade click: {e}")
            return False
        elif action == "build_new":
            return self._construct_from_scratch(gid, section=section)
        return False

    def _construction_started(self, location: str, queue_before: int) -> bool:
        """
        Проверяет, что после рекламы стройка реально попала в очередь:
        перезаходит на страницу деревни и сравнивает длину очереди с той,
        что была до клика. Если очередь выросла — стройка началась.
        """
        try:
            self.safe_goto(f"{self.config.base_url}/{location}")
            self.human_sleep(1.0, 2.0)
            queue_after = self.page.locator(self.LOCATORS['queue']).count()
            logging.info(f"🔎 Очередь стройки: было {queue_before}, стало {queue_after}.")
            return queue_after > queue_before
        except Exception as e:
            logging.debug(f"construction started check: {e}")
            return False

    def _build_via_ad_or_fallback(self, gid: str, action: str, slot_url_part: str, location: str) -> bool:
        """
        Строит/улучшает здание через рекламу (section2, -25% времени постройки).

        Логика:
          1. До AD_MAX_ATTEMPTS попыток: клик по section2 → окно согласия →
             ждём прокрутку рекламы → проверяем, началась ли стройка.
          2. Если реклама так и не сработала — откат на обычную стройку (section1).

        Возвращает True, если здание поставлено в очередь любым способом.
        """
        for attempt in range(1, self.AD_MAX_ATTEMPTS + 1):
            # длина очереди ДО клика (замер на странице деревни)
            self.safe_goto(f"{self.config.base_url}/{location}")
            self.human_sleep(0.8, 1.5)
            queue_before = self.page.locator(self.LOCATORS['queue']).count()

            # открываем карточку здания
            self.safe_goto(urljoin(self.page.url, slot_url_part))
            self.human_sleep(1.0, 2.0)

            logging.info(f"📺 Стройка через рекламу (section2), попытка {attempt}/{self.AD_MAX_ATTEMPTS}...")
            if not self._click_section("section2", gid, action):
                logging.warning("⚠️ Кнопка section2 недоступна — перехожу на обычную стройку.")
                break

            self._handle_ad_consent()
            self._wait_for_ad()

            if self._construction_started(location, queue_before):
                logging.info("✅ Стройка через рекламу запущена (-25% времени постройки)!")
                return True
            logging.warning(f"⚠️ После рекламы стройка не началась (попытка {attempt}/{self.AD_MAX_ATTEMPTS}).")

        # реклама не сработала — строим обычным способом (section1)
        logging.info("↩️ Реклама не сработала — строю обычным способом (section1).")
        self.safe_goto(urljoin(self.page.url, slot_url_part))
        self.human_sleep(1.0, 2.0)
        return self._click_section("section1", gid, action)

    def execute_plan(self, build_plan: list, start_step: int = None, village_key: str = None) -> int | None:
        """
        НЕБЛОКИРУЮЩИЙ режим стройки.
        Бот проверяет здания по списку. Если построить прямо сейчас нельзя
        (очередь забита или нет ресов) - выходит из функции, чтобы карусель крутилась дальше.

        Прогресс сохраняется в build_progress_{acc}.json по каждой деревне:
        при перезапуске бот продолжает с того шага, где остановился,
        а не проходит весь план с начала.
        start_step, переданный явно, имеет приоритет над сохранённым.

        Возвращает:
            int  — секунды до окончания текущей постройки (очередь занята);
                   вызывающий код может передать это значение в scheduler.set_next_run.
            None — постройка поставлена / нет ресурсов / план завершён.
        """
        # Автоподхват сохранённого шага, если не задан явно
        if start_step is None:
            start_step = self.get_saved_step(village_key) if village_key else 1
            if start_step > 1:
                logging.info(f"💾 Продолжаю стройку с сохранённого шага {start_step}.")

        logging.info(f"Анализ плана постройки (начиная с шага {start_step})...")

        if start_step < 1 or start_step > len(build_plan):
            start_step = 1

        plan_to_execute = build_plan[start_step - 1:]

        def remember(step):
            if village_key:
                self.save_step(village_key, step)

        try:
            for step_idx, task in enumerate(plan_to_execute, start_step):
                location = task.location if hasattr(task, 'location') else task['location']
                gid = str(task.gid if hasattr(task, 'gid') else task['gid'])
                name = task.name if hasattr(task, 'name') else task['name']
                target_level = task.target_level if hasattr(task, 'target_level') else task['target_level']

                # Заходим в нужную локацию (поля или центр деревни)
                self.safe_goto(f"{self.config.base_url}/{location}")
                self.human_sleep(1.0, 2.0)

                # Проверяем статус здания
                # Для стен возвращается 3-tuple (action, url, real_gid)
                _result = self._get_building_action(gid, target_level)
                if len(_result) == 3:
                    action, slot_url_part, gid = _result  # перезаписываем gid реальным
                else:
                    action, slot_url_part = _result

                if action == "done" or not slot_url_part:
                    # Если уже построено - запоминаем прогресс и идем дальше,
                    # чтобы при перезапуске не перепроверять готовые шаги
                    logging.info(f"✅ [{step_idx}/{len(build_plan)}] {name} уже на уровне {target_level}.")
                    remember(step_idx + 1)
                    continue

                # ==========================================
                # МЫ НАШЛИ ЗДАНИЕ, КОТОРОЕ НУЖНО ПОСТРОИТЬ
                # ==========================================
                logging.info(f"🎯 Наша текущая цель: [{step_idx}/{len(build_plan)}] {name} (до {target_level} ур.)")

                # 1. Проверяем очередь
                if not self.is_queue_free():
                    secs = self.get_queue_finish_seconds()
                    if secs is not None:
                        logging.info(
                            f"⏳ Очередь занята. Следующая постройка освободится через "
                            f"~{secs}с ({int(secs/60)}м {secs%60}с). Передаю время планировщику."
                        )
                    else:
                        logging.info("⏳ Очередь постройки занята. Перехожу к следующей деревне.")
                    remember(step_idx)  # при перезапуске продолжим с этого же шага
                    return secs  # ВЫХОД: планировщик поставит следующий запуск ровно на это время

                # 2. Пытаемся построить
                def attempt_build():
                    self._last_unmet_prereq = None
                    full_slot_url = urljoin(self.page.url, slot_url_part)
                    self.safe_goto(full_slot_url)
                    self.human_sleep(1.0, 2.5)

                    # Для build_new кнопка upgrade отсутствует на странице пустого
                    # слота — она появится только внутри #contract_buildingN после
                    # выбора здания. Проверку кнопки делаем только для upgrade.
                    if action == "upgrade":
                        btn_state = self.page.evaluate(r'''
                            () => {
                                const btn = document.querySelector(
                                    'button.textButtonV1.green.build, ' +
                                    'button.green.build, ' +
                                    'button[class*="section1"][class*="build"], ' +
                                    'button[class*="upgradeButton"]'
                                );
                                if (!btn) return { found: false };
                                const cls = btn.className || '';
                                const lacking = btn.disabled
                                    || cls.includes('disabled')
                                    || cls.includes('notNow');
                                return { found: true, cls, disabled: btn.disabled, lacking };
                            }
                        ''')
                        if not btn_state.get('found'):
                            logging.warning(f"[build] {name}: кнопка апгрейда не найдена.")
                            self._log_contract_resources(name)
                            return False
                        if btn_state.get('lacking'):
                            # Кнопка неактивна — нехватка ресурсов.
                            _missing = self._get_transfer_needed()
                            last_missing['value'] = _missing
                            self._log_contract_resources(name, _missing)
                            return False

                    # Стройка через рекламу (section2, -25% времени) с откатом
                    # на обычную (section1) после 3 неудачных попыток.
                    if self.use_ad_boost:
                        return self._build_via_ad_or_fallback(gid, action, slot_url_part, location)

                    # Обычная стройка (реклама выключена в настройках)
                    if action == "upgrade":
                        btn = self.page.locator(self.LOCATORS['upgrade_btn']).first
                        if btn.is_visible() and btn.is_enabled() and 'disabled' not in (
                                btn.get_attribute('class') or ''):
                            self.human_click(btn, force=True)
                            return True
                    elif action == "build_new":
                        return self._construct_from_scratch(gid)
                    return False

                # Попытка №1
                success = attempt_build()

                if success:
                    logging.info(f"🚀 Здание {name} успешно поставлено в очередь!")
                    self._last_missing = None
                    self.log_history(village_key or 'default', name, target_level)
                    remember(step_idx)
                    self.human_sleep(1.5, 2.5)
                    # С Premium может быть ещё один свободный слот — проверяем
                    # не выходя из цикла, чтобы сразу поставить вторую постройку.
                    if self.is_queue_free():
                        logging.info(f"[build] Второй слот свободен — продолжаю план.")
                        continue
                    # Оба слота заняты — возвращаем время до ближайшего освобождения.
                    return self.get_queue_finish_seconds()

                else:
                    # Требования не выполнены (например, нужна Академия 10 ур.,
                    # которая ещё строится) — ресурсы тут ни при чём. Просто
                    # откладываем шаг до конца текущей стройки.
                    if getattr(self, '_last_unmet_prereq', None):
                        logging.info(
                            f"⏸️ {name}: жду требования '{self._last_unmet_prereq}' — "
                            f"вернусь после завершения текущей стройки."
                        )
                        self._last_unmet_prereq = None
                        return self.get_queue_finish_seconds()

                    # Проверяем блокировку по свободному зерну (прокорм населения).
                    # _is_blocked_by_crop() читает freeCrop и cropConsumptionBig —
                    # это НЕ то же самое что зерно в targetResourceAmount.
                    if self._is_blocked_by_crop():
                        logging.warning(
                            f"⚠️ {name}: блокировка по свободному зерну. "
                            f"Улучшаю самую дешёвую ферму."
                        )
                        if self._upgrade_cropland():
                            remember(step_idx)  # остаёмся на этом шаге
                            self.human_sleep(1.5, 2.5)
                            return self.get_queue_finish_seconds()
                        # ферму улучшить не вышло (нет ресурсов на ферму) —
                        # тогда пробуем пополнить ресурсы обычным путём ниже

                    logging.warning(f"⚠️ Не хватает ресурсов для {name}. Пробую пополнить...")
                    found_extra = False

                    # Пытаемся собрать награды за задания
                    if self.tasks_action and self.tasks_action.collect_tasks() > 0:
                        found_extra = True

                    # Пытаемся достать нужные ресурсы из инвентаря героя.
                    # Передаём словарь нехватки чтобы брать только то что нужно.
                    if not found_extra and self._use_inventory_resources(needed=getattr(self, '_last_missing', None)):
                        found_extra = True

                    # Если ресурсы нашлись, пробуем еще раз
                    if found_extra:
                        logging.info("📦 Ресурсы пополнены! Делаю вторую попытку...")
                        self.safe_goto(f"{self.config.base_url}/{location}")
                        self.human_sleep(1.0, 2.0)

                        # Попытка №2
                        if attempt_build():
                            logging.info(f"🚀 Со второй попытки {name} заказано! Иду в другую деревню.")
                            self._last_missing = None
                            self.log_history(village_key or 'default', name, target_level)
                            remember(step_idx)
                            self.human_sleep(1.5, 2.5)
                            return self.get_queue_finish_seconds()

                    # Если не вышло (нет ресурсов в ящиках)
                    logging.info(
                        f"💤 Все еще нет ресурсов для {name}. Оставляем деревню копить ресурсы до следующего круга.")
                    remember(step_idx)  # при перезапуске продолжим отсюда
                    return  # ВЫХОД: Ждем следующего круга карусели

            logging.info("🎉 План постройки для этой деревни полностью завершен!")
            remember(len(build_plan) + 1)  # весь план пройден

        except KeyboardInterrupt:
            logging.info("\n🛑 SmartBuilder прерван пользователем. Возврат в меню...")
