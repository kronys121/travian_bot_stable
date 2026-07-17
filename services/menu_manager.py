import logging
import time
import random
from actions.adventure_action import HeroAdventure
from actions.tasks_action import TasksAction
from services.smart_builder import SmartBuilder
from actions.oasis_action import FarmManager


class MenuManager:
    def __init__(self, page, smart_builder: SmartBuilder, adventure_action: HeroAdventure,
                 tasks_action: TasksAction, farm_manager: FarmManager, config,
                 attack_monitor=None, troop_trainer=None, trade_manager=None,
                 settings_store=None):
        self.page             = page
        self.smart_builder    = smart_builder
        self.adventure_action = adventure_action
        self.tasks_action     = tasks_action
        self.farm_manager     = farm_manager
        self.config           = config
        self.attack_monitor   = attack_monitor
        self.troop_trainer    = troop_trainer
        self.trade_manager    = trade_manager
        self._settings_store  = settings_store  # для _get_build_plan_for_village

    def get_all_villages(self):
        """
        [MULTI-VILLAGE]
        Парсит правое меню и собирает уникальные ID всех деревень аккаунта.
        Возвращает список ID (например: ['29831', '34012']).
        Если деревня одна, вернёт [None].
        """
        try:
            # Переходим в обзор деревни, чтобы меню гарантированно загрузилось
            self.page.goto(f"{self.config.base_url}/dorf1.php")
            time.sleep(random.uniform(1.0, 2.0))

            villages = self.page.evaluate(r'''
            () => {
                const nodes = document.querySelectorAll(
                    '.villageList .listEntry, #sidebarBoxVillages .listEntry'
                );
                const vids = new Set();
                nodes.forEach(node => {
                    // 1) data-did (современные сервера)
                    if (node.dataset.did) {
                        vids.add(node.dataset.did);
                        return;
                    }
                    // 2) data-sortid
                    if (node.dataset.sortid) {
                        const match = node.dataset.sortid.match(/\d+/);
                        if (match) { vids.add(match[0]); return; }
                    }
                    // 3) href?newdid= (неактивные деревни)
                    const a = node.querySelector('a[href*="newdid"]');
                    if (a) {
                        const match = a.href.match(/newdid=(\d+)/);
                        if (match) { vids.add(match[1]); return; }
                    }
                    // 4) Активная деревня: class="listEntry village active"
                    //    Ссылка не содержит newdid, ищем любую ссылку на деревню
                    if (node.classList.contains('active')) {
                        const anyA = node.querySelector('a');
                        if (anyA) {
                            // Извлекаем did из href даже без newdid
                            const m = anyA.href.match(/dorf1\.php\?[^"]*did=(\d+)/) ||
                                      anyA.href.match(/(\d{4,})/);  // fallback: любой длинный номер
                            if (m) vids.add(m[1]);
                        }
                    }
                });
                return Array.from(vids);
            }
            ''')

            if not villages:
                logging.info("🏰 Найдена только 1 деревня на аккаунте.")
                return [None]

            logging.info(f"🏰 Найдено деревень: {len(villages)} -> {villages}")
            return villages

        except Exception as e:
            logging.error(f"❌ Ошибка при поиске деревень: {e}")
            return [None]

    def get_villages_detailed(self):
        """
        [MULTI-VILLAGE] Список деревень с именами и РЕАЛЬНЫМИ id (включая активную).
        Возвращает [{'id': '29831', 'name': 'Столица'}, ...].
        Нужно для переброски ресурсов: правило ссылается на деревню-донора по имени,
        а навигация к ней делается по id (newdid).
        """
        try:
            self.page.goto(f"{self.config.base_url}/dorf1.php")
            time.sleep(random.uniform(1.0, 2.0))
            villages = self.page.evaluate(r'''
            () => {
                const out = [];
                document.querySelectorAll(
                    '.villageList .listEntry, #sidebarBoxVillages .listEntry'
                ).forEach(node => {
                    let id = node.dataset.did || null;
                    if (!id && node.dataset.sortid) {
                        const m = node.dataset.sortid.match(/\d+/); if (m) id = m[0];
                    }
                    if (!id) {
                        const a = node.querySelector('a[href*="newdid"]');
                        if (a) { const m = a.href.match(/newdid=(\d+)/); if (m) id = m[1]; }
                    }
                    if (!id) {
                        const a = node.querySelector('a');
                        if (a) { const m = a.href.match(/(\d{4,})/); if (m) id = m[1]; }
                    }
                    const nameEl = node.querySelector('.name, a .name, a');
                    const name = nameEl ? nameEl.textContent.trim().slice(0, 40) : '';
                    if (name) out.push({ id, name });
                });
                return out;
            }
            ''') or []
            logging.info(f"🏰 Деревни (с именами): {[v.get('name') for v in villages]}")
            return villages
        except Exception as e:
            logging.error(f"❌ Ошибка при получении списка деревень с именами: {e}")
            return []

    def _get_current_village_name(self):
        """Имя активной деревни из сайдбара (для сопоставления с шаблонами GUI)."""
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

    def _get_build_plan_for_village(self, village_key):
        """
        Возвращает план застройки для деревни.
        Приоритет:
          1. Шаблон из runtime-настроек (build.village_plans[...]) — GUI
          2. Глобальный config.BUILD_PLAN (dict по деревням или общий список)

        village_key приходит как 'village_<id>' (или 'default_village'), а GUI
        сохраняет ключи по ИМЕНИ деревни. Поэтому сопоставляем по набору
        кандидатов: имя активной деревни, сырой id, полный village_key и '*'.
        """
        # 1. Runtime-настройка из GUI (bot_settings_<acc>.json)
        try:
            from config.build_templates import TEMPLATES, get_template_plan
            from config.config import PLAN_X1, PLAN_X3
            store = getattr(self, '_settings_store', None)
            if store is not None:
                village_plans = store.section('build').get('village_plans', {})

                # Собираем кандидатов-ключей в порядке приоритета
                candidates = []
                name = self._get_current_village_name()
                if name:
                    candidates.append(name)
                if village_key:
                    candidates.append(village_key)                       # village_29831
                    raw = str(village_key).replace('village_', '')       # 29831
                    if raw and raw != village_key:
                        candidates.append(raw)
                candidates.append('*')  # правило «все деревни»

                template_id = None
                matched_key = None
                for key in candidates:
                    if key in village_plans and village_plans[key]:
                        template_id = village_plans[key]
                        matched_key = key
                        break

                if template_id and template_id in TEMPLATES:
                    plan = get_template_plan(template_id, fallback_x1=PLAN_X1, fallback_x3=PLAN_X3)
                    logging.info(f"[Build] '{matched_key}': шаблон '{template_id}' ({len(plan)} шагов)")
                    return plan

            # Шаблон аккаунта (выбран при добавлении аккаунта в форме GUI)
            acc_template = getattr(self.config, 'build_template', None)
            if acc_template and acc_template in TEMPLATES:
                plan = get_template_plan(acc_template, fallback_x1=PLAN_X1, fallback_x3=PLAN_X3)
                logging.info(f"[Build] Шаблон аккаунта '{acc_template}' ({len(plan)} шагов)")
                return plan

            logging.info(f"[Build] Шаблон не назначен → глобальный план.")
        except Exception as e:
            logging.warning(f"[Build] Ошибка чтения шаблона для {village_key}: {e}")

        # 2. Легаси: глобальный BUILD_PLAN из config
        plan = self.config.BUILD_PLAN
        if isinstance(plan, dict):
            return plan.get(village_key, plan.get("default_village", []))
        return plan

    def show_menu(self):
        print("\n" + "=" * 50)
        print("🌍 НАСТРОЙКА СЕРВЕРА")
        print("=" * 50)
        print("Выберите скорость (рейт) вашего сервера:")
        print("  1. x1 (Стандарт: упор на ресурсы)")
        print("  3. x3 / x5 (Скоростной)")
        print("=" * 50)

        while True:
            rate = input("👉 Введите 1 или 3: ").strip()
            if rate in ['1', '3']:
                self.config.set_rate(rate)
                logging.info(f"✅ План постройки для x{rate} загружен!")
                break
            print("❌ Ошибка ввода.")

        while True:
            print("\n" + "=" * 50)
            print("🎮 TRAVIAN БОТ - ГЛАВНОЕ МЕНЮ")
            print("=" * 50)
            print("   1. 📜 Собрать награды за задания")
            print("   2. 🏇 Приключения героя")
            print("   3. 🏗️ Умная постройка (Smart Builder)")
            print("   4. 📡 РАДАР: Сканировать оазисы вокруг")
            print("   5. ⚔️ ФАРМ: Отправить набеги по списку")
            print("   6. 🤖 ПОЛНЫЙ ЦИКЛ (Мульти-Деревни: Фарм + Стройка)")
            print("   7. ⚙️ НАСТРОЙКИ ФАРМА (Юниты, Тип, Дистанция, Радиус)")
            print("   0. ❌ Выход")
            print("=" * 50)

            choice = input("\n👉 Выберите действие: ").strip()

            if choice == '1':
                self.tasks_action.collect_tasks()
            elif choice == '2':
                self.adventure_action.auto_adventure()
            elif choice == '3':
                # В ручном режиме применяем план к ТЕКУЩЕЙ открытой деревне
                village_key = self.farm_manager.update_village_identity()
                saved = self.smart_builder.get_saved_step(village_key)
                step_str = input(
                    f"🔢 С какого шага начать стройку? (Enter — продолжить с сохранённого: {saved}): "
                ).strip()
                start_step = int(step_str) if step_str.isdigit() else None  # None = сохранённый
                plan = self._get_build_plan_for_village(village_key)

                logging.info(f"🏗️ Запуск Smart Builder (Деревня: {village_key}, Шаг: {start_step or saved})...")
                self.smart_builder.execute_plan(plan, start_step=start_step, village_key=village_key)

            elif choice == '4':
                settings = self.farm_manager.settings
                print(f"ℹ️ Укажите координаты деревни. Радиус: {settings.get('scan_radius', 5)}.")
                try:
                    x = int(input("  X (по умолчанию 0): ") or "0")
                    y = int(input("  Y (по умолчанию 0): ") or "0")
                    self.farm_manager.scan_oases_around(x, y)
                except ValueError:
                    print("❌ Вводите только числа!")

            elif choice == '5':
                self.farm_manager.auto_farm()


            elif choice == '6':

                logging.info("🤖 Запуск Мульти-Деревенского Цикла (КАРУСЕЛЬ)...")

                logging.info("ℹ️ Нажмите Ctrl+C, чтобы остановить.")

                try:

                    while True:

                        villages = self.get_all_villages()

                        self.tasks_action.collect_tasks()

                        self.adventure_action.auto_adventure()

                        # Проверяем входящие атаки один раз за круг

                        attacks = self.attack_monitor.check_incoming() if self.attack_monitor else []

                        for vid in villages:

                            # Переключаемся на деревню

                            if vid:

                                switch_url = f"{self.config.base_url}/dorf1.php?newdid={vid}"

                                logging.info(f"🔄 === ПЕРЕКЛЮЧЕНИЕ НА ДЕРЕВНЮ [{vid}] ===")

                            else:

                                switch_url = f"{self.config.base_url}/dorf1.php"

                                logging.info(f"🔄 === АКТИВНАЯ ДЕРЕВНЯ ===")

                            self.page.goto(switch_url)

                            time.sleep(random.uniform(1.5, 3.0))

                            # Только после goto — обновляем ID

                            current_village_key = self.farm_manager.update_village_identity()

                            # Эвазия при атаке.
                            # FIX: раньше maybe_evade запускал фарм, а строкой ниже
                            # auto_farm() запускался ЕЩЁ РАЗ => двойная отправка.
                            evaded = False
                            if self.attack_monitor and attacks and getattr(self.config, 'evasion_enabled', False):
                                self.attack_monitor.maybe_evade(self.farm_manager, attacks)
                                evaded = True

                            if not evaded:
                                self.farm_manager.auto_farm()

                            store = getattr(self.config, 'settings_store', None)

                            # FIX: тренировка и NPC — только если включены в настройках
                            if self.troop_trainer and (store is None or store.feature('train_enabled', False)):
                                self.troop_trainer.auto_train()

                            if self.trade_manager and store is not None and store.feature('npc_trade_enabled', False):
                                threshold = int(store.section('trade').get('npc_threshold_pct', 85))
                                self.trade_manager.npc_trade(threshold_pct=threshold)

                            plan = self._get_build_plan_for_village(current_village_key)

                            if plan:

                                self.smart_builder.execute_plan(plan, village_key=current_village_key)

                            else:

                                logging.info(f"⏭️ Для деревни {current_village_key} нет плана. Пропускаю.")

                            time.sleep(random.uniform(2.0, 4.0))

                        sleep_time = random.uniform(180, 420)

                        logging.info(f"💤 Круг завершен. Сплю {int(sleep_time / 60)} мин {int(sleep_time % 60)} сек...")

                        time.sleep(sleep_time)


                except KeyboardInterrupt:

                    print("\n🛑 Карусель остановлена.")


            elif choice == '7':
                settings = self.farm_manager.settings
                print("\n" + "-" * 40)
                print("⚙️ ТЕКУЩИЕ НАСТРОЙКИ ФАРМА:")
                print(f"  1. Юнитов на 1 оазис: {settings.get('troops_per_raid', 10)}")
                print(f"  2. Тип юнита (1-11): t{settings.get('troop_type_index', 1)}")
                print(f"  3. Макс. дистанция: {settings.get('max_distance', 0.0)} (0 = без лимита)")
                print(f"  4. Радиус радара: {settings.get('scan_radius', 5)}")
                print(f"  5. Перерыв для оазиса (мин): {settings.get('cooldown_minutes', 60)}")
                print("-" * 40)

                try:
                    t_str = input("⚔️ Введите кол-во юнитов (Enter - оставить): ").strip()
                    u_str = input("💂 Введите индекс юнита (например 1 для дубин) (Enter - оставить): ").strip()
                    d_str = input("📏 Введите макс. дистанцию (Enter - оставить): ").strip()
                    r_str = input("📡 Введите радиус сканирования (Enter - оставить): ").strip()
                    c_str = input("⏳ Введите перерыв для оазиса в минутах (Enter - оставить): ").strip()
                    new_t = int(t_str) if t_str else settings.get('troops_per_raid', 10)
                    new_u = int(u_str) if u_str else settings.get('troop_type_index', 1)
                    new_d = float(d_str) if d_str else settings.get('max_distance', 0.0)
                    new_r = int(r_str) if r_str else settings.get('scan_radius', 5)
                    new_c = int(c_str) if c_str else settings.get('cooldown_minutes', 60)

                    if not (1 <= new_u <= 11):
                        print("❌ Индекс юнита должен быть от 1 до 11! Значение не изменено.")
                        new_u = settings.get('troop_type_index', 1)

                    self.farm_manager.save_settings({
                        "troops_per_raid": new_t,
                        "troop_type_index": new_u,
                        "max_distance": new_d,
                        "scan_radius": new_r,
                        "cooldown_minutes": new_c
                    })

                except ValueError:
                    print("❌ Ошибка ввода! Используйте только числа.")

            elif choice == '0':
                print("👋 До свидания!")
                break
            else:
                print("❌ Неверный выбор!")
