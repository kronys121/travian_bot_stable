import re
import time
import logging
from utils.base_action import BaseAction


class HeroAdventure(BaseAction):
    LOCATORS = {
        'health_val':    '.stats .value',
        'adv_rows':      '.borderGap.adventureList tbody tr',
        'distance':      '.distance',
        'duration':      '.cellWrapper .duration',
        'difficulty':    '.difficulty',
        # Основная кнопка запуска приключения
        'start_btn':     '.textButtonV2',
        # Две фиолетовые кнопки буста: первая — сократить время, вторая — повысить сложность
        'boost_btns':    '.textButtonV2.buttonFramed.withTextAndIcon.rectangle.withText.purple',
        # Попап согласия с чекбоксом (внутри iframe .buttonWrapper.formV2)
        'boost_checkbox': '.buttonWrapper.formV2 .checkbox',
        'boost_ok':       '.textButtonV2.buttonFramed.dialogButtonOk.rectangle.withText.green',
        # Кнопка воспроизведения видео в плеере
        'ad_play_btn':       '[id^="player"] > div > div > div, .atg-gima-big-play-button',
        'ad_play_btn_small': '.atg-gima-play-button',
        'ad_mute_btn':       '.atg-gima-audio-button.atg-gima-controlbar-btn',
    }

    # Сколько секунд ждать пока крутится реклама
    AD_WAIT_SECONDS = 40

    def __init__(self, page, config):
        super().__init__(page, config)

    # ------------------------------------------------------------------
    # Утилиты: поиск в iframe + клик видео
    # ------------------------------------------------------------------

    def _find_in_frames(self, selector: str, timeout_ms: int = 15000):
        """
        Ищет элемент по селектору на главной странице И во всех iframe.
        Возвращает (locator, where_str) или (None, None).
        """
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            try:
                if self.page.locator(selector).count() > 0:
                    loc = self.page.locator(selector).first
                    if loc.is_visible():
                        return loc, "page"
            except Exception:
                logging.debug("suppressed error in actions/adventure_action:50", exc_info=True)
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
                logging.debug("suppressed error in actions/adventure_action:63", exc_info=True)
            time.sleep(0.5)
        return None, None

    def _handle_boost_consent(self) -> bool:
        """
        Обрабатывает попап согласия который появляется при нажатии фиолетовой кнопки буста.
        Попап находится внутри iframe (.buttonWrapper.formV2):
          1. Ставим галку .checkbox
          2. Жмём .textButtonV2.buttonFramed.dialogButtonOk.rectangle.withText.green
        Возвращает True если попап был и успешно принят, False если его не было.
        """
        checkbox_loc, where = self._find_in_frames(
            self.LOCATORS['boost_checkbox'], timeout_ms=4000
        )
        if checkbox_loc is None:
            return False  # попапа нет — уже соглашался раньше

        logging.info(f"Обнаружен попап согласия на буст ({where}), принимаю...")
        try:
            checkbox_loc.click(force=True)
        except Exception:
            checkbox_loc.dispatch_event("click")
        self.human_sleep(0.4, 0.8)

        ok_loc, _ = self._find_in_frames(
            self.LOCATORS['boost_ok'], timeout_ms=3000
        )
        if ok_loc is not None:
            try:
                ok_loc.click(force=True)
            except Exception:
                ok_loc.dispatch_event("click")
            logging.info("Попап закрыт.")
            self.human_sleep(0.8, 1.5)
        return True

    def _watch_boost_video(self):
        """
        После нажатия фиолетовой кнопки и закрытия попапа:
        1. Жмём кнопку пуск (большая кнопка воспроизведения в плеере)
        2. Жмём запасную кнопку пуск (маленькая в контролбаре)
        3. Отключаем звук
        4. Ждём AD_WAIT_SECONDS пока реклама крутится
        """
        self.human_sleep(1.5, 2.5)

        # Первый пуск (большая кнопка)
        play_loc, _ = self._find_in_frames(self.LOCATORS['ad_play_btn'], timeout_ms=15000)
        if play_loc is not None:
            self.human_sleep(0.5, 1.2)
            try:
                play_loc.click(force=True)
                logging.info("Нажал первую кнопку воспроизведения.")
            except Exception as e:
                logging.debug(f"play btn 1 error: {e}")

        # Второй пуск (запасная маленькая кнопка)
        self.human_sleep(1.0, 2.0)
        small_loc, _ = self._find_in_frames(self.LOCATORS['ad_play_btn_small'], timeout_ms=8000)
        if small_loc is not None:
            try:
                small_loc.click(force=True)
                logging.info("Нажал вторую кнопку воспроизведения.")
            except Exception as e:
                logging.debug(f"play btn 2 error: {e}")

        # Выключаем звук
        self.human_sleep(1.0, 2.0)
        mute_loc, _ = self._find_in_frames(self.LOCATORS['ad_mute_btn'], timeout_ms=8000)
        if mute_loc is not None:
            try:
                mute_loc.click(force=True)
                logging.info("Выключил звук рекламы.")
            except Exception as e:
                logging.debug(f"mute btn error: {e}")

        # Ждём окончания рекламы
        secs = self.AD_WAIT_SECONDS
        logging.info(f"Смотрю рекламу (~{secs}с)...")
        self.human_sleep(secs, secs + 6)

        # Закрываем пост-рекламный диалог если появился
        for sel in [self.LOCATORS['boost_ok'], '#dialogButtonOk', '.dialogButtonOk',
                    '#dialogContent button.green', '.dialogVisible button.green']:
            try:
                b = self.page.locator(sel).first
                if b.is_visible():
                    self.human_click(b, force=True)
                    self.human_sleep(0.5, 1.0)
                    break
            except Exception:
                continue

    def _read_adventure_duration(self, row) -> int | None:
        """
        Читает длительность приключения из строки <tr> таблицы .adventureList.
        Приоритет: div.bonusDuration (появляется после просмотра рекламы, -25%),
        если не найдена — div.duration (обычное время).
        DOM: td.duration > div.cellWrapper > div.bonusDuration | div.duration
        Возвращает секунды (int) или None.
        """
        try:
            result = row.evaluate(r'''
                (row) => {
                    const bonus = row.querySelector('td.duration div.bonusDuration');
                    const normal = row.querySelector('td.duration div.duration');
                    return {
                        bonus: bonus ? bonus.textContent.trim() : null,
                        normal: normal ? normal.textContent.trim() : null,
                    };
                }
            ''')
            # Приоритет — bonusDuration (сокращённое время после рекламы)
            txt = result.get('bonus') or result.get('normal') if result else None
            source = 'bonusDuration' if result and result.get('bonus') else 'duration'
            if not txt:
                logging.warning("[adv] div.duration/bonusDuration не найден в строке приключения.")
                return None
            m = re.search(r'(\d+):(\d+):(\d+)', txt)
            if m:
                secs = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
                logging.info(f"[adv] Длительность ({source}): {txt} = {secs}с.")
                return secs
            m2 = re.search(r'(\d+):(\d+)', txt)
            if m2:
                secs = int(m2[1]) * 60 + int(m2[2])
                logging.info(f"[adv] Длительность ({source}): {txt} = {secs}с.")
                return secs
            logging.warning(f"[adv] Не удалось распарсить время '{txt}' ({source}).")
            return None
        except Exception as e:
            logging.debug(f"_read_adventure_duration: {e}")
            return None

    def _is_boost_active(self, kind: str) -> bool:
        """
        Проверяет, активирован ли бонус видео-рекламы уже.
        kind: 'duration'   -> ищет .videoFeatureBonusBox.adventureDuration.bonusReady .bonusReadyText
              'difficulty' -> ищет .videoFeatureBonusBox.adventureDifficulty.bonusReady .bonusReadyText
        Возвращает True если бонус уже активирован (видео смотреть не нужно).
        """
        selectors = {
            'duration':   '.videoFeatureBonusBox.adventureDuration.bonusReady .bonusReadyText',
            'difficulty': '.videoFeatureBonusBox.adventureDifficulty.bonusReady .bonusReadyText',
        }
        sel = selectors.get(kind)
        if not sel:
            return False

        try:
            count = self.page.locator(sel).count()
            visible = self.page.locator(sel).first.is_visible() if count > 0 else False
            logging.debug(
                f"[adv:debug] _is_boost_active('{kind}'): selector='{sel}' "
                f"count={count} visible={visible}"
            )
            return count > 0 and visible
        except Exception as e:
            logging.debug(f"[adv:debug] _is_boost_active('{kind}') exception: {e}")
            return False

    def _click_boost_btn(self, index: int, label: str) -> bool:
        """
        Нажимает фиолетовую кнопку буста по индексу (0 = сократить время, 1 = сложность).
        После клика обрабатывает попап согласия и запускает просмотр видео.
        Возвращает True если кнопка была нажата и видео запущено.
        """
        try:
            btns = self.page.locator(self.LOCATORS['boost_btns'])
            count = btns.count()
            if count <= index:
                logging.info(f"Кнопка буста [{label}] не найдена (index={index}, найдено={count}).")
                return False

            btn = btns.nth(index)
            btn_class = btn.get_attribute('class') or ''
            if 'disabled' in btn_class.split():
                logging.info(f"Кнопка буста [{label}] задизейблена — пропускаю.")
                return False
            if not btn.is_visible():
                logging.info(f"Кнопка буста [{label}] не видна — пропускаю.")
                return False

            logging.info(f"Нажимаю кнопку буста [{label}]...")
            self.human_click(btn, force=True)
            self.human_sleep(1.0, 2.0)

            # Попап согласия (появляется только при первом использовании)
            self._handle_boost_consent()

            # Смотрим видео
            self._watch_boost_video()
            logging.info(f"Буст [{label}] применён.")
            return True

        except Exception as e:
            logging.error(f"Ошибка при нажатии кнопки буста [{label}]: {e}")
            return False

    # ------------------------------------------------------------------
    # Основные методы
    # ------------------------------------------------------------------

    def is_health_ok(self, min_health: int = 30) -> bool:
        logging.info("Проверяю здоровье героя...")
        try:
            self.safe_goto(self.config.hero_attributes_url)
            health_el = self.page.locator(self.LOCATORS['health_val']).first
            health_el.wait_for(timeout=5000)
            raw_text = health_el.text_content()
            health_digits = re.sub(r'\D', '', raw_text)
            if not health_digits:
                logging.error("Не удалось спарсить здоровье героя.")
                return False
            health = int(health_digits)
            logging.info(f"Текущее здоровье: {health}%")
            if health <= min_health:
                logging.warning(f"Здоровье ({health}%) ниже порога ({min_health}%). Идти опасно!")
                return False
            return True
        except Exception as e:
            logging.error(f"Ошибка при проверке здоровья: {e}")
            return False

    def is_hero_busy(self) -> bool:
        """
        Возвращает True если герой сейчас в приключении или в пути.
        """
        try:
            self.safe_goto(self.config.hero_adventure_url)
            self.page.wait_for_load_state('domcontentloaded')
            rows = self.page.locator('.borderGap.adventureList tbody tr')
            if rows.count() == 0:
                return False
            btn = rows.nth(0).locator('.textButtonV2').first
            cls = btn.get_attribute('class') or ''
            return 'disabled' in cls.split()
        except Exception:
            return False

    def auto_adventure(self, shorten: bool = False, boost_difficulty: bool = False,
                       min_health: int = 30) -> bool:
        """
        Отправляет героя в приключение если он дома и здоров.

        Args:
            shorten:          смотреть первое видео (сократить время приключения)
            boost_difficulty: смотреть второе видео (повысить до сложного)
            min_health:       не отправлять, если HP героя ниже этого порога (%)

        Возвращает True  — герой отправлен или уже в пути.
        Возвращает False — герой дома, нет приключений или здоровье низкое.
        """
        if not self.is_health_ok(min_health=min_health):
            self.safe_goto(f"{self.config.base_url}/dorf1.php")
            return False

        logging.info("Герой здоров! Проверяю список приключений...")
        self.safe_goto(self.config.hero_adventure_url)

        try:
            self.page.wait_for_selector('.borderGap.adventureList', timeout=5000)
        except Exception:
            logging.info("Таблица приключений не найдена.")
            self.safe_goto(f"{self.config.base_url}/dorf1.php")
            return False

        if self.page.locator('.borderGap.adventureList .noAdventures').count() > 0:
            logging.info("Список приключений пуст.")
            self.safe_goto(f"{self.config.base_url}/dorf1.php")
            return False

        adv_rows = self.page.locator(self.LOCATORS['adv_rows'])
        adv_count = adv_rows.count()
        if adv_count == 0:
            logging.info("Список приключений пуст.")
            self.safe_goto(f"{self.config.base_url}/dorf1.php")
            return False

        logging.info(f"Доступно приключений: {adv_count}")

        try:
            first_adv = adv_rows.nth(0)

            info = first_adv.evaluate(r'''
                (row) => {
                    const out = { distance: null, difficulty: null };
                    const distEl = row.querySelector('.distance, td.distance');
                    if (distEl) { const m = distEl.textContent.match(/\d+/); if (m) out.distance = m[0]; }
                    if (out.distance == null) {
                        const tds = row.querySelectorAll('td');
                        for (const td of tds) {
                            const t = td.textContent.trim();
                            if (/^\d+$/.test(t)) { out.distance = t; break; }
                        }
                    }
                    const iconEl = row.querySelector('.difficulty .iconWrapper [class*="difficulty_"]');
                    if (iconEl) {
                        const cls = iconEl.className.baseVal || iconEl.className || '';
                        if (cls.includes('difficulty_normal')) out.difficulty = 'normal';
                        else if (cls.includes('difficulty_hard')) out.difficulty = 'hard';
                    }
                    if (!out.difficulty) {
                        const anyEl = row.querySelector('.difficulty [title], .difficulty [alt], .difficulty');
                        if (anyEl) {
                            const t = anyEl.getAttribute('title') || anyEl.getAttribute('alt');
                            if (t) out.difficulty = t.trim();
                        }
                    }
                    return out;
                }
            ''')
            distance   = info.get('distance') or '?'
            difficulty = info.get('difficulty') or '?'
            logging.info(f"Выбрано приключение: дистанция={distance}, сложность={difficulty}")

            # Проверяем что герой ещё не в пути
            start_btn = first_adv.locator(self.LOCATORS['start_btn']).first
            btn_class = (start_btn.get_attribute("class") or "")
            if "disabled" in btn_class.split():
                logging.info("Герой уже в приключении (кнопка disabled).")
                self.safe_goto(f"{self.config.base_url}/dorf1.php")
                return True

            # --- Кнопка 1: сократить время (первая фиолетовая) ---
            if shorten:
                logging.debug("[adv:debug] Проверяю бонус 'duration' перед попыткой видео...")
                if self._is_boost_active('duration'):
                    logging.debug("[adv:debug] Бонус 'duration' УЖЕ активен — пропускаю видео.")
                else:
                    logging.debug("[adv:debug] Бонус 'duration' не активен — смотрю видео.")
                    self._click_boost_btn(index=0, label="сократить время")

            # --- Кнопка 2: повысить сложность (вторая фиолетовая) ---
            if boost_difficulty:
                logging.debug("[adv:debug] Проверяю бонус 'difficulty' перед попыткой видео...")
                if self._is_boost_active('difficulty'):
                    logging.debug("[adv:debug] Бонус 'difficulty' УЖЕ активен — пропускаю видео.")
                else:
                    logging.debug("[adv:debug] Бонус 'difficulty' не активен — смотрю видео.")
                    self._click_boost_btn(index=1, label="повысить сложность")
                self.safe_goto(self.config.hero_adventure_url)
                self.page.wait_for_load_state('domcontentloaded')
                self.human_sleep(1.0, 2.0)
                adv_rows = self.page.locator(self.LOCATORS['adv_rows'])
                first_adv = adv_rows.nth(0)

            # --- Отправляем героя ---
            start_btn = first_adv.locator(self.LOCATORS['start_btn']).first
            btn_class = (start_btn.get_attribute("class") or "")
            if "disabled" in btn_class.split():
                logging.info("Герой уже в приключении после буста.")
                self.safe_goto(f"{self.config.base_url}/dorf1.php")
                return True

            if start_btn.is_visible() and start_btn.is_enabled():
                # Читаем длительность ДО клика — после клика строка исчезает из DOM.
                one_way = self._read_adventure_duration(first_adv)

                self.human_click(start_btn)
                logging.info("Герой успешно отправлен в приключение!")

                if one_way and one_way > 0:
                    # Герой идёт туда и обратно за одинаковое время + 30с буфер.
                    cooldown = one_way * 2 + 30
                    logging.info(
                        f"Время в одну сторону: {one_way//60}м {one_way%60}с. "
                        f"Следующая проверка через {cooldown//60}м {cooldown%60}с."
                    )
                    self.safe_goto(f"{self.config.base_url}/dorf1.php")
                    return cooldown

                self.safe_goto(f"{self.config.base_url}/dorf1.php")
                return True
            else:
                logging.warning("Кнопка отправки недоступна (герой, возможно, уже в пути).")
                self.safe_goto(f"{self.config.base_url}/dorf1.php")
                return True

        except Exception as e:
            logging.error(f"Ошибка при отправке в приключение: {e}")

        self.safe_goto(f"{self.config.base_url}/dorf1.php")
        return False
