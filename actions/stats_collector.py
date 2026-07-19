"""
Сборщик статистики аккаунта: ресурсы, войска, герой.

Лёгкая задача планировщика — один заход на dorf1.php, всё берём
с одной страницы (ресурсы, войска в деревне, статус героя из сайдбара).
Пишет stats_{name}.json — его читает GUI (app.py).

Атаки сюда НЕ парсим повторно: их уже отслеживает поток attack_monitor
в runner.py, он и передаёт список через set_attacks().
"""
import json
import logging
import threading
from datetime import datetime


class StatsCollector:
    def __init__(self, page, config):
        self.page = page
        self.config = config
        self._attacks_lock = threading.Lock()
        self._attacks: list = []

    # --- вызывается из потока монитора атак (thread-safe) ----------

    def set_attacks(self, attacks: list):
        """attacks: [{'from_x': .., 'from_y': .., 'arrival': .., 'count': ..}, ...]"""
        with self._attacks_lock:
            self._attacks = list(attacks)

    def get_attacks(self) -> list:
        with self._attacks_lock:
            return list(self._attacks)

    # --- основная задача (владеет страницей эксклюзивно) -----------

    def collect(self):
        """
        Собирает статистику ПО КАЖДОЙ ДЕРЕВНЕ и пишет stats_{name}.json.
        FIX: раньше статистика бралась только с текущей (последней активной)
        деревни — при 2+ деревнях данные были только из одной.
        """
        base_url = getattr(self.config, 'base_url', None) or self.config.server_url
        if "dorf1.php" not in self.page.url:
            self.page.goto(f"{base_url}/dorf1.php")
            self.page.wait_for_load_state("domcontentloaded")

        villages = self._get_villages()
        village_stats = []
        for v in villages:
            try:
                if v.get("id"):
                    self.page.goto(f"{base_url}/dorf1.php?newdid={v['id']}")
                    self.page.wait_for_load_state("domcontentloaded")
                village_stats.append({
                    "id": v.get("id"),
                    "name": v.get("name") or "Деревня",
                    "resources": self._get_resources(),
                    "troops": self._get_troops(),
                    "build_queue": self._get_build_queue(),
                })
            except Exception as e:
                logging.warning(f"📊 Ошибка сбора по деревне {v}: {e}")

        first = village_stats[0] if village_stats else {}
        stats = {
            "villages": village_stats,
            # legacy-поля (совместимость со старым GUI) = первая деревня
            "resources": first.get("resources", {}),
            "troops": first.get("troops", []),
            "build_queue": first.get("build_queue", []),
            "hero": self._get_hero(),
            "account": self._get_account_info(),
            "attacks": self.get_attacks(),
            "updated_at": datetime.now().isoformat(),
        }
        # Сохраняем прогресс кузницы, записанный SmithyUpgrader — collect()
        # пересобирает stats с нуля и иначе затёр бы этот ключ.
        prev_smithy = self._load_existing().get("smithy")
        if prev_smithy is not None:
            stats["smithy"] = prev_smithy
        self._save(stats)
        logging.info(
            "📊 Статистика собрана: "
            f"деревень={len(village_stats)}, "
            f"герой={'ok' if stats['hero'] else '—'}, "
            f"атак={len(stats['attacks'])}"
        )
        return stats

    def _get_villages(self) -> list:
        """
        Список деревень {id, name} из сайдбара.
        Активная деревня может не иметь newdid в ссылке — тогда id=None
        (значит переключаться не надо, мы уже на ней).
        """
        try:
            villages = self.page.evaluate(r'''
                () => {
                    const out = [];
                    document.querySelectorAll(
                        '.villageList .listEntry, #sidebarBoxVillages .listEntry'
                    ).forEach(node => {
                        let id = node.dataset.did || null;
                        if (!id) {
                            const a = node.querySelector('a[href*="newdid"]');
                            if (a) { const m = a.href.match(/newdid=(\d+)/); if (m) id = m[1]; }
                        }
                        const nameEl = node.querySelector('.name, a .name, a');
                        const name = nameEl ? nameEl.textContent.trim().slice(0, 40) : '';
                        out.push({ id, name, active: node.classList.contains('active') });
                    });
                    return out;
                }
            ''') or []
            # активную деревню обходим первой (мы уже на ней — без лишнего goto)
            villages.sort(key=lambda v: not v.get("active"))
            if villages and villages[0].get("active"):
                villages[0]["id"] = None
            return villages or [{"id": None, "name": "Деревня"}]
        except Exception as e:
            logging.debug(f"stats villages error: {e}")
            return [{"id": None, "name": "Деревня"}]

    # --- парсеры ----------------------------------------------------

    def _get_resources(self) -> dict:
        """
        Ресурсы + производство + ёмкость. Источники (по очереди):
          1. window.resources (Travian Legends кладёт данные в JS)
          2. стокбар: #l1..#l4 / .stockBarButton .value
          3. производство — таблица #production на dorf1
        """
        try:
            out = self.page.evaluate(r'''
                () => {
                    const keys = ['wood', 'clay', 'iron', 'crop'];
                    const out = { storage: {}, production: {}, capacity: {}, _src: '' };
                    const num = t => {
                        if (t == null) return 0;
                        // Travian использует юникод-минус \u2212 и NBSP-разделители
                        const s = String(t).replace(/[\u202C\u202D\u200E\u200F\u200B\uFEFF\u00A0\s,.]/g, '')
                                           .replace(/\u2212/g, '-');
                        const m = s.match(/-?\d+/);
                        return m ? parseInt(m[0], 10) : 0;
                    };

                    // --- 1) window.resources -------------------------
                    const R = window.resources;
                    if (R && (R.storage || R.production)) {
                        keys.forEach((k, i) => {
                            const id = 'l' + (i + 1);
                            out.storage[k]    = Math.floor((R.storage    || {})[id] || 0);
                            out.production[k] = Math.floor((R.production || {})[id] || 0);
                            out.capacity[k]   = Math.floor((R.maxStorage || {})[id] || 0);
                        });
                        out._src = 'window.resources';
                        if (Object.values(out.storage).some(v => v > 0)) return out;
                    }

                    // --- 2) стокбар (разные версии разметки) ---------
                    const stockSel = i => (
                        document.getElementById('l' + i) ||
                        document.querySelector('#stockBarResource' + i + ' .value') ||
                        document.querySelector('.stockBarButton:nth-of-type(' + i + ') .value')
                    );
                    keys.forEach((k, i) => {
                        out.storage[k] = num(stockSel(i + 1)?.textContent);
                    });
                    const whCap = num(document.querySelector(
                        '#stockBarWarehouse .capacity .value, #stockBarWarehouse .value, .warehouse .capacity'
                    )?.textContent);
                    const grCap = num(document.querySelector(
                        '#stockBarGranary .capacity .value, #stockBarGranary .value, .granary .capacity'
                    )?.textContent);
                    keys.forEach((k, i) => { out.capacity[k] = i === 3 ? grCap : whCap; });

                    // --- 3) производство: таблица #production --------
                    const prodRows = document.querySelectorAll('#production tbody tr, table#production tr');
                    prodRows.forEach((tr, i) => {
                        if (i < 4) {
                            const numTd = tr.querySelector('td.num');
                            if (numTd) out.production[keys[i]] = num(numTd.textContent);
                        }
                    });
                    out._src = 'dom';
                    return out;
                }
            ''') or {}
            # Свободное зерно (прокорм) — отдельным запросом, работает для
            # обоих источников (window.resources его не отдаёт)
            try:
                free_crop = self.page.evaluate(r'''
                    () => {
                        const el = document.querySelector('.granary.stockBarButton #stockBarFreeCrop')
                                || document.querySelector('#stockBarFreeCrop')
                                || document.querySelector('.freeCrop_small .value, .freeCrop .value');
                        if (!el) return null;
                        const s = String(el.textContent || '')
                            .replace(/[\u202C\u202D\u200E\u200F\u200B\uFEFF\u00A0\s,.]/g, '')
                            .replace(/\u2212/g, '-');
                        const m = s.match(/-?\d+/);
                        return m ? parseInt(m[0], 10) : null;
                    }
                ''')
                if free_crop is not None:
                    out["free_crop"] = int(free_crop)
            except Exception as fe:
                logging.debug(f"free crop stats error: {fe}")
            src = out.pop("_src", "?")
            if not any(out.get("storage", {}).values()):
                logging.warning(f"📊 Ресурсы не распарсились (источник: {src}). URL: {self.page.url}")
            return out
        except Exception as e:
            logging.warning(f"📊 stats resources error: {e}")
            return {}

    def _get_troops(self) -> list:
        """
        Войска в текущей деревне. Пробует несколько вариантов разметки:
          - dorf1: таблица #troops (классическая)
          - dorf1: блок .villageInfobox .troops / [class*="troop"]
        """
        try:
            troops = self.page.evaluate(r'''
                () => {
                    const out = [];
                    const num = t => {
                        const s = String(t || '').replace(/[\u00A0\s,.]/g, '');
                        const m = s.match(/\d+/);
                        return m ? parseInt(m[0], 10) : 0;
                    };
                    const unitFromClass = cls => {
                        const m = String(cls || '').match(/(?:^|\s)u(\d{1,2})(?:\s|$)/) ||
                                  String(cls || '').match(/unit u?(\d{1,2})/);
                        return m ? 'u' + m[1] : '';
                    };

                    // Вариант 1: таблица #troops (tbody может отсутствовать)
                    let rows = document.querySelectorAll('#troops tr, table.troop_details tr');
                    rows.forEach(tr => {
                        const img = tr.querySelector('img[class*="u"], i[class*="unit"], td.ico img');
                        const numEl = tr.querySelector('td.num');
                        const nameEl = tr.querySelector('td.un');
                        if (!numEl && !nameEl) return;
                        const count = num((numEl || {}).textContent);
                        const unit = img ? unitFromClass(img.className) : '';
                        const name = nameEl ? nameEl.textContent.trim() : unit;
                        if ((name || unit) && count > 0) out.push({ unit, name, count });
                    });
                    if (out.length) return out;

                    // Вариант 2: инфобокс деревни (новая разметка)
                    document.querySelectorAll(
                        '.villageInfobox.troops tr, [class*="troopsBlock"] tr, .troops_wrapper tr'
                    ).forEach(tr => {
                        const icon = tr.querySelector('[class*="unit"], img');
                        const count = num(tr.textContent);
                        if (icon && count > 0) {
                            const unit = unitFromClass(icon.className);
                            const name = (icon.getAttribute('alt') || icon.getAttribute('title') || unit || '').trim();
                            out.push({ unit, name, count });
                        }
                    });
                    return out;
                }
            ''') or []
            if not troops:
                logging.info("📊 Войска: таблица не найдена или в деревне пусто.")
            return troops
        except Exception as e:
            logging.warning(f"📊 stats troops error: {e}")
            return []

    def _get_build_queue(self) -> list:
        """
        Текущая очередь строительства деревни (что строится и сколько осталось).
        Берётся из .buildingList на dorf1/dorf2 (список задач .name + таймер).
        Возвращает [{'name': .., 'level': .., 'seconds': int, 'timer': 'чч:мм:сс'}]
        """
        try:
            queue = self.page.evaluate(r'''
                () => {
                    const out = [];
                    const items = document.querySelectorAll(
                        '.buildingList ul li, .constructionList li, #build .buildingList li'
                    );
                    items.forEach(li => {
                        const nameEl = li.querySelector('.name');
                        const timerEl = li.querySelector('.timer, span.timer, .buildDuration .timer');
                        if (!nameEl) return;

                        // Целевой уровень хранится в .lvl (то, до чего строим)
                        let targetLevel = null;
                        const lvlEl = li.querySelector('.lvl, .level');
                        if (lvlEl) {
                            const m = lvlEl.textContent.match(/\d+/);
                            if (m) targetLevel = parseInt(m[0], 10);
                        }

                        // Чистое имя: берём только название без числа уровня
                        // (Travian пишет "Склад Уровень 8" — убираем числовую часть в конце)
                        let name = nameEl.textContent.replace(/\s+/g, ' ').trim();
                        // Удаляем хвост вида " Уровень 8" / " Level 8" / " 8" если он дублирует lvlEl
                        if (lvlEl && targetLevel !== null) {
                            name = name.replace(lvlEl.textContent.trim(), '').replace(/\s+/g, ' ').trim();
                        }

                        // секунды: атрибут value таймера (Travian кладёт остаток в секундах)
                        let seconds = null, timer = '';
                        if (timerEl) {
                            const v = timerEl.getAttribute('value');
                            if (v && /^\d+$/.test(v)) seconds = parseInt(v, 10);
                            timer = timerEl.textContent.trim();
                        }
                        out.push({ name, target_level: targetLevel, seconds, timer });
                    });
                    return out;
                }
            ''') or []
            return queue
        except Exception as e:
            logging.debug(f"build queue error: {e}")
            return []

    def _get_account_info(self) -> dict:
        """
        Аккаунт-уровневая информация (не привязана к деревне):
          - gold, silver (валюта из топбара);
          - premium (Travian Plus / Золотой клуб активны?);
          - beginner_protection (защита новичка: осталось времени / активна).
        Все поля best-effort: если что-то не найдено — просто отсутствует.
        """
        try:
            info = self.page.evaluate(r'''
                () => {
                    const out = {};
                    const num = t => {
                        const s = String(t || '').replace(/[\u202C\u202D\u200E\u200F\u200B\uFEFF\u00A0\s,.]/g, '');
                        const m = s.match(/\d+/);
                        return m ? parseInt(m[0], 10) : null;
                    };

                    // --- Золото / серебро ---
                    // Разметка: .currency .value.ajaxReplaceableGoldAmount / ...SilverAmount
                    const goldEl = document.querySelector(
                        '.currency .value.ajaxReplaceableGoldAmount, .value.ajaxReplaceableGoldAmount, .ajaxReplaceableGoldAmount'
                    );
                    const silverEl = document.querySelector(
                        '.currency .value.ajaxReplaceableSilverAmount, .value.ajaxReplaceableSilverAmount, .ajaxReplaceableSilverAmount'
                    );
                    if (goldEl)   out.gold   = num(goldEl.textContent);
                    if (silverEl) out.silver = num(silverEl.textContent);

                    // --- Премиум (Travian Plus) ---
                    // Надёжный источник: GraphQL viewData в inline-скрипте VillageBoxes
                    // содержит goldFeatures.travianPlus.isActive и goldClub.
                    const html = document.documentElement.innerHTML;
                    let plusActive = /"travianPlus"\s*:\s*\{\s*"isActive"\s*:\s*true/.test(html);
                    const goldClub = /"goldClub"\s*:\s*true/.test(html);
                    out.premium = plusActive;
                    out.gold_club = goldClub;

                    // --- Инфобокс (#sidebarBoxInfobox): таймеры премиума/защиты ---
                    // Собираем все строки li с их текстом и таймером (секунды в value).
                    const infoItems = [];
                    document.querySelectorAll('#sidebarBoxInfobox .content ul li').forEach(li => {
                        const timerEl = li.querySelector('.timer, [value]');
                        let seconds = null, timerTxt = '';
                        if (timerEl) {
                            const v = timerEl.getAttribute('value');
                            if (v && /^\d+$/.test(v)) seconds = parseInt(v, 10);
                            timerTxt = timerEl.textContent.trim();
                        }
                        // подпись строки (без таймера)
                        const label = li.textContent.replace(timerTxt, '').replace(/\s+/g, ' ').trim();
                        const cls = li.getAttribute('class') || '';
                        infoItems.push({ label: label.slice(0, 60), seconds, timer: timerTxt, cls });
                    });
                    if (infoItems.length) out.infobox = infoItems;

                    // --- Защита новичка ---
                    // Ищем среди инфобокса строку про защиту (beginner / новичк / protection),
                    // иначе отдельный баннер beginnerProtection.
                    const bpItem = infoItems.find(i =>
                        /(новичк|защит|beginner|protection|schutz)/i.test(i.label) ||
                        /(beginner|protection)/i.test(i.cls)
                    );
                    if (bpItem) {
                        out.beginner_protection = true;
                        if (bpItem.seconds != null) out.beginner_protection_seconds = bpItem.seconds;
                        else if (bpItem.timer)      out.beginner_protection_text = bpItem.timer;
                        else                        out.beginner_protection_text = bpItem.label;
                    } else {
                        const bp = document.querySelector(
                            '.beginnerProtection, [class*="beginnerProtection"], #beginnerProtection'
                        );
                        if (bp) {
                            out.beginner_protection = true;
                            const t = bp.querySelector('.timer, [value]');
                            if (t) {
                                const v = t.getAttribute('value');
                                if (v && /^\d+$/.test(v)) out.beginner_protection_seconds = parseInt(v, 10);
                            }
                        } else {
                            out.beginner_protection = false;
                        }
                    }
                    return out;
                }
            ''') or {}
            return {k: v for k, v in info.items() if v is not None}
        except Exception as e:
            logging.debug(f"account info error: {e}")
            return {}

    def _get_hero(self) -> dict:
        """
        Герой: HP, уровень, опыт, статус.
        Источник №1 — официальный API Travian Legends /api/v1/hero/dataForHUD
        (его использует сам интерфейс игры — селекторы не нужны вообще).
        Fallback — DOM топбара/сайдбара.
        """
        # --- 1) API HUD: самый надёжный источник -------------------
        try:
            hud = self.page.evaluate(r'''
                async () => {
                    try {
                        const r = await fetch('/api/v1/hero/dataForHUD', {
                            headers: { 'Accept': 'application/json' },
                            credentials: 'same-origin',
                        });
                        if (!r.ok) return null;
                        return await r.json();
                    } catch (e) { return null; }
                }
            ''')
            if hud and isinstance(hud, dict):
                hero = {}
                # ключи в разных версиях: health / healthPercent; level; experiencePercent
                for k_src, k_dst in (
                    ("health", "health"), ("healthPercent", "health"),
                    ("level", "level"),
                    ("experience", "experience"), ("experiencePercent", "experience_pct"),
                ):
                    v = hud.get(k_src)
                    if v is not None and k_dst not in hero:
                        try:
                            hero[k_dst] = int(float(v))
                        except (TypeError, ValueError):
                            logging.debug("suppressed error in actions/stats_collector:451", exc_info=True)
                if "statusInlineIcon" in hud or "heroStatus" in hud:
                    hero["status"] = str(hud.get("heroStatus") or "")[:80] or None
                if hero.get("health") is not None or hero.get("level") is not None:
                    return {k: v for k, v in hero.items() if v is not None}
        except Exception as e:
            logging.debug(f"hero HUD api error: {e}")

        # --- 2) Fallback: DOM ---------------------------------------
        try:
            hero = self.page.evaluate(r'''
                () => {
                    const out = {};
                    const num = t => { const m = String(t || '').replace(',', '.').match(/-?\d+(\.\d+)?/); return m ? Math.round(parseFloat(m[0])) : null; };

                    // HP: title/значение в топбаре или сайдбаре
                    for (const sel of [
                        '#topBarHero .health [title]', '.heroHealthBarBox [title]',
                        '#heroImageButton [title]', '#sidebarBoxHero .health .value',
                        '.heroStatus .health',
                    ]) {
                        const el = document.querySelector(sel);
                        if (el) { out.health = num(el.getAttribute('title') ?? el.textContent); if (out.health != null) break; }
                    }
                    // SVG-круг HP (Legends): процент в stroke-dasharray
                    if (out.health == null) {
                        const c = document.querySelector('.heroHealthBarBox svg circle[stroke-dasharray], #heroImageButton svg path[title]');
                        if (c) out.health = num(c.getAttribute('stroke-dasharray') || c.getAttribute('title'));
                    }

                    for (const sel of [
                        '#topBarHero .level .value', '#sidebarBoxHero .level .value',
                        '.heroLevel', '#heroImageButton .labelLayer',
                    ]) {
                        const el = document.querySelector(sel);
                        if (el) { out.level = num(el.textContent); if (out.level != null) break; }
                    }

                    const xpEl = document.querySelector('#sidebarBoxHero .experience .value, .heroExperience');
                    if (xpEl) out.experience = num(xpEl.getAttribute('value') ?? xpEl.textContent);

                    const statusEl = document.querySelector('.heroStatusMessage, #sidebarBoxHero .heroStatus');
                    if (statusEl) out.status = statusEl.textContent.trim().slice(0, 80);
                    return out;
                }
            ''') or {}
            if hero.get("health") is None and hero.get("level") is None:
                logging.info("📊 Герой: не удалось распарсить ни через API, ни через DOM.")
            return {k: v for k, v in hero.items() if v is not None}
        except Exception as e:
            logging.warning(f"📊 stats hero error: {e}")
            return {}

    # --- сохранение --------------------------------------------------

    def _stats_path(self):
        from utils.paths import account_file
        name = getattr(self.config, 'name', 'bot')
        return account_file(name, 'stats')

    def _load_existing(self) -> dict:
        """Читает текущий stats-файл аккаунта (или {} если нет/битый)."""
        try:
            with open(self._stats_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, stats: dict):
        path = str(self._stats_path())
        tmp = path + ".tmp"
        try:
            import os
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            logging.warning(f"⚠️ Не удалось записать {path}: {e}")

    def save_attacks_only(self):
        """
        Обновляет ТОЛЬКО список атак в существующем stats-файле.
        Вызывается из потока монитора — БЕЗ обращения к странице.
        """
        try:
            with open(self._stats_path(), "r", encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            stats = {"villages": [], "resources": {}, "troops": [], "hero": {}}
        stats["attacks"] = self.get_attacks()
        stats["updated_at"] = datetime.now().isoformat()
        self._save(stats)
