import time
import logging
from services.smart_builder import SmartBuilder
from utils.locators import SMITHY


class SmithyUpgrader(SmartBuilder):
    """
    Авто-улучшение войск в Кузнице (gid=13).

    Идентификация юнита:
        Каждая строка кузницы содержит элемент с классом .title у которого:
            onclick="Travian.Game.Manual.open('troop', <AbsoluteID>)"
        AbsoluteID = TRIBE_BASE_ID[tribe] + (troop_type_index - 1).
        Romans: 1-10, Teutons: 11-20, Gauls: 21-30 (Phalanx = 21).
        Это самый надёжный идентификатор — не зависит от порядка строк в DOM.

    Кнопки улучшения (блоки .cta):
        Внутри строки есть два блока .cta с button[type="button"]:
          • 1-й .cta — обычное улучшение (без рекламы)
          • 2-й .cta — улучшение с рекламой (-25% времени)

    Настройки (секция smithy):
        upgrade_queue: [{troop_type_index, target_level, priority}]
        Реклама включается глобальным тумблером smithy_use_ads в features.
    """

    SMITHY_URL = "build.php?gid=13"

    # Абсолютный ID первого юнита каждого племени в Travian.
    # Travian.Game.Manual.open('troop', ID) — ID = base + (troop_type_index - 1)
    TRIBE_BASE_ID = {
        "roman":  1,   # t1=1 (Legionnaire) … t10=10
        "teuton": 11,  # t1=11 (Clubswinger) … t10=20
        "gaul":   21,  # t1=21 (Phalanx)     … t10=30
    }

    # Селекторы специфичные для кузницы (остальные берутся из SmartBuilder.LOCATORS)
    SMITHY_LOCATORS = {
        # Контейнер страницы кузницы — подтверждает что мы на нужной странице
        'smithy_container': '#research, .researches, .upgradeBuilding, .smithy_upgrade',
        # Текущий уровень юнита в строке
        'unit_level': '.level, .researchLevel, .upgradeLevel, td.level',
        # Индикатор занятости кузницы (идёт исследование)
        'busy_indicator': '.buildDuration, .upgradeList .item, .smithy_build .buildingList li',
    }

    def __init__(self, page, config, settings_store=None):
        super().__init__(page, config)
        self.settings_store = settings_store

    # ------------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------------

    def _get_queue(self) -> list:
        """Читает очередь улучшений, фильтрует enabled, сортирует по priority."""
        if not self.settings_store:
            return []
        raw = self.settings_store.section("smithy").get("upgrade_queue", [])
        # Реклама включается одним общим тумблером в меню (features), а не для
        # каждого юнита отдельно.
        use_ads_global = self.settings_store.feature("smithy_use_ads", False)
        items = []
        for entry in (raw or []):
            try:
                if not entry.get("enabled", True):
                    continue
                items.append({
                    "troop_type_index": int(entry.get("troop_type_index", 1)),
                    "target_level":     min(20, max(1, int(entry.get("target_level", 1)))),
                    "priority":         int(entry.get("priority", 99)),
                    "use_ad":           use_ads_global,
                })
            except Exception:
                continue
        return sorted(items, key=lambda x: x["priority"])

    # ------------------------------------------------------------------
    # Навигация и состояние
    # ------------------------------------------------------------------

    def _get_tribe(self) -> str:
        """
        Читает племя из settings_store.
        Tribe хранится в секции farm (farm.tribe) — именно туда пишет GUI.
        Дополнительно проверяет корень на случай другой конфигурации.
        """
        if self.settings_store:
            try:
                # Основное место: секция farm, ключ tribe
                tribe = self.settings_store.section("farm").get("tribe", "")
                if tribe:
                    return str(tribe).lower()
                # Запасной: корень настроек
                tribe = self.settings_store.get_all().get("tribe", "")
                if tribe:
                    return str(tribe).lower()
            except Exception:
                logging.debug("suppressed error in actions/smithy_action:99", exc_info=True)
        return "roman"

    def _detect_tribe_from_page(self) -> str:
        """
        Определяет племя автоматически по минимальному ID юнита на странице кузницы.
        Romans 1-10, Teutons 11-20, Gauls 21-30.
        """
        try:
            import re as _re
            els = self.page.locator("[onclick*=\"open('troop',\"]").all()
            ids = []
            for el in els:
                oc = el.get_attribute("onclick") or ""
                m = _re.search(r"open\('troop',\s*(\d+)\)", oc)
                if m:
                    ids.append(int(m.group(1)))
            if not ids:
                return ""
            min_id = min(ids)
            if min_id <= 10:
                return "roman"
            elif min_id <= 20:
                return "teuton"
            elif min_id <= 30:
                return "gaul"
        except Exception:
            logging.debug("suppressed error in actions/smithy_action:126", exc_info=True)
        return ""

    def _troop_absolute_id(self, troop_type_index: int) -> int:
        """
        Переводит troop_type_index (1-10) в абсолютный ID юнита Travian.
        Travian.Game.Manual.open('troop', <ID>) — именно этот ID в onclick.
        Сначала пробует определить племя по странице (надёжнее), затем из настроек.
        """
        tribe = self._detect_tribe_from_page() or self._get_tribe()
        base  = self.TRIBE_BASE_ID.get(tribe, 1)
        return base + (troop_type_index - 1)

    def _open_smithy(self) -> bool:
        """Переходит на страницу кузницы. Возвращает False если кузница недоступна."""
        try:
            self.safe_goto(f"{self.config.base_url}/{self.SMITHY_URL}")
            self.human_sleep(1.5, 2.5)
            visible = self.page.locator(self.SMITHY_LOCATORS['smithy_container']).count() > 0
            return visible
        except Exception as e:
            logging.warning(f"[Smithy] Не удалось открыть кузницу: {e}")
            return False

    def _is_busy(self) -> bool:
        """Проверяет, идёт ли сейчас исследование (глобально по странице)."""
        try:
            if self.page.locator(self.SMITHY_LOCATORS['busy_indicator']).count() > 0:
                return True
            # Активный таймер обратного отсчёта на странице кузницы = идёт исследование
            if self.page.locator("span.timer[value], .buildDuration .timer, .research .timer").count() > 0:
                return True
        except Exception:
            logging.debug("suppressed error in actions/smithy_action:159", exc_info=True)
        return False

    def _get_in_progress(self) -> list:
        """
        Читает список идущих улучшений из блока .under_progress.
        Структура Travian:
            .under_progress ... .desc
                .unit uXX   → XX = абсолютный ID юнита (u21 = Фаланга)
                .level      → до какого уровня идёт улучшение
        Возвращает [{unit_id, level, name, seconds, timer}, ...].
        """
        try:
            return self.page.evaluate(r'''
                () => {
                    const out = [];
                    // сам .under_progress может быть контейнером или строкой —
                    // берём все элементы с .desc внутри области прогресса.
                    const scope = document.querySelector('.under_progress') || document;
                    const items = scope.matches('.under_progress')
                        ? scope.querySelectorAll('li, .desc, tr')
                        : scope.querySelectorAll('.under_progress li, .under_progress .desc, .under_progress tr');
                    const seen = new Set();
                    items.forEach(node => {
                        const desc = node.querySelector('.desc') || node;
                        // ID юнита из класса .unit uXX
                        let unitId = null;
                        const unitEl = desc.querySelector('[class*="unit"]') ||
                                       node.querySelector('[class*="unit"]');
                        if (unitEl) {
                            const m = (unitEl.className || '').match(/\bu(\d+)\b/);
                            if (m) unitId = parseInt(m[1]);
                        }
                        // Целевой уровень из .level
                        let level = null;
                        const lvlEl = desc.querySelector('.level') || node.querySelector('.level');
                        if (lvlEl) { const m = lvlEl.textContent.match(/\d+/); if (m) level = parseInt(m[0]); }
                        // Имя юнита (если есть)
                        const nameEl = desc.querySelector('.name, .title, a');
                        let name = nameEl ? nameEl.textContent.trim() : '';
                        if (!name) name = (desc.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
                        // Таймер обратного отсчёта
                        const timerEl = node.querySelector('span.timer[value], .timer, .buildDuration .timer');
                        let seconds = null, timer = '';
                        if (timerEl) {
                            const v = parseInt(timerEl.getAttribute('value'));
                            seconds = Number.isFinite(v) ? v : null;
                            timer = timerEl.textContent.trim();
                        }
                        if (unitId == null && level == null) return;
                        const key = unitId + ':' + level;
                        if (seen.has(key)) return;
                        seen.add(key);
                        out.push({ unit_id: unitId, level, name, seconds, timer });
                    });
                    return out;
                }
            ''') or []
        except Exception as e:
            logging.debug(f"[Smithy] _get_in_progress: {e}")
            return []

    def _is_unit_upgrading(self, troop_index: int) -> bool:
        """
        Проверяет, идёт ли УЖЕ улучшение конкретного юнита, по списку
        .under_progress (сопоставление по абсолютному ID юнита).
        Кузница Travian ставит улучшения в очередь: уровень в .title не меняется
        пока идёт исследование, а кнопка остаётся активной — без этой проверки
        бот бесконечно доставлял бы в очередь следующие уровни.
        """
        abs_id = self._troop_absolute_id(troop_index)
        for item in self._get_in_progress():
            if item.get("unit_id") == abs_id:
                lvl = item.get("level")
                logging.info(f"[Smithy] t{troop_index} (id={abs_id}): улучшение уже идёт"
                             + (f" до ур. {lvl}." if lvl else "."))
                return True
        return False

    def _save_progress(self):
        """
        Записывает список идущих улучшений кузницы в stats_{name}.json (ключ
        'smithy'), не затирая остальные поля — GUI показывает его как стройку.
        Каждый элемент дополняется troop_index (1-10) для подписи в интерфейсе.
        """
        import json, os
        items = self._get_in_progress()
        # определяем базу племени, чтобы вычислить troop_index из абсолютного ID
        tribe = self._detect_tribe_from_page() or self._get_tribe()
        base  = self.TRIBE_BASE_ID.get(tribe, 1)
        for it in items:
            uid = it.get("unit_id")
            if isinstance(uid, int):
                ti = uid - base + 1
                it["troop_index"] = ti if 1 <= ti <= 10 else None
        from utils.paths import account_file
        name = getattr(self.config, 'name', 'bot')
        path = str(account_file(name, 'stats'))
        try:
            with open(path, "r", encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            stats = {}
        stats["smithy"] = items
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            logging.debug(f"[Smithy] _save_progress: {e}")

    # ------------------------------------------------------------------
    # Поиск строки юнита по абсолютному ID в onclick
    # ------------------------------------------------------------------

    def _find_unit_row(self, troop_index: int):
        """
        Ищет контейнер строки юнита по onclick="Travian.Game.Manual.open('troop', <ID>)".
        onclick стоит НЕ на .title, а на соседнем элементе (a/span/button).
        Находим этот элемент, поднимаемся к общему контейнеру строки.
        """
        abs_id   = self._troop_absolute_id(troop_index)
        selector = f"[onclick*=\"open('troop', {abs_id})\"]"
        el = self.page.locator(selector)
        if el.count() == 0:
            logging.warning(f"[Smithy] t{troop_index} (id={abs_id}): onclick-элемент не найден на странице.")
            return None
        el_first = el.first

        # Главная стратегия: ближайший предок, который содержит блок .cta.
        # Именно этот контейнер объединяет .title (название/уровень) и кнопки .cta.
        try:
            row = el_first.locator("xpath=ancestor::*[.//*[contains(@class,'cta')]][1]")
            if row.count() > 0:
                return row.first
        except Exception:
            logging.debug("suppressed error in actions/smithy_action:295", exc_info=True)

        # Запасные варианты — типовые контейнеры строки (по одному, без union).
        for xpath in (
            "xpath=ancestor::tr[1]",
            "xpath=ancestor::li[1]",
            "xpath=ancestor::div[contains(@class,'unit')][1]",
            "xpath=ancestor::div[contains(@class,'item')][1]",
            "xpath=ancestor::div[contains(@class,'row')][1]",
            "xpath=..",
        ):
            try:
                candidate = el_first.locator(xpath)
                if candidate.count() > 0:
                    return candidate.first
            except Exception:
                continue
        return el_first  # последний резерв: сам элемент с onclick

    # ------------------------------------------------------------------
    # Чтение текущего уровня
    # ------------------------------------------------------------------

    def _get_current_level(self, troop_index: int) -> int:
        """
        Читает текущий уровень улучшения из текста блока .title.
        Формат: "Фаланга Уровень 1 (Имеется: 35)" — берём первую цифру после слова
        Уровень/Level. Если .level дочерний элемент — берём цифры из него.
        Возвращает 0 если не улучшался, -1 если юнит не найден.
        """
        abs_id = self._troop_absolute_id(troop_index)
        # Находим строку-контейнер через _find_unit_row
        row = self._find_unit_row(troop_index)
        if row is None:
            return -1
        try:
            import re as _re
            # Ищем .title внутри контейнера строки
            title_el = row.locator(".title").first
            if title_el.count() == 0:
                # Запасной: ищем .level напрямую в строке
                lvl_el = row.locator(".level").first
                if lvl_el.count() > 0:
                    raw = lvl_el.inner_text().strip()
                    digits = "".join(c for c in raw if c.isdigit())
                    return int(digits) if digits else 0
                return 0

            raw = title_el.inner_text().strip()

            # Диагностика: точный текст .title и .level, чтобы видеть что парсим.
            lvl_el  = title_el.locator(".level").first
            raw_lvl = lvl_el.inner_text().strip() if lvl_el.count() > 0 else "<нет .level>"
            logging.info(f"[Smithy] t{troop_index}: .title={raw!r} | .level={raw_lvl!r}")

            # 1) Уровень из текста вида "Уровень N" / "Level N" (исключает
            #    посторонние числа: кол-во юнитов "Имеется: 35", атаку и т.п.).
            for source in (raw_lvl, raw):
                m = _re.search(r"(?:Уровень|Level|Ур\.?|Lvl\.?)\s*[:.]?\s*(\d+)", source, _re.IGNORECASE)
                if m:
                    level = int(m.group(1))
                    logging.info(f"[Smithy] t{troop_index}: распознан уровень = {level}")
                    return level

            # 2) .level содержит ТОЛЬКО одно число (бейдж уровня без слова) — берём его.
            nums = _re.findall(r"\d+", raw_lvl)
            if len(nums) == 1:
                level = int(nums[0])
                logging.info(f"[Smithy] t{troop_index}: уровень из бейджа .level = {level}")
                return level

            # Юнит показан, но текста уровня нет — значит ещё не улучшался (0).
            logging.info(f"[Smithy] t{troop_index}: текст уровня не найден -> считаю уровень 0.")
            return 0
        except Exception as e:
            logging.warning(f"[Smithy] get_current_level t{troop_index}: {e}")
            return 0

    # ------------------------------------------------------------------
    # Поиск кнопок в блоках .cta
    # ------------------------------------------------------------------

    def _get_cta_button(self, troop_index: int, ad: bool):
        """
        Возвращает Playwright Locator кнопки улучшения из нужного блока .cta.
        ad=False -> зелёная кнопка (обычное улучшение, type="button")
        ad=True  -> фиолетовая кнопка (реклама -25%, type="submit"!)
        Надёжнее искать по классу цвета: green / purple — тип кнопки у
        рекламной submit, а не button, поэтому старый селектор её не находил.
        """
        row = self._find_unit_row(troop_index)
        if row is None:
            return None
        base_sel = SMITHY['upgrade_btn_ad'] if ad else SMITHY['upgrade_btn_normal']
        color = "purple" if ad else "green"
        # 1) По классу цвета — самый надёжный признак
        btn = row.locator(f"{base_sel}, {SMITHY['cta_block']} button.{color}")
        if btn.count() > 0:
            return btn.first
        # 2) Fallback: по индексу блока .cta, кнопка ЛЮБОГО типа
        cta_index  = 1 if ad else 0
        cta_blocks = row.locator(SMITHY['cta_block'])
        if cta_blocks.count() <= cta_index:
            return None
        return cta_blocks.nth(cta_index).locator("button").first

    # ------------------------------------------------------------------
    # Клик по кнопке улучшения
    # ------------------------------------------------------------------

    def _click_upgrade_normal(self, troop_index: int) -> bool:
        """Нажимает кнопку в первом блоке .cta (обычное улучшение без рекламы)."""
        try:
            btn = self._get_cta_button(troop_index, ad=False)
            if btn is None or btn.count() == 0:
                logging.warning(f"[Smithy] t{troop_index}: кнопка обычного улучшения не найдена.")
                return False
            if not btn.is_visible() or not btn.is_enabled():
                logging.warning(f"[Smithy] t{troop_index}: кнопка обычного улучшения недоступна.")
                return False
            self.human_click(btn, force=True)
            self.human_sleep(1.0, 2.0)
            logging.info(f"[Smithy] t{troop_index}: улучшение запущено (обычное).")
            return True
        except Exception as e:
            logging.debug(f"[Smithy] click_upgrade_normal t{troop_index}: {e}")
            return False

    def _click_upgrade_ad(self, troop_index: int) -> bool:
        """
        Нажимает кнопку во втором блоке .cta (улучшение с рекламой, -25% времени).
        После нажатия обрабатывает окно согласия и видеоплеер через SmartBuilder.
        """
        try:
            btn = self._get_cta_button(troop_index, ad=True)
            if btn is None or btn.count() == 0:
                logging.info(f"[Smithy] t{troop_index}: кнопка рекламы не найдена, пробую обычную.")
                return False
            if not btn.is_visible() or not btn.is_enabled():
                logging.info(f"[Smithy] t{troop_index}: кнопка рекламы недоступна.")
                return False

            self.human_click(btn, force=True)
            logging.info(f"[Smithy] t{troop_index}: нажата кнопка рекламы.")
            self.human_sleep(1.2, 2.0)

            # Окно согласия (checkbox + ok.green) — показывается только 1 раз
            self._handle_ad_consent()
            # Запуск плеера (play + play_small + mute) через метод SmartBuilder
            self._click_video_feature_btn()
            # Ждём прокрутку рекламы
            self._wait_for_ad()

            logging.info(f"[Smithy] t{troop_index}: реклама досмотрена, улучшение -25% запущено.")
            return True
        except Exception as e:
            logging.warning(f"[Smithy] click_upgrade_ad t{troop_index}: {e}")
            return False

    # ------------------------------------------------------------------
    # Главный метод
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Обходит очередь по приоритету и запускает первое возможное улучшение.
        Один вызов = одно улучшение (кузница занята одним исследованием за раз).
        """
        if self.settings_store and not self.settings_store.feature("smithy_enabled", False):
            logging.info("[Smithy] Авто-улучшение выключено.")
            return

        queue = self._get_queue()
        if not queue:
            logging.info("[Smithy] Очередь улучшений пуста.")
            return

        if not self._open_smithy():
            logging.warning("[Smithy] Кузница недоступна в текущей деревне.")
            return

        # Сохраняем текущий прогресс улучшений для отображения в GUI.
        self._save_progress()

        for job in queue:
            idx    = job["troop_type_index"]
            target = job["target_level"]
            use_ad = job["use_ad"]

            current = self._get_current_level(idx)
            if current < 0:
                logging.info(f"[Smithy] t{idx}: юнит не найден в кузнице, пропуск.")
                continue
            if current >= target:
                logging.info(f"[Smithy] t{idx}: уровень {current}/{target} — цель достигнута.")
                continue
            # Улучшение этого юнита уже идёт (в очереди) — не дублируем.
            if self._is_unit_upgrading(idx):
                logging.info(f"[Smithy] t{idx}: улучшение уже в процессе, жду завершения.")
                continue

            logging.info(
                f"[Smithy] t{idx}: уровень {current} -> {target} "
                f"(приоритет {job['priority']}, реклама={'да' if use_ad else 'нет'})."
            )

            success = False
            if use_ad:
                # Сначала пробуем через рекламу, при неудаче — обычный способ
                success = self._click_upgrade_ad(idx)
                if not success:
                    logging.info(f"[Smithy] t{idx}: реклама недоступна, пробую обычный способ.")
                    success = self._click_upgrade_normal(idx)
            else:
                success = self._click_upgrade_normal(idx)

            if success:
                # Кузница теперь занята — следующий юнит при следующем запуске
                return

        logging.info("[Smithy] Нечего улучшать: все цели достигнуты или кнопки недоступны.")
