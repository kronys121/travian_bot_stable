import time
import random
import logging
import json
import math
import requests
from bs4 import BeautifulSoup

from actions.farm_stats import FarmStats


class FarmManager:

    LOCATORS = {
        'rally_point_send': 'build.php?id=39&tt=2',
        'rally_point_troops': 'build.php?id=39&gid=16&tt=1',
        'coord_x':          'input[name="x"]',
        'coord_y':          'input[name="y"]',
        'raid_radio':       'input[value="4"]',
        'raid_submit_btn':  '#btn_ok, button[type="submit"]',
        'raid_confirm_btn': '[name="confirmSendTroops"], #btn_ok',
        'village_view':     'dorf1.php',
    }

    ANIMAL_STATS = {
        'u31': {'name': 'Крыса',     'def_inf': 25,  'def_cav': 20},
        'u32': {'name': 'Паук',      'def_inf': 35,  'def_cav': 40},
        'u33': {'name': 'Змея',      'def_inf': 40,  'def_cav': 50},
        'u34': {'name': 'Лет. мышь', 'def_inf': 66,  'def_cav': 50},
        'u35': {'name': 'Кабан',     'def_inf': 70,  'def_cav': 33},
        'u36': {'name': 'Волк',      'def_inf': 80,  'def_cav': 70},
        'u37': {'name': 'Медведь',   'def_inf': 140, 'def_cav': 200},
        'u38': {'name': 'Крокодил',  'def_inf': 380, 'def_cav': 240},
        'u39': {'name': 'Тигр',      'def_inf': 170, 'def_cav': 250},
        'u40': {'name': 'Слон',      'def_inf': 440, 'def_cav': 520},
    }

    def __init__(self, page, config, settings_store=None, adventure_action=None,
                 farm_stats=None):
        self.page = page
        self.config = config
        self.settings_store = settings_store
        self.adventure_action = adventure_action  # для проверки приключения перед фармом
        self.current_village_id = "default_village"
        self.farm_list = []
        self.is_scanning = False  # флаг: другие задачи должны проверять его перед навигацией
        self.settings = {
            "troops_per_raid":  10,
            "max_distance":     0.0,
            "scan_radius":      5,
            "troop_type_index": 1,
            "cooldown_minutes": 60,
            # Скорость войск (клеток/час) для расчёта кулдауна с учётом
            # времени возврата. 0 = выкл. (используется только базовый
            # cooldown_minutes). Пример: легионеры ~6, конница ~14.
            "troop_speed_tph": 0,
        }
        # FIX: кулдауны теперь на диске — переживают рестарт бота
        # (раньше после перезапуска бот сразу слал повторные набеги)
        self.cooldowns = self._load_cooldowns()
        # Статистика фарма (набеги/юниты/оазисы) — копится и переживает рестарт.
        # Экземпляр может быть общим с ReportCollector (передаётся снаружи).
        self.farm_stats = farm_stats or FarmStats(self._acc_name())

    # --- ПЕРСИСТЕНТНОСТЬ -------------------------------------------

    def _acc_name(self) -> str:
        return getattr(self.config, 'name', 'bot')

    def _file(self, base: str) -> str:
        """Файлы данных per-account, чтобы процессы не перетирали друг друга."""
        return f"{base}_{self._acc_name()}.json"

    def _load_cooldowns(self) -> dict:
        try:
            with open(self._file("cooldowns"), "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            logging.debug("suppressed error in actions/oasis_action:74", exc_info=True)
        return {}

    def _save_cooldowns(self):
        try:
            with open(self._file("cooldowns"), "w", encoding="utf-8") as f:
                json.dump(self.cooldowns, f, ensure_ascii=False)
        except Exception as e:
            logging.debug(f"Не удалось сохранить кулдауны: {e}")

    def _refresh_settings(self):
        """Подтягивает живые настройки фарма из SettingsStore (GUI)."""
        if self.settings_store:
            fresh = self.settings_store.section("farm")
            for k, v in fresh.items():
                if v is not None:
                    self.settings[k] = v

    # --- ДЕРЕВНЯ ---------------------------------------------------

    def update_village_identity(self) -> str:
        try:
            village_id = self.page.evaluate(r'''
                () => {
                    const activeNode = document.querySelector(
                        '.listEntry.village.active, .villageList .active, #sidebarBoxVillages .active'
                    );
                    if (activeNode) {
                        if (activeNode.dataset.did) return activeNode.dataset.did;
                        if (activeNode.dataset.sortid) {
                            const match = activeNode.dataset.sortid.match(/\d+/);
                            if (match) return match[0];
                        }
                        const a = activeNode.tagName === 'A' ? activeNode : activeNode.querySelector('a');
                        if (a && a.href) {
                            const match = a.href.match(/newdid=(\d+)/);
                            if (match) return match[1];
                        }
                    }
                    const urlMatch = window.location.href.match(/newdid=(\d+)/);
                    if (urlMatch) return urlMatch[1];
                    return null;
                }
            ''')
            if village_id:
                self.current_village_id = f"village_{village_id}"
                logging.info(f"🏡 Деревня: {self.current_village_id}")
                return self.current_village_id
        except Exception as e:
            logging.debug(f"ID деревни не найден: {e}")
        self.current_village_id = "default_village"
        return self.current_village_id

    def get_current_village_coords(self) -> tuple[int, int]:
        """
        Ищет .coordinateX / .coordinateY напрямую по DOM.
        Travian оборачивает цифры в bidi-символы (U+202D / U+202C) —
        без их удаления parseInt возвращает NaN и координаты = 0|0.
        """
        try:
            coords = self.page.evaluate(r'''
                () => {
                    // Очищаем от bidi-символов и лишних символов
                    const parse = el => {
                        const raw = el.textContent
                            .replace(/[\u202C\u202D\u200E\u200F\u200B\uFEFF]/g, "")
                            .replace(/[()|\s]/g, "")
                            .replace(/\u2212/g, "-");
                        return parseInt(raw, 10);
                    };

                    // 1) Внутри любого active-элемента
                    for (const node of document.querySelectorAll("[class*=active]")) {
                        const xEl = node.querySelector(".coordinateX");
                        const yEl = node.querySelector(".coordinateY");
                        if (xEl && yEl) {
                            const x = parse(xEl), y = parse(yEl);
                            if (!isNaN(x) && !isNaN(y)) return { x, y, src: "active" };
                        }
                    }

                    // 2) Fallback: первые на странице
                    const xEl = document.querySelector(".coordinateX");
                    const yEl = document.querySelector(".coordinateY");
                    if (xEl && yEl) {
                        const x = parse(xEl), y = parse(yEl);
                        if (!isNaN(x) && !isNaN(y)) return { x, y, src: "first" };
                    }
                    return null;
                }
            ''')
            if coords:
                logging.info(f"📍 Координаты [{coords.get('src')}]: ({coords['x']}|{coords['y']})")
                return coords['x'], coords['y']
        except Exception as e:
            logging.warning(f"⚠️ Не удалось спарсить координаты: {e}")

        fx = self.settings.get('center_x', 0)
        fy = self.settings.get('center_y', 0)
        logging.warning(f"⚠️ Fallback из settings: ({fx}|{fy})")
        return fx, fy

    # --- JSON ------------------------------------------------------

    def _save_to_json(self, filename: str, village_key: str, data: list):
        all_data = {}
        try:
            with open(filename, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    all_data = loaded
        except Exception:
            logging.debug("suppressed error in actions/oasis_action:186", exc_info=True)
        all_data[village_key] = data
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения {filename}: {e}")

    def load_saved_oases(self) -> bool:
        self.update_village_identity()
        try:
            with open(self._file("unoccupied_oases"), "r", encoding="utf-8") as f:
                all_data = json.load(f)
            if isinstance(all_data, dict) and self.current_village_id in all_data:
                self.farm_list = all_data[self.current_village_id]
                return bool(self.farm_list)
            if isinstance(all_data, list):
                self.farm_list = all_data
                return bool(self.farm_list)
        except Exception:
            logging.debug("suppressed error in actions/oasis_action:206", exc_info=True)
        self.farm_list = []
        return False

    # --- ПРОВЕРКА КЛЕТКИ ------------------------------------------

    def _parse_tile_html(self, html: str) -> dict:
        """
        Разбирает HTML попапа клетки (ответ /api/v1/map/tile-details).

        Разметка оазиса с животными (проверено на реальном сервере):
          #troop_info tbody tr → td.ico > img.unit.uNN (u31..u40 = животные),
          td.val = количество. Строки без img.unit (кнопки/«Нет информации»)
          пропускаются. Захваченный оазис содержит ссылку на профиль владельца.

        Возвращает: is_oasis, is_conquered, is_occupied, animals{uNN:count},
        has_player_troops, is_15_crop, is_9_crop, (error при пустом html).
        """
        if not html:
            return {'error': True}
        lower = html.lower()
        is_oasis = ('oasis' in lower or 'оазис' in lower or 'nature' in lower)
        is_conquered = ('spieler.php' in lower or '/profile/' in lower
                        or 'allianz.php' in lower or 'владелец' in lower or 'owner' in lower)

        animals_obj = {}
        has_player_troops = False
        total_units = 0
        is_15_crop = False
        is_9_crop = False

        soup = BeautifulSoup(html, 'html.parser')

        # Кроперы: распределение ресурсов (4-я строка = зерно)
        dist_table = soup.select_one('#distribution, table.distribution, .distribution')
        if dist_table:
            vals = dist_table.select('td.val, span.val')
            if len(vals) >= 4:
                crop_str = ''.join(c for c in vals[3].get_text() if c.isdigit())
                if crop_str:
                    crop_val = int(crop_str)
                    if crop_val == 15:
                        is_15_crop = True
                    if crop_val == 9:
                        is_9_crop = True

        # Животные в оазисах
        if is_oasis:
            for row in soup.select('#troop_info tbody tr, .troop_details tbody tr'):
                img = row.select_one('img.unit')
                val_td = row.select_one('td.val')
                if img and val_td:
                    unit_class = next(
                        (c for c in img.get('class', []) if c.startswith('u') and c[1:].isdigit()),
                        None
                    )
                    count_str = ''.join(c for c in val_td.get_text() if c.isdigit())
                    if unit_class and count_str:
                        count = int(count_str)
                        if count > 0:
                            total_units += count
                            n = int(unit_class[1:])
                            if n < 31 or n > 40:
                                has_player_troops = True
                            else:
                                animals_obj[unit_class] = count

        return {
            'is_oasis':          is_oasis,
            'is_conquered':      is_conquered,
            'is_occupied':       total_units > 0,
            'animals':           animals_obj,
            'has_player_troops': has_player_troops,
            'is_15_crop':        is_15_crop,
            'is_9_crop':         is_9_crop,
        }

    # --- СКАН ------------------------------------------------------

    def _get_session(self):
        """
        Создаёт requests.Session с куками из браузера.
        Используется для прямых API-запросов без участия браузера —
        навигация страницы вообще не влияет.
        """
        session = requests.Session()
        try:
            cookies = self.page.context.cookies()
            for c in cookies:
                session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''))
        except Exception as e:
            logging.warning(f"⚠️ Не удалось скопировать куки: {e}")
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        })
        return session

    def _fetch_tile(self, session: requests.Session, x: int, y: int) -> dict:
        """
        Прямой HTTP-запрос к /api/v1/map/tile-details через requests.
        Не зависит от навигации страницы в браузере.
        """
        try:
            url = f"{self.config.base_url}/api/v1/map/tile-details"
            resp = session.post(url, json={'x': x, 'y': y}, timeout=10)
            if not resp.ok:
                return {'error': True}

            data = resp.json()
            return self._parse_tile_html(data.get('html', ''))
        except Exception as e:
            logging.debug(f"_fetch_tile({x}|{y}) ошибка: {e}")
            return {'error': True}

    def scan_oases_around(self, center_x: int, center_y: int):
        radius = self.settings.get("scan_radius", 5)
        logging.info(f"📡 Скан (радиус {radius}) вокруг ({center_x}|{center_y})...")
        self.is_scanning = True

        # Переходим на dorf1 чтобы получить ID деревни, затем остаёмся там
        self.page.goto(f"{self.config.base_url}/{self.LOCATORS['village_view']}")
        self.page.wait_for_load_state('domcontentloaded')
        time.sleep(1)
        self.update_village_identity()

        # FIX: создаём requests-сессию с куками из браузера
        # Дальше скан идёт через HTTP-запросы, а не через page.evaluate
        # Навигация страницы вообще не мешает!
        session = self._get_session()

        current_farm_list, occupied_oases, found_croppers = [], [], []
        scanned_count = 0

        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                distance = round(math.sqrt(dx**2 + dy**2), 1)
                if distance > radius:
                    continue

                target_x = center_x + dx
                target_y = center_y + dy
                scanned_count += 1
                if scanned_count % 20 == 0:
                    logging.info(f"⏳ Просканировано {scanned_count} клеток...")

                status = self._fetch_tile(session, target_x, target_y)
                self._classify_tile(status, target_x, target_y, distance,
                                    current_farm_list, occupied_oases, found_croppers)

                time.sleep(random.uniform(0.4, 0.9))

        current_farm_list.sort(key=lambda o: o.get('distance', 999))
        self.farm_list = current_farm_list
        sorted_occupied = sorted(occupied_oases, key=lambda o: (o['def_inf'], o.get('distance', 999)))
        found_croppers.sort(key=lambda o: (o.get('distance', 999), -o.get('type', 0)))

        self.is_scanning = False
        logging.info(f"🏁 Скан завершён! Пустых: {len(current_farm_list)} | Долин: {len(found_croppers)}")
        self._save_to_json(self._file("unoccupied_oases"), self.current_village_id, current_farm_list)
        self._save_to_json(self._file("occupied_oases"),   self.current_village_id, sorted_occupied)
        self._save_to_json(self._file("croppers"),          self.current_village_id, found_croppers)

    def _classify_tile(self, status: dict, tx: int, ty: int, distance: float,
                       farm_list: list, occupied: list, croppers: list):
        """
        Разбирает результат _fetch_tile и раскладывает клетку по спискам:
        пустой оазис → farm_list, занятый/захваченный → occupied, долина → croppers.
        Используется и полным сканом, и быстрым пересканом известных оазисов.
        """
        if status.get("error"):
            return

        if status.get("is_15_crop") or status.get("is_9_crop"):
            crop_type = 15 if status.get("is_15_crop") else 9
            icon = "🌟" if crop_type == 15 else "✨"
            logging.info(f"{icon} ДОЛИНА ({crop_type} кропа): ({tx}|{ty}) [Дист: {distance}]")
            croppers.append({"x": tx, "y": ty, "type": crop_type, "distance": distance})
            return

        if not status.get("is_oasis"):
            return

        if status.get("is_conquered"):
            logging.info(f"🚩 ЗАХВАЧЕН ({tx}|{ty}). Игнорируем.")
            occupied.append({
                "x": tx, "y": ty, "distance": distance,
                "animals": {}, "has_player_troops": True,
                "def_inf": 0, "def_cav": 0, "desc": "🚩 Захвачен"
            })
        elif not status.get("is_occupied"):
            logging.info(f"✅ ПУСТОЙ: ({tx}|{ty}) [Дист: {distance}]")
            farm_list.append({"x": tx, "y": ty, "distance": distance})
        else:
            animals_data = status.get("animals", {})
            total_inf, total_cav = 0, 0
            animal_strings = []
            for u_code, count in animals_data.items():
                stats = self.ANIMAL_STATS.get(u_code)
                if stats:
                    total_inf += stats['def_inf'] * count
                    total_cav += stats['def_cav'] * count
                    animal_strings.append(f"{stats['name']}: {count}")
            desc = ", ".join(animal_strings) or "Неизвестные войска"
            if status.get("has_player_troops"):
                desc += " + ВОЙСКА ИГРОКА!"
            logging.info(f"🐺 ЗАНЯТ ({tx}|{ty}) [Дист: {distance}] -> {desc} | 🛡️{total_inf}")
            occupied.append({
                "x": tx, "y": ty, "distance": distance,
                "animals": animals_data,
                "has_player_troops": status.get("has_player_troops", False),
                "def_inf": total_inf, "def_cav": total_cav, "desc": desc
            })

    def rescan_known_oases(self):
        """
        Быстрый перескан: перепроверяет ТОЛЬКО ранее найденные оазисы/долины
        (из occupied/unoccupied/croppers), а не весь радиус.

        Зачем: после полного скана мы уже знаем все клетки-оазисы вокруг.
        Животные приходят/уходят, оазисы захватывают — но новых оазисов
        на карте не появляется. Поэтому достаточно обойти известные клетки.
        Это в разы быстрее полного скана (десятки клеток вместо сотен).

        Если известных оазисов нет — откатываемся к полному скану.
        """
        self.update_village_identity()

        # Собираем уникальные координаты всех известных клеток
        known = {}
        for o in self.load_occupied_oases():
            known[(o["x"], o["y"])] = o.get("distance", 0)
        try:
            for o in self._load_list("unoccupied_oases"):
                known[(o["x"], o["y"])] = o.get("distance", 0)
            for o in self._load_list("croppers"):
                known[(o["x"], o["y"])] = o.get("distance", 0)
        except Exception:
            logging.debug("suppressed error in actions/oasis_action:480", exc_info=True)

        if not known:
            logging.info("♻️ Нет сохранённых оазисов — запускаю полный скан.")
            cx, cy = self.get_current_village_coords()
            self.scan_oases_around(cx, cy)
            return

        logging.info(f"♻️ Быстрый перескан {len(known)} известных клеток...")
        self.is_scanning = True
        self.page.goto(f"{self.config.base_url}/{self.LOCATORS['village_view']}")
        self.page.wait_for_load_state('domcontentloaded')
        time.sleep(1)
        session = self._get_session()

        farm_list, occupied_oases, found_croppers = [], [], []
        done = 0
        for (tx, ty), distance in known.items():
            status = self._fetch_tile(session, tx, ty)
            self._classify_tile(status, tx, ty, distance,
                                farm_list, occupied_oases, found_croppers)
            done += 1
            if done % 20 == 0:
                logging.info(f"⏳ Перепроверено {done}/{len(known)} клеток...")
            time.sleep(random.uniform(0.4, 0.9))

        farm_list.sort(key=lambda o: o.get('distance', 999))
        self.farm_list = farm_list
        sorted_occupied = sorted(occupied_oases, key=lambda o: (o['def_inf'], o.get('distance', 999)))
        found_croppers.sort(key=lambda o: (o.get('distance', 999), -o.get('type', 0)))

        self.is_scanning = False
        logging.info(f"🏁 Перескан завершён! Пустых: {len(farm_list)} | Занятых: {len(occupied_oases)}")
        self._save_to_json(self._file("unoccupied_oases"), self.current_village_id, farm_list)
        self._save_to_json(self._file("occupied_oases"),   self.current_village_id, sorted_occupied)
        self._save_to_json(self._file("croppers"),          self.current_village_id, found_croppers)

    def _load_list(self, kind: str) -> list:
        """Загружает список клеток текущей деревни из JSON-файла (occupied/unoccupied/croppers)."""
        try:
            with open(self._file(kind), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data.get(self.current_village_id, [])
            if isinstance(data, list):
                return data
        except Exception:
            logging.debug("suppressed error in actions/oasis_action:527", exc_info=True)
        return []

    # --- ГЕРОЙ -----------------------------------------------------

    def get_hero_power(self) -> int:
        """
        Боевая сила героя со страницы /hero/attributes.
        Страница — SPA: контент рендерится ПОСЛЕ domcontentloaded,
        поэтому явно ждём появления блока атрибутов (до 10 сек).
        Структура: .denominator > .value (первый = боевая сила).
        Возвращает 0, если определить не удалось.
        """
        try:
            self.page.goto(f"{self.config.base_url}/hero/attributes")
            self.page.wait_for_load_state('domcontentloaded')
            # ждём, пока SPA отрендерит атрибуты героя
            try:
                self.page.wait_for_selector('.denominator .value', timeout=10000)
            except Exception:
                logging.debug("hero attributes: .denominator .value не появился за 10с")
            time.sleep(random.uniform(0.5, 1.0))

            power = self.page.evaluate(r'''
                () => {
                    // 1) Основной путь: первый .denominator > .value = боевая сила
                    const denominators = document.querySelectorAll('.denominator');
                    for (const d of denominators) {
                        const val = d.querySelector('.value');
                        if (val) {
                            const n = parseInt(val.textContent.replace(/[^\d]/g, ''), 10);
                            if (n > 0) return n;
                        }
                    }
                    // 2) fallback: селекторы по имени атрибута
                    const el = document.querySelector(
                        '[class*="fightingStrength"] .value, .power .value, [data-key="fightingStrength"]'
                    );
                    if (el) {
                        const m = el.textContent.replace(/[^\d]/g, '').match(/\d+/);
                        if (m) return parseInt(m[0], 10);
                    }
                    // 3) fallback: текст страницы "Боевая сила: N"
                    const m = document.body.innerText.match(/(?:Боевая сила|Fighting strength)\D{0,5}([\d\s.,]+)/i);
                    return m ? parseInt(m[1].replace(/\D/g, ''), 10) : 0;
                }
            ''') or 0

            if not power:
                # 4) последний шанс: API героя (работает не на всех версиях)
                power = self.page.evaluate(r'''
                    async () => {
                        for (const url of ['/api/v1/hero/v2/screen/attributes', '/api/v1/hero/attributes']) {
                            try {
                                const r = await fetch(url, {
                                    headers: { 'Accept': 'application/json' },
                                    credentials: 'same-origin',
                                });
                                if (r.ok) {
                                    const j = await r.json();
                                    const fs = j.fightingStrength ?? j.hero?.fightingStrength;
                                    if (fs) return Math.floor(Number(fs));
                                }
                            } catch (e) {}
                        }
                        return 0;
                    }
                ''') or 0

            return int(power)
        except Exception as e:
            logging.debug(f"hero power error: {e}")
            return 0

    def load_occupied_oases(self) -> list:
        """Список занятых животными оазисов текущей деревни (со скана)."""
        try:
            with open(self._file("occupied_oases"), "r", encoding="utf-8") as f:
                all_data = json.load(f)
            if isinstance(all_data, dict):
                return all_data.get(self.current_village_id, [])
            if isinstance(all_data, list):
                return all_data
        except Exception:
            logging.debug("suppressed error in actions/oasis_action:611", exc_info=True)
        return []

    def run_hero_farm(self) -> bool:
        """
        Фарм ТОЛЬКО героем (режим раннего старта).

        Логика безопасности:
          сила героя (fightingStrength) сравнивается с защитой оазиса
          (макс. из def_inf/def_cav животных). Атакуем только если
          hero_power >= защита * (hero_safety_pct / 100).
          При 150% герой должен быть в полтора раза сильнее — не умрёт.

        Одна атака за цикл — герой один.
        Пустые оазисы (без животных) НЕ атакуем — нет смысла гнать
        героя без добычи опыта/ресурсов от животных.
        """
        self.update_village_identity()
        safety = max(100, int(self.settings.get("hero_safety_pct", 150) or 150))
        max_dist = float(self.settings.get("max_distance", 0) or 0)

        # Приоритет 1: отправить героя в приключение если есть
        if self.adventure_action is not None:
            hero_went = self.adventure_action.auto_adventure()
            if hero_went:
                logging.info("Герой отправлен в приключение — фарм оазисов пропущен.")
                return False

        hero_power = self.get_hero_power()
        if hero_power <= 0:
            logging.warning("Не удалось определить силу героя — фарм героем пропущен.")
            return False
        logging.info(f"Сила героя: {hero_power} | Запас прочности: {safety}%")

        # Кандидаты: ТОЛЬКО оазисы с животными (def > 0), где герой безопасно победит.
        # Пустые оазисы не берём — нет добычи и смысла.
        candidates = []
        for o in self.load_occupied_oases():
            if o.get("has_player_troops"):
                continue  # чужие войска — не наша цель
            defense = max(int(o.get("def_inf", 0)), int(o.get("def_cav", 0)))
            if defense > 0 and hero_power * 100 >= defense * safety:
                candidates.append({**o, "def": defense})

        if max_dist > 0:
            candidates = [c for c in candidates if c.get("distance", 0) <= max_dist]

        # Приоритет: максимальная защита (= больше добычи/опыта), среди равных — ближе
        candidates.sort(key=lambda c: (-c["def"], c.get("distance", 999)))

        if not candidates:
            logging.info("🦸 Нет безопасных целей для героя (все оазисы слишком сильные или пусто).")
            return False

        for target in candidates:
            defense = target["def"]
            logging.info(
                f"🦸 Цель героя: ({target['x']}|{target['y']}) "
                f"[защита животных ~{defense}, дист {target.get('distance', '?')}] "
                f"животные: {target.get('desc', '?')}"
            )
            result = self.attack_oasis(
                target['x'], target['y'],
                troop_count=1, troop_type_index=11,   # t11 = герой
                allow_occupied=True,   # герой ходит только на оазисы с животными
                max_defense=hero_power * 100 // safety,
            )
            if result == "SUCCESS":
                logging.info("🦸 Герой отправлен. Следующая атака — когда вернётся.")
                return True
            if result == "NO_TROOPS":
                logging.info("🦸 Герой недоступен (в пути/приключении). Пропуск цикла.")
                return False
            # COOLDOWN/OCCUPIED/ERROR — пробуем следующую цель
        return False

    # --- АТАКА -----------------------------------------------------

    def _effective_cooldown_sec(self, distance: float) -> float:
        """
        Кулдаун цели с учётом времени полёта войск.

        Ближний оазис можно фармить часто, дальний — только после того,
        как войска успеют слетать туда и обратно. Берём максимум из базового
        кулдауна (cooldown_minutes) и оценки round-trip по скорости войск
        (troop_speed_tph — клеток/час, из настроек) плюс небольшой буфер.
        """
        base = float(self.settings.get("cooldown_minutes", 60)) * 60
        speed_tph = float(self.settings.get("troop_speed_tph", 0) or 0)
        if speed_tph > 0 and distance > 0:
            round_trip = (2 * distance / speed_tph) * 3600
            return max(base, round_trip + 120)  # +2 мин буфера на бой/загрузку
        return base

    def _animal_defense(self, animals: dict) -> int:
        """Суммарная защита животных в оазисе (макс из пехотной/конной)."""
        d_inf, d_cav = 0, 0
        for u_code, count in (animals or {}).items():
            st = self.ANIMAL_STATS.get(u_code)
            if st:
                d_inf += st['def_inf'] * count
                d_cav += st['def_cav'] * count
        return max(d_inf, d_cav)

    def attack_oasis(self, target_x: int, target_y: int,
                     troop_count: int, troop_type_index: int,
                     allow_occupied: bool = False, max_defense: int = 0,
                     distance: float = 0.0) -> str:
        """
        Возвращает: SUCCESS | COOLDOWN | OCCUPIED | PLAYER_TROOPS | ANIMALS | NO_TROOPS | ERROR

        Прямо перед отправкой оазис перепроверяется на свежих животных
        (они респавнятся, пока войска в пути). Логика:
          - захвачен игроком (оккупирован)          → OCCUPIED (убрать из списка навсегда)
          - войска игрока (подмога, временно)        → PLAYER_TROOPS (пропустить круг,
            цель остаётся в списке — подмога уйдёт)
          - животные, защита которых > допустимой   → ANIMALS  (временно пропустить,
            оазис остаётся в списке — животные уйдут и он снова станет фармерским)
          - иначе                                    → отправляем набег

        allow_occupied=True — режим героя: атаковать слабый занятый оазис можно,
        но защита сверяется с max_defense.

        distance — дистанция (клетки) для расчёта кулдауна с учётом возврата войск.
        """
        cache_key = f"{self.current_village_id}_{target_x}_{target_y}"
        cooldown_sec = self._effective_cooldown_sec(distance)

        elapsed = time.time() - self.cooldowns.get(cache_key, 0)
        if elapsed < cooldown_sec:
            left = int((cooldown_sec - elapsed) / 60)
            logging.info(f"⏳ Оазис ({target_x}|{target_y}) на кулдауне (~{left} мин, войска ещё в пути).")
            return "COOLDOWN"

        logging.info(f"⚔️ Набег на ({target_x}|{target_y}) юнитами t{troop_type_index}...")
        self.page.goto(f"{self.config.base_url}/{self.LOCATORS['rally_point_send']}")
        self.page.wait_for_load_state('domcontentloaded')
        time.sleep(random.uniform(1.5, 2.5))

        # ── СВЕЖАЯ ПРОВЕРКА ЖИВОТНЫХ прямо перед отправкой ──
        # Через прямой HTTP (как скан), а НЕ через JS страницы отправки —
        # там мог не сработать api-токен и проверка молча падала, из-за чего
        # войска уходили на оазис с уже заспавненными животными.
        try:
            status = self._fetch_tile(self._get_session(), target_x, target_y)
        except Exception as e:
            logging.warning(f"⚠️ Проверка оазиса ({target_x}|{target_y}) упала: {e}")
            status = {"error": True}

        # Fail-safe: не удалось проверить — НЕ шлём вслепую, цель остаётся в списке.
        if status.get("error"):
            logging.warning(
                f"⚠️ Не удалось проверить оазис ({target_x}|{target_y}) перед набегом "
                f"— атака отменена (без риска нарваться на животных)."
            )
            return "ANIMALS"

        if status.get("is_conquered"):
            logging.warning("🚨 Оазис захвачен игроком! Атака отменена.")
            return "OCCUPIED"

        if status.get("is_occupied"):
            # войска игрока — временное усиление (подмога). Не отправляем
            # войска на убой, но и цель НЕ удаляем: подмога уйдёт — снова фармим.
            if status.get("has_player_troops"):
                logging.warning(
                    f"🛡️ Оазис ({target_x}|{target_y}): войска игрока (подмога). "
                    f"Набег отменён, цель остаётся в списке."
                )
                return "PLAYER_TROOPS"

            fresh_def = self._animal_defense(status.get("animals"))

            if allow_occupied:
                # режим героя: сверяем с расчётным лимитом силы героя
                if max_defense and fresh_def > max_defense:
                    logging.warning(
                        f"🐺 Животных прибавилось: защита {fresh_def} > лимит {max_defense}. Герой НЕ отправлен."
                    )
                    return "ANIMALS"
            else:
                # обычный набег: не отправляем войска на убой к животным.
                # allowed = сколько защиты терпим (по умолч. 0 = вообще никаких).
                allowed = int(self.settings.get("max_animal_defense", 0))
                if fresh_def > allowed:
                    logging.warning(
                        f"🐺 Оазис ({target_x}|{target_y}): появились животные "
                        f"(защита {fresh_def} > допустимо {allowed}). Набег ОТМЕНЁН, "
                        f"цель остаётся в списке."
                    )
                    return "ANIMALS"

        try:
            self.page.locator(self.LOCATORS['coord_x']).fill(str(target_x))
            self.page.locator(self.LOCATORS['coord_y']).fill(str(target_y))
            time.sleep(random.uniform(0.3, 0.8))

            troop_sel = f'input[name="troop[t{troop_type_index}]"], input[name="t{troop_type_index}"]'
            t_input = self.page.locator(troop_sel).first

            if t_input.is_visible() and not t_input.is_disabled():
                t_input.fill(str(troop_count))
                time.sleep(random.uniform(0.3, 0.8))
            else:
                logging.warning(f"⚠️ Войска t{troop_type_index} отсутствуют.")
                return "NO_TROOPS"

            raid_radio = self.page.locator(self.LOCATORS['raid_radio'])
            if raid_radio.is_visible():
                raid_radio.check(force=True)

            self.page.locator(self.LOCATORS['raid_submit_btn']).first.click()
            time.sleep(random.uniform(1.5, 2.5))

            confirm = self.page.locator(self.LOCATORS['raid_confirm_btn']).first
            if confirm.is_visible():
                confirm.click()
                logging.info(f"🚀 {troop_count} юнитов t{troop_type_index} → ({target_x}|{target_y})")
                self.cooldowns[cache_key] = time.time()
                self._save_cooldowns()
                return "SUCCESS"
            else:
                logging.warning("⚠️ Кнопка подтверждения не найдена.")
                return "ERROR"

        except Exception as e:
            logging.error(f"❌ Ошибка атаки: {e}")
            return "ERROR"

    # --- ЭВАКУАЦИЯ (эвазия при атаке) ------------------------------

    def evade_all_troops(self) -> str:
        """
        Настоящая эвакуация: отправляет ВСЕ доступные войска деревни
        ОДНИМ рейдом в ближайший сохранённый оазис.

        Отличия от фарм-цикла:
          - игнорирует кулдауны (спасение важнее)
          - игнорирует troops_per_raid — уводит всё, каждый тип юнитов
          - одна отправка вместо обхода всех целей (быстро — атака на подходе)

        Логика возврата: рейд дойдёт до оазиса и войска сами вернутся домой.
        Атака за это время ударит по пустой деревне.

        Возвращает: SUCCESS | NO_TARGET | NO_TROOPS | ERROR
        """
        self.update_village_identity()
        self._refresh_settings()  # подхватываем evade_target из GUI

        # Цель: приоритет — evade_target из настроек, иначе ближайший оазис
        target = None
        ev = self.settings.get("evade_target")  # {"x": ..., "y": ...} из GUI
        if ev and ev.get("x") is not None:
            target = (int(ev["x"]), int(ev["y"]))
        elif self.load_saved_oases() and self.farm_list:
            # farm_list отсортирован по дистанции — берём ближайший
            near = self.farm_list[0]
            target = (near["x"], near["y"])

        if not target:
            logging.warning("🏃 Эвакуация: нет цели (список оазисов пуст, evade_target не задан).")
            return "NO_TARGET"

        tx, ty = target
        logging.info(f"🏃 ЭВАКУАЦИЯ: увожу ВСЕ войска → ({tx}|{ty})...")
        try:
            self.page.goto(f"{self.config.base_url}/{self.LOCATORS['rally_point_send']}")
            self.page.wait_for_load_state('domcontentloaded')
            time.sleep(random.uniform(1.0, 2.0))

            # Заполняем КАЖДЫЙ тип юнитов максимумом.
            # Максимум берём из ссылки/текста "/ N" рядом с полем ввода —
            # это стандартная разметка формы отправки войск Travian.
            filled = self.page.evaluate(r'''
                () => {
                    let total = 0;
                    document.querySelectorAll(
                        'input[name^="troop"], input[name^="troops"]'
                    ).forEach(inp => {
                        if (inp.disabled || inp.type === 'hidden') return;
                        // максимум: ссылка "/N" в той же ячейке/строке
                        const cell = inp.closest('td') || inp.parentElement;
                        let max = 0;
                        if (cell) {
                            const link = cell.querySelector('a');
                            const src = link ? link.textContent : cell.textContent;
                            const m = String(src).replace(/[\u00A0\s.,]/g, ' ').match(/\/?\s*(\d+)\s*$/) ||
                                      String(src).match(/(\d+)/);
                            if (m) max = parseInt(m[1], 10) || 0;
                        }
                        if (max > 0) {
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value').set;
                            setter.call(inp, String(max));
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                            total += max;
                        }
                    });
                    return total;
                }
            ''')

            if not filled:
                logging.warning("🏃 Эвакуация: в деревне нет войск для увода.")
                return "NO_TROOPS"

            self.page.locator(self.LOCATORS['coord_x']).fill(str(tx))
            self.page.locator(self.LOCATORS['coord_y']).fill(str(ty))
            time.sleep(random.uniform(0.3, 0.8))

            raid_radio = self.page.locator(self.LOCATORS['raid_radio'])
            if raid_radio.is_visible():
                raid_radio.check(force=True)

            self.page.locator(self.LOCATORS['raid_submit_btn']).first.click()
            time.sleep(random.uniform(1.5, 2.5))

            confirm = self.page.locator(self.LOCATORS['raid_confirm_btn']).first
            if confirm.is_visible():
                confirm.click()
                logging.info(f"✅ ЭВАКУАЦИЯ: ~{filled} юнитов уведено → ({tx}|{ty}). Вернутся сами.")
                return "SUCCESS"
            logging.warning("🏃 Эвакуация: кнопка подтверждения не найдена.")
            return "ERROR"
        except Exception as e:
            logging.error(f"❌ Эвакуация не удалась: {e}")
            return "ERROR"

    # --- ФАРМ ------------------------------------------------------

    def _read_home_troops(self, indices: list[int]) -> dict:
        """
        Читает кол-во своих ДОМАШНИХ войск для указанных типов с вкладки
        «Войска» точки сбора (build.php?id=39&gid=16&tt=1).

        Разметка (как в TroopTrainer.get_current_count): блок ровно
        `.troop_details` (без outHero), строка `.units.last tr`, ячейки `.unit`
        по порядку (1-я = t1, 2-я = t2, ...); класс `.none` = войск этого типа нет.

        Возвращает {index: count}. Значение -1 = прочитать не удалось — тогда
        фарм не блокируем (шлём как раньше), но пишем предупреждение в лог.
        """
        result = {ti: -1 for ti in indices}
        try:
            self.page.goto(f"{self.config.base_url}/{self.LOCATORS['rally_point_troops']}")
            self.page.wait_for_load_state('domcontentloaded')
            time.sleep(random.uniform(1.0, 2.0))
            counts = self.page.evaluate(r'''
                () => {
                    // Берём ТОЛЬКО блок с классом ровно "troop_details"
                    // (пропускаем troop_details outHero и прочие варианты).
                    const blocks = document.querySelectorAll('.troop_details');
                    let home = null;
                    for (const b of blocks) {
                        const cls = (b.getAttribute('class') || '').trim().split(/\s+/);
                        if (cls.length === 1 && cls[0] === 'troop_details') { home = b; break; }
                    }
                    if (!home) {
                        for (const b of blocks) {
                            if (!b.classList.contains('outHero')) { home = b; break; }
                        }
                    }
                    if (!home) return null;
                    const row = home.querySelector('.units.last tr') ||
                                home.querySelector('.units tr');
                    if (!row) return null;
                    const cells = row.querySelectorAll('.unit');
                    if (!cells.length) return null;
                    const out = [];
                    cells.forEach(cell => {
                        if (cell.classList.contains('none')) { out.push(0); return; }
                        const n = parseInt(cell.textContent.replace(/\D/g, ''), 10);
                        out.push(isNaN(n) ? 0 : n);
                    });
                    return out;  // 1-based позиция: out[0]=t1, out[1]=t2, ...
                }
            ''')
            if counts:
                for ti in indices:
                    pos = ti - 1
                    if 0 <= pos < len(counts):
                        result[ti] = int(counts[pos])
            else:
                logging.warning(
                    "⚠️ Не удалось прочитать домашние войска (tt=1) — "
                    "фарм по старой логике (без проверки запаса)."
                )
        except Exception as e:
            logging.warning(f"⚠️ Ошибка чтения домашних войск: {e}")
        return result

    def run_farm_cycle(self, force_rescan: bool = False, force_send: bool = False):
        """
        Полный фарм-цикл:
          1. Если список пуст или force_rescan=True — сканируем
          2. Отправляем войска ко всем целям в списке
        Возвращает True если были успешные набеги, False если ничего не сделано.

        force_send=True — игнорировать тумблер farm_enabled
        (используется эвазией: войска надо вывести даже при выключенном фарме).
        ВАЖНО: в режиме force_send скан НИКОГДА не запускается —
        эвазия работает только по уже сохранённому списку целей.
        """
        # Защита на уровне модуля: тумблер GUI уважается даже при
        # вызове в обход планировщика (menu_manager и т.д.)
        farm_on = not self.settings_store or self.settings_store.feature('farm_enabled', True)
        if not force_send and not farm_on:
            logging.info("⏭️ Фарм выключен в настройках — пропуск (скан не запускается).")
            return False

        self._refresh_settings()  # живые настройки из GUI
        troops   = self.settings.get("troops_per_raid", 10)
        max_dist = self.settings.get("max_distance", 0.0)

        # Список юнитов для фарма: поддерживает как старый одиночный troop_type_index,
        # так и новый farm_troop_indices (несколько юнитов — чередуются по целям).
        _raw_indices = self.settings.get("farm_troop_indices") or []
        if isinstance(_raw_indices, (int, float)):
            _raw_indices = [int(_raw_indices)]
        troop_indices = [int(x) for x in _raw_indices if x]
        if not troop_indices:
            troop_indices = [int(self.settings.get("troop_type_index", 1))]
        # legacy-совместимость: troop_type = первый выбранный юнит
        troop_type = troop_indices[0]

        # Шаг 1: скан если нужно.
        # FIX: скан разрешён ТОЛЬКО когда фарм включён в GUI.
        # Раньше эвазия (force_send=True) при пустом списке запускала скан,
        # игнорируя выключенный тумблер farm_enabled.
        has_list = self.load_saved_oases()
        if (not has_list or force_rescan) and farm_on:
            logging.info("📡 Запускаю скан оазисов...")
            center_x, center_y = self.get_current_village_coords()
            self.scan_oases_around(center_x, center_y)
            self.load_saved_oases()
        elif not has_list:
            logging.info("⏭️ Списка целей нет, а фарм выключен — скан пропущен.")
            return False

        def _feat(name: str) -> bool:
            return bool(
                self.settings_store.feature(name, False)
                if self.settings_store else self.settings.get(name, False)
            )

        # Режим "только героем" (ранний старт): вместо волны войск
        # одна безопасная атака героем по слабому/пустому оазису.
        # Флаг живёт в features (тумблер в GUI), не в farm-секции.
        hero_only = _feat("hero_only")
        if not force_send and hero_only:
            return self.run_hero_farm()

        # Комбинированный режим "герой + войска": в одном цикле герой ходит
        # по оазисам С ЖИВОТНЫМИ (безопасно, по силе), а войска — по ПУСТЫМ
        # оазисам (обычная волна ниже). Это раздельная работа: герой и войска
        # не пересекаются по целям. Героя отправляем первым (одна атака).
        hero_with_troops = _feat("hero_with_troops")
        hero_sent = False
        if not force_send and hero_with_troops:
            logging.info("🦸+🚜 Комбо-фарм: герой — по животным, войска — по пустым.")
            hero_sent = self.run_hero_farm()

        if not self.farm_list:
            if hero_sent:
                logging.info("🤷 Пустых оазисов нет, но герой уже отправлен.")
                return True
            logging.warning("🤷 Список оазисов пуст. Нечего атаковать.")
            return False

        # Шаг 2: фильтр и сортировка
        self.farm_list.sort(key=lambda o: o.get('distance', 999))
        if max_dist > 0:
            before = len(self.farm_list)
            self.farm_list = [o for o in self.farm_list if o.get('distance', 0) <= max_dist]
            logging.info(f"📏 Фильтр дистанции (<= {max_dist}): убрано {before - len(self.farm_list)} целей.")
            if not self.farm_list:
                return False

        # Шаг 3: атака
        types_str = "+".join(f"t{i}" for i in troop_indices)
        logging.info(f"🚜 Отправка войск: {len(self.farm_list)} целей | {troops} юнитов ({types_str})")
        # Запас домашних войск читаем ОДИН раз за цикл. Если какого-то типа
        # меньше, чем нужно на полную отправку (troops), остаток НЕ шлём вовсе.
        home_troops = self._read_home_troops(troop_indices)
        sent = 0
        skipped_animals = 0
        occupied_now = []
        # Типы войск, у которых юниты закончились в этом цикле. Исключаем их
        # из ротации, но продолжаем остальными — раньше первый же NO_TROOPS
        # обрывал весь фарм, из-за чего второй тип переставал ходить.
        exhausted = set()
        rr = 0  # указатель round-robin среди ДОСТУПНЫХ типов

        def _available():
            return [ti for ti in troop_indices if ti not in exhausted]

        try:
            for oasis in self.farm_list:
                available = _available()
                if not available:
                    logging.info("🛑 Все выбранные типы войск закончились. Стоп.")
                    break

                # Пытаемся отправить цель одним из доступных типов (по кругу).
                # Если у выбранного типа нет войск — исключаем его и пробуем
                # СЛЕДУЮЩИЙ тип на ЭТУ ЖЕ цель (цель не теряем).
                result = None
                while available:
                    current_troop = available[rr % len(available)]
                    # Проверка запаса ДО отправки: если войск типа меньше, чем
                    # нужно на полную волну (troops) — остаток НЕ шлём, а тип
                    # исключаем из цикла (дальше он только уменьшится) и пробуем
                    # следующий доступный тип на эту же цель.
                    have = home_troops.get(current_troop, -1)
                    if have != -1 and have < troops:
                        logging.info(
                            f"🚫 Войск t{current_troop} меньше нормы отправки "
                            f"({have} < {troops}) — остаток не шлём, тип исключён из цикла."
                        )
                        exhausted.add(current_troop)
                        available = _available()
                        continue
                    result = self.attack_oasis(
                        oasis['x'], oasis['y'], troops, current_troop,
                        distance=oasis.get('distance', 0.0),
                    )
                    if result == "NO_TROOPS":
                        exhausted.add(current_troop)
                        logging.info(f"🚫 Войска t{current_troop} закончились — исключаю из ротации.")
                        available = _available()
                        continue
                    if result == "SUCCESS" and have != -1:
                        # Локально вычитаем отправленных — следующей цели уйдёт
                        # из остатка, и гейт сработает, когда запас < troops.
                        home_troops[current_troop] = have - troops
                    break

                if not available:
                    logging.info("🛑 Не осталось типов войск с достаточным запасом. Стоп.")
                    break

                if result == "OCCUPIED":
                    # захвачен игроком (оккупация) — убираем насовсем
                    occupied_now.append((oasis['x'], oasis['y']))
                if result in ("ANIMALS", "PLAYER_TROOPS"):
                    # временное препятствие (животные/подмога) — цель НЕ удаляем,
                    # просто пропускаем этот круг (уйдут — снова фармим)
                    skipped_animals += 1
                if result == "SUCCESS":
                    sent += 1
                    rr += 1  # следующая цель — следующим типом (чередование)
                    self.farm_stats.record_raid(
                        oasis['x'], oasis['y'], current_troop, troops,
                        oasis.get('distance', 0.0),
                    )
                    time.sleep(random.uniform(2.5, 4.5))
        except KeyboardInterrupt:
            logging.info("🛑 Фарм прерван.")

        # Сохраняем накопленную статистику один раз за цикл.
        if sent:
            self.farm_stats.save()

        if occupied_now:
            self.farm_list = [
                o for o in self.farm_list if (o['x'], o['y']) not in occupied_now
            ]
            self._save_to_json(self._file("unoccupied_oases"), self.current_village_id, self.farm_list)
            logging.info(f"🚩 Удалено занятых целей из списка: {len(occupied_now)}")

        msg = f"🏁 Фарм завершён. Отправлено набегов: {sent}"
        if skipped_animals:
            msg += f" | пропущено из-за животных: {skipped_animals}"
        logging.info(msg)
        self.page.goto(f"{self.config.base_url}/{self.LOCATORS['village_view']}")
        self.page.wait_for_load_state('domcontentloaded')
        return sent > 0 or hero_sent

    def auto_farm(self):
        """Legacy-обёртка для совместимости."""
        self.run_farm_cycle()

    # --- НАСТРОЙКИ -------------------------------------------------

    def save_settings(self, new_settings: dict):
        """
        Обновляет self.settings и сохраняет на диск в farm_settings.json.
        Вызывается из menu_manager (пункт 7 меню).
        """
        self.settings.update(new_settings)
        try:
            with open('farm_settings.json', 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
            logging.info(f"✅ Настройки фарма сохранены: {self.settings}")
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения настроек: {e}")

    def load_settings(self):
        """
        Загружает настройки из farm_settings.json (если файл есть).
        Вызывать при инициализации бота.
        """
        try:
            with open('farm_settings.json', 'r', encoding='utf-8') as f:
                saved = json.load(f)
            self.settings.update(saved)
            logging.info(f"📥 Настройки фарма загружены: {self.settings}")
        except FileNotFoundError:
            logging.debug("suppressed error in actions/oasis_action:1115", exc_info=True)
        except Exception as e:
            logging.warning(f"⚠️ Не удалось загрузить настройки: {e}")
