import os
import logging
import time
import argparse
import multiprocessing
from dotenv import load_dotenv

load_dotenv()


def run_bot(acc_config: dict):
    import os
    import time
    import json
    import random
    import logging
    import threading
    from datetime import datetime

    # --- ЛОГИРОВАНИЕ -----------------------------------------------
    name = acc_config.get('name', 'bot')
    os.makedirs("logs", exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = f"logs/{name}_{date_str}.log"
    logging.basicConfig(
        level=logging.INFO,
        format=f'[{name}] %(asctime)s - [%(levelname)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info(f"🚀 Запуск бота для [{name}]")

    # --- СТАТУС (per-account файл — нет гонки между процессами) -----
    from utils.paths import account_file
    status_file = str(account_file(name, 'status'))

    def write_status(data: dict):
        payload = {
            **data,
            "last_heartbeat": datetime.now().isoformat(),
            "alive": data.get("alive", True),
        }
        tmp = status_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, status_file)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось записать {status_file}: {e}")

    # --- КОНФИГ ----------------------------------------------------
    from config.config import BotConfig
    from services.notifier import create_notifier
    from utils.base_action import get_random_viewport, get_random_user_agent
    from utils.settings_store import SettingsStore
    from utils.exceptions import CaptchaDetectedError
    from utils.commands import pop_commands

    config = BotConfig()
    config.name        = name
    config.server      = acc_config.get('server', config.server)
    config.cookie_file = acc_config.get('cookies') or str(account_file(name, 'cookies'))
    config.headless    = acc_config.get('headless', False)
    config.telegram_token   = acc_config.get('telegram_token')   or os.getenv('TELEGRAM_TOKEN')
    config.telegram_chat_id = acc_config.get('telegram_chat_id') or os.getenv('TELEGRAM_CHAT_ID')
    config.sleep_hours           = tuple(acc_config.get('sleep_hours', []))
    config.max_actions_per_hour  = acc_config.get('max_actions_per_hour', 0)
    config.set_rate(str(acc_config.get('rate', '3')))
    # Шаблон стройки выбранный при добавлении аккаунта (форма GUI)
    config.build_template = acc_config.get('build_template') or None
    config.notifier  = create_notifier(config)
    config.center_x  = acc_config.get('center_x', 0)
    config.center_y  = acc_config.get('center_y', 0)

    # ЕДИНЫЙ источник настроек: bot_settings_{name}.json
    # Создаётся из config.yaml, дальше редактируется из GUI в реальном времени.
    store = SettingsStore(name, acc_config)
    config.settings_store = store

    # evasion читается живьём из store (GUI может переключить на лету)
    config.evasion_enabled = store.feature('evasion_enabled', acc_config.get('evasion_enabled', True))

    # --- БРАУЗЕР ---------------------------------------------------
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import Stealth
        stealth_available = True
    except ImportError:
        stealth_available = False

    # Отпечаток браузера (viewport + User-Agent) СТАБИЛЕН для аккаунта:
    # генерируем один раз и сохраняем на диск. Реальный игрок заходит с
    # одного устройства — менять fingerprint при каждом рестарте подозрительно.
    fingerprint_file = f"fingerprint_{name}.json"
    fingerprint = None
    try:
        if os.path.exists(fingerprint_file):
            with open(fingerprint_file, "r", encoding="utf-8") as f:
                fingerprint = json.load(f)
    except Exception as e:
        logger.debug(f"fingerprint load error: {e}")

    if not fingerprint or 'viewport' not in fingerprint or 'user_agent' not in fingerprint:
        fingerprint = {
            'viewport': get_random_viewport(),
            'user_agent': get_random_user_agent(),
        }
        try:
            with open(fingerprint_file, "w", encoding="utf-8") as f:
                json.dump(fingerprint, f, ensure_ascii=False, indent=2)
            logger.info("🧬 Сгенерирован новый отпечаток браузера (сохранён на диск).")
        except Exception as e:
            logger.debug(f"fingerprint save error: {e}")
    else:
        logger.info("🧬 Использую сохранённый отпечаток браузера аккаунта.")

    viewport   = fingerprint['viewport']
    user_agent = fingerprint['user_agent']

    # Прокси: поддерживаются схемы http:// https:// socks5:// (без логина/пароля)
    # Chromium НЕ поддерживает socks5 с логином/паролем — используй http/https прокси.
    from utils.accounts import parse_proxy, validate_proxy
    from urllib.parse import urlparse as _urlparse
    proxy_str = acc_config.get("proxy") or ""
    proxy_cfg = None

    if proxy_str:
        _u = _urlparse(proxy_str if "://" in proxy_str else "http://" + proxy_str)
        if _u.scheme.lower() == "socks5" and _u.username:
            logger.error(
                "❌ Прокси отклонён: Chromium не поддерживает SOCKS5 с логином/паролем. "
                "Используй HTTP/HTTPS прокси: http://user:pass@host:port"
            )
            write_status({
                'last_action': 'Ошибка прокси: SOCKS5 с паролем не поддерживается — используй HTTP прокси',
                'current_village': '—',
                'alive': False,
            })
            return

        ok, err = validate_proxy(proxy_str, timeout=6.0)
        if not ok:
            logger.error(f"❌ Прокси недоступен — бот остановлен. {err}")
            write_status({
                'last_action': f'Ошибка прокси: {err}',
                'current_village': '—',
                'alive': False,
            })
            return

        proxy_cfg = parse_proxy(proxy_str)
        logger.info(f"🌐 Использую прокси: {proxy_cfg['server']}")

    with sync_playwright() as p:
        launch_kwargs = {
            "headless": config.headless,
            "args": ['--disable-blink-features=AutomationControlled', '--mute-audio'],
        }
        if proxy_cfg:
            launch_kwargs["proxy"] = proxy_cfg
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as e:
            err_msg = str(e)
            logger.error(f"❌ Не удалось запустить браузер: {err_msg}", exc_info=True)
            write_status({
                'last_action': f'Ошибка запуска браузера: {err_msg[:120]}',
                'current_village': '—',
                'alive': False,
            })
            return
        context = browser.new_context(viewport=viewport, user_agent=user_agent)
        page    = context.new_page()

        if stealth_available:
            try:
                stealth = Stealth()
                stealth.apply_stealth_sync(context)
                stealth.apply_stealth_sync(page)
                logger.info("🥷 Stealth активирован.")
            except Exception as e:
                logger.warning(f"⚠️ Stealth ошибка: {e}")
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
        else:
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

        # --- МОДУЛИ ------------------------------------------------
        from services.cookie_manager import CookieManager
        from services.smart_builder  import SmartBuilder
        from services.menu_manager   import MenuManager
        from services.troop_trainer  import TroopTrainer
        from services.trade_manager  import TradeManager
        from services.scheduler      import Scheduler
        from actions.adventure_action import HeroAdventure
        from actions.tasks_action     import TasksAction
        from actions.oasis_action     import FarmManager
        from actions.attack_monitor      import AttackMonitor
        from actions.stats_collector     import StatsCollector
        from actions.celebration_action  import CelebrationAction
        from actions.smithy_action       import SmithyUpgrader
        from actions.report_action        import ReportCollector
        from actions.farm_stats           import FarmStats

        cookie_manager   = CookieManager(context, config.cookie_file)
        tasks_action     = TasksAction(page, config)
        adventure_action = HeroAdventure(page, config)
        smart_builder    = SmartBuilder(page, config, tasks_action, settings_store=store)
        # Общая статистика фарма: пишут FarmManager (набеги/юниты) и
        # ReportCollector (добыча/потери) — один файл, без гонок.
        farm_stats       = FarmStats(name)
        farm_manager     = FarmManager(page, config, settings_store=store,
                                       adventure_action=adventure_action, farm_stats=farm_stats)
        attack_monitor   = AttackMonitor(page, config)
        troop_trainer    = TroopTrainer(page, config, settings_store=store)
        trade_manager    = TradeManager(page, config)
        stats_collector  = StatsCollector(page, config)
        report_collector = ReportCollector(page, config, farm_stats)

        # Начальные настройки фарма из store (дальше FarmManager сам обновляет)
        farm_settings = store.section('farm')
        farm_manager.settings.update({k: v for k, v in farm_settings.items() if v is not None})
        farm_manager.settings.update({
            'center_x': config.center_x,
            'center_y': config.center_y,
        })

        menu_manager = MenuManager(
            page, smart_builder, adventure_action,
            tasks_action, farm_manager, config,
            attack_monitor=attack_monitor,
            troop_trainer=troop_trainer,
            trade_manager=trade_manager,
            settings_store=store,
        )
        celebration_action = CelebrationAction(
            page, config,
            villages_fn=menu_manager.get_villages_detailed,
        )
        smithy_upgrader = SmithyUpgrader(page, config, settings_store=store)

        # --- АВТОРИЗАЦИЯ ------------------------------------------
        # Приоритет: поля аккаунта -> TRAVIAN_EMAIL_<NAME> -> TRAVIAN_EMAIL
        from utils.accounts import resolve_credentials
        email, password = resolve_credentials(acc_config)

        def _do_login():
            """Полный вход по логину/паролю. Выбрасывает RuntimeError при неудаче."""
            if not email or not password:
                raise RuntimeError("Куки устарели, а email/password не заданы (config.yaml или .env).")
            logger.info("Вход по логину/паролю...")
            # На странице логина ищем форму (может быть input[name="name"] или input[name="username"])
            name_input = page.locator('input[name="name"], input[name="username"]').first
            name_input.fill(email)
            page.locator('input[name="password"]').fill(password)
            page.locator('button[type="submit"], input[type="submit"]').first.click()
            page.wait_for_selector('#sidebarBoxActiveVillage, #villageList', timeout=20000)
            cookie_manager.save_cookie()
            logger.info("Авторизация по логину/паролю успешна.")

        def _is_logged_in() -> bool:
            """True — мы внутри игры (виден сайдбар деревни)."""
            return (
                page.locator('#sidebarBoxActiveVillage').count() > 0
                or page.locator('#villageList').count() > 0
            )

        # Ретраи входа с экспоненциальным backoff: 30с, 2м, 8м, 30м, 30м...
        LOGIN_MAX_ATTEMPTS = 5
        login_ok = False
        last_login_err = None
        for attempt in range(1, LOGIN_MAX_ATTEMPTS + 1):
            try:
                cookie_manager.load_cookies()
                page.goto(config.login_url)
                page.wait_for_load_state('domcontentloaded')

                if _is_logged_in():
                    logger.info("Вход по кукам успешен.")
                else:
                    # Куки устарели или файла нет — пробуем войти по логину/паролю.
                    logger.warning("Куки не подошли или устарели — пробую войти по логину/паролю.")
                    if not page.locator('input[name="name"], input[name="username"]').is_visible():
                        page.goto(config.login_url.replace('/dorf1.php', '/login'))
                        page.wait_for_load_state('domcontentloaded')
                    _do_login()

                config.base_url = page.url.split("/dorf1.php")[0]
                login_ok = True
                break
            except Exception as e:
                last_login_err = e
                if attempt >= LOGIN_MAX_ATTEMPTS:
                    break
                # 30с * 4^(attempt-1), максимум 30 минут
                delay = min(30 * (4 ** (attempt - 1)), 1800)
                logger.warning(
                    f"Ошибка авторизации (попытка {attempt}/{LOGIN_MAX_ATTEMPTS}): {e}. "
                    f"Повтор через {delay//60}м {delay%60}с."
                )
                time.sleep(delay)

        if not login_ok:
            logger.error(f"Авторизация не удалась после {LOGIN_MAX_ATTEMPTS} попыток: {last_login_err}")
            config.notifier.error(f"{name}: вход", last_login_err)
            browser.close()
            return

        # --- МОНИТОРИНГ АТАК В ОТДЕЛЬНОМ ПОТОКЕ --------------------
        # Работает через requests (не трогает браузер!) => не мешает задачам.
        # При обнаружении атаки НЕ действует сам, а ставит срочную задачу
        # "evade" в планировщик (задачи не перебивают друг друга).
        # FIX: поддерживаем и опечатку 'ttack_check_interval' из старых конфигов
        attack_check_interval = acc_config.get(
            'attack_check_interval',
            acc_config.get('ttack_check_interval', 120)
        )
        _stop_monitor = threading.Event()
        _last_attack_ids: set = set()
        _attack_flag = threading.Event()   # сигнал планировщику

        _cookies_lock = threading.Lock()
        _cookies_cache: list = []

        def refresh_cookies():
            """Вызывать только из главного потока!"""
            try:
                new_cookies = context.cookies()
                with _cookies_lock:
                    _cookies_cache.clear()
                    _cookies_cache.extend(new_cookies)
            except Exception as e:
                logger.debug(f"refresh_cookies error: {e}")

        def attack_monitor_loop():
            import re as _re
            import requests as req
            from bs4 import BeautifulSoup

            logger.info(f"🛡️ Поток мониторинга атак запущен (каждые {attack_check_interval}с).")
            notifier = getattr(config, 'notifier', None)

            while not _stop_monitor.is_set():
                try:
                    with _cookies_lock:
                        cookies_snapshot = list(_cookies_cache)

                    session = req.Session()
                    for c in cookies_snapshot:
                        session.cookies.set(c['name'], c['value'])
                    session.headers['User-Agent'] = 'Mozilla/5.0'

                    resp = session.get(f"{config.base_url}/dorf1.php", timeout=10)

                    # FIX: детект протухшей сессии — раньше молча умирал на debug
                    if 'name="password"' in resp.text or '/login' in str(resp.url):
                        logger.warning("⚠️ [монитор] Сессия протухла — жду обновления кук от главного потока.")
                        _stop_monitor.wait(attack_check_interval)
                        continue

                    soup = BeautifulSoup(resp.text, 'html.parser')

                    # :has() ненадёжен в BeautifulSoup/soupsieve — вместо него
                    # ищем все .att1 и поднимаемся к родительскому <tr>.
                    # Так ложных срабатываний нет даже на старых версиях soupsieve.
                    att1_elements = soup.select('.typ .att1')
                    attack_rows = []
                    for el in att1_elements:
                        tr = el.find_parent('tr')
                        if tr and tr not in attack_rows:
                            attack_rows.append(tr)

                    current_attacks = []
                    if attack_rows:
                        new_attack = False
                        for row in attack_rows:
                            a1 = row.select_one('.mov .a1')
                            count_str = a1.get_text().strip() if a1 else '1'
                            count_m = _re.search(r'\d+', count_str)
                            count = int(count_m.group()) if count_m else 1

                            timer = row.select_one('.dur_r .timer')
                            arrival = timer.get_text().strip() if timer else '?'

                            row_text = row.get_text()
                            coords_m = _re.search(r'\((\-?\d+)\|(\-?\d+)\)', row_text)
                            from_x = int(coords_m.group(1)) if coords_m else 0
                            from_y = int(coords_m.group(2)) if coords_m else 0

                            current_attacks.append({
                                "from_x": from_x, "from_y": from_y,
                                "arrival": arrival, "count": count,
                            })

                            key = f"{from_x}|{from_y}|{count}"
                            if key not in _last_attack_ids:
                                _last_attack_ids.add(key)
                                new_attack = True
                                logger.warning(
                                    f"🚨 [монитор] АТАКА! x{count} через {arrival} ({from_x}|{from_y})"
                                )
                                if notifier:
                                    try:
                                        notifier.attack(coords=(from_x, from_y), arrival=arrival)
                                    except Exception as ne:
                                        logger.debug(f"notifier.attack error: {ne}")
                        if new_attack:
                            _attack_flag.set()
                    else:
                        _last_attack_ids.clear()

                    # Живой список атак — в статистику для GUI (thread-safe,
                    # страницу не трогаем: пишем только JSON-файл)
                    stats_collector.set_attacks(current_attacks)
                    stats_collector.save_attacks_only()

                except Exception as e:
                    logger.warning(f"⚠️ Монитор атак: {e}")

                _stop_monitor.wait(attack_check_interval)

        refresh_cookies()
        monitor_thread = threading.Thread(
            target=attack_monitor_loop,
            name=f"{name}-attack-monitor",
            daemon=True,
        )
        monitor_thread.start()

        # --- SAFE GOTO (анти-редирект dorf1.php?reload=auto) -------
        _original_goto = page.goto

        def safe_goto(url, **kwargs):
            kwargs.setdefault('wait_until', 'domcontentloaded')
            for attempt in range(3):
                try:
                    _original_goto(url, **kwargs)
                    try:
                        page.wait_for_load_state('domcontentloaded', timeout=5000)
                    except Exception:
                        logging.debug("suppressed error in runner:423", exc_info=True)
                    return
                except Exception as e:
                    err = str(e).lower()
                    if 'interrupted by another navigation' in err or 'navigation' in err:
                        logger.debug(f"safe_goto retry {attempt + 1}: {e}")
                        time.sleep(1.5)
                        try:
                            page.wait_for_load_state('domcontentloaded', timeout=8000)
                        except Exception:
                            logging.debug("suppressed error in runner:433", exc_info=True)
                        if attempt == 2:
                            logger.warning(f"⚠️ safe_goto: не удалось перейти на {url}: {e}")
                    else:
                        raise

        page.goto = safe_goto

        # --- ЗАДАЧИ ПЛАНИРОВЩИКА -----------------------------------
        # Каждая задача владеет страницей ЭКСКЛЮЗИВНО, пока выполняется.
        # Планировщик запускает их по одной => никто никого не перебивает.

        scheduler = Scheduler(logger)
        _captcha_until = [0.0]  # пауза после капчи

        # Задачи, которые САМИ решают, работать ли в ночном окне (sleep_hours):
        # стройка и кузница (по тумблеру build_night_enabled) и общий обход.
        # Остальные ночью спят.
        _NIGHT_OK_TASKS = ('build', 'smithy', 'village_round')

        def _sleep_hours() -> tuple:
            """Окно ночного режима из настроек GUI (секция 'night'), на лету.
            Возвращает (start, end) или () если ночной режим выключен/некорректен."""
            n = store.section('night')
            if not n.get('enabled', True):
                return ()
            try:
                s, e = int(n.get('start', 2)) % 24, int(n.get('end', 8)) % 24
            except (TypeError, ValueError):
                return ()
            return () if s == e else (s, e)

        def _refresh_night():
            """Применяет актуальное окно ночи к config (его читают is_night_time
            и seconds_until_morning)."""
            config.sleep_hours = _sleep_hours()

        _refresh_night()

        def _guard(task_name, fn):
            """Обёртка: капча-пауза, ночной режим, обновление кук, статус."""
            def wrapped():
                _refresh_night()  # окно ночи можно менять из GUI на лету
                # Пауза после капчи — стоп для ВСЕХ задач.
                if time.time() < _captcha_until[0]:
                    logger.info(f"💤 [{task_name}] пропущена (пауза после капчи).")
                    return
                # Ночь (sleep_hours): спят все задачи, кроме тех, что умеют
                # работать ночью сами (стройка/кузница при build_night_enabled).
                if attack_monitor.is_night_time() and task_name not in _NIGHT_OK_TASKS:
                    logger.info(f"🌙 [{task_name}] пропущена (ночной режим).")
                    return
                write_status({'last_action': f'Выполняю: {task_name}', 'current_village': farm_manager.current_village_id})
                try:
                    fn()
                except CaptchaDetectedError:
                    logger.error("💤 CAPTCHA! Пауза 30 минут, отправляю Telegram.")
                    config.notifier.captcha()
                    _captcha_until[0] = time.time() + 30 * 60
                    write_status({'last_action': '💤 CAPTCHA — пауза 30 мин', 'current_village': '—'})
                finally:
                    refresh_cookies()  # Монитор атак всегда с живыми куками
                write_status({'last_action': f'Готово: {task_name}', 'current_village': farm_manager.current_village_id})
            return wrapped

        def for_each_village(action, label, should_continue=None):
            """
            Карусель деревень для одного типа действия.
            should_continue() проверяется ПЕРЕД КАЖДОЙ деревней —
            если модуль выключили в GUI посреди карусели, она останавливается.
            """
            villages = menu_manager.get_all_villages()
            for vid in villages:
                if should_continue and not should_continue():
                    logger.info(f"⏭️ [{label}] выключено в настройках — карусель остановлена.")
                    return
                try:
                    if vid:
                        page.goto(f"{config.base_url}/dorf1.php?newdid={vid}")
                    else:
                        page.goto(config.login_url)
                    page.wait_for_load_state('domcontentloaded')
                    time.sleep(random.uniform(1.5, 2.5))
                    village_key = farm_manager.update_village_identity()
                    write_status({'last_action': f'{label}: {village_key}', 'current_village': village_key})
                    action(village_key)
                    time.sleep(random.uniform(1.5, 3.0))
                except CaptchaDetectedError:
                    raise
                except Exception as e:
                    logger.error(f"❌ [{label}] деревня {vid}: {e}")
                    continue

        # -- задачи --
        def job_farm():
            for_each_village(lambda vk: farm_manager.run_farm_cycle(), "Фарм",
                             should_continue=lambda: store.feature('farm_enabled', True))

        def job_hero_farm():
            """
            Отдельная задача: фарм ТОЛЬКО героем по оазисам с животными
            (безопасно, по силе героя). Войска сюда не входят — за них
            отвечает задача 'farm'. Порядок и вкл/выкл настраиваются в GUI.
            """
            for_each_village(lambda vk: farm_manager.run_hero_farm(), "Фарм героем",
                             should_continue=lambda: store.feature('hero_farm_enabled', False))

        def job_evade():
            """
            Срочная эвазия при атаке: ВСЕ войска каждой деревни уводятся
            ОДНИМ рейдом в ближайший оазис (evade_all_troops).
            Кулдауны и лимиты фарма игнорируются — это спасение армии,
            а не фарм. Войска вернутся сами после того, как рейд дойдёт.
            """
            _attack_flag.clear()
            if not store.feature('evasion_enabled', True):
                logger.info("⏭️ Эвазия выключена в настройках.")
                return
            # Кулдаун: при волнах атак не эвакуируемся чаще, чем раз в
            # EVADE_COOLDOWN_SEC — иначе бот бесконечно уводит уже ушедшие войска.
            if not attack_monitor.can_evade_now():
                logger.info("🏃 Эвазия на кулдауне — пропуск (недавно уже эвакуировались).")
                return
            write_status({'last_action': '🚨 АТАКА! Эвакуация войск', 'current_village': farm_manager.current_village_id})
            for_each_village(lambda vk: farm_manager.evade_all_troops(), "Эвакуация")
            attack_monitor._last_evade_ts = time.time()

        def _seconds_until_morning() -> int:
            """Секунды до конца ночного окна (sleep_hours[1])."""
            from utils.night_time import seconds_until_morning
            return seconds_until_morning(getattr(config, 'sleep_hours', ()))

        def job_build():
            # Ночной режим стройки: если build_night_enabled=False — пропускаем в sleep_hours
            if attack_monitor.is_night_time() and not store.feature('build_night_enabled', False):
                wake = _seconds_until_morning() + random.randint(60, 600)
                scheduler.set_next_run('build', wake)
                logger.info(
                    f"[build] Ночное время — стройка на паузе. "
                    f"Следующий запуск через {wake//3600}ч {(wake%3600)//60}м (утро)."
                )
                return
            # применяем настройку "строить через рекламу" в реальном времени
            smart_builder.use_ad_boost = store.feature('build_use_ads', True)
            # Собираем минимальное время ожидания по всем деревням:
            # если во всех деревнях очередь занята — ставим следующий запуск
            # ровно когда закончится самая ранняя постройка (+ 15с буфер).
            min_wait: list[int] = []

            def build_one(village_key):
                plan = menu_manager._get_build_plan_for_village(village_key)
                if not plan:
                    logger.info(f"⏭️ Нет плана для {village_key}.")
                    return
                wait_secs = smart_builder.execute_plan(plan, village_key=village_key)
                if isinstance(wait_secs, int) and wait_secs > 0:
                    min_wait.append(wait_secs)

            for_each_village(build_one, "Стройка")

            # Если хоть одна деревня вернула секунды (очередь занята или
            # постройка только что поставлена) — переставляем задачу ровно
            # на время окончания ближайшей постройки + 15с буфер.
            if min_wait:
                earliest = min(min_wait) + 15
                scheduler.set_next_run('build', earliest)
                logger.info(f"[build] следующий запуск через {earliest//60}м {earliest%60}с (по таймеру очереди).")

        def job_train():
            # vk = village_key вида "village_29831"; имя берём из сайдбара внутри auto_train
            for_each_village(
                lambda vk: troop_trainer.auto_train(
                    village_name=menu_manager._get_current_village_name()
                ),
                "Тренировка",
                should_continue=lambda: store.feature('train_enabled', False),
            )

        def job_npc_trade():
            threshold = int(store.section('trade').get('npc_threshold_pct', 85))
            for_each_village(lambda vk: trade_manager.npc_trade(threshold_pct=threshold), "NPC-обмен",
                             should_continue=lambda: store.feature('npc_trade_enabled', False))

        def job_transfer():
            """Переброска излишков ресурсов между своими деревнями по правилам из GUI."""
            tsec = store.section('trade')
            rules = tsec.get('transfer_rules') or []
            if not rules:
                logger.info("↔️ Переброска: правил нет — пропуск.")
                return
            detailed = menu_manager.get_villages_detailed()
            name_to_id = {v.get('name'): v.get('id') for v in detailed if v.get('name')}
            trade_manager.run_transfers(rules, name_to_id)

        def job_tasks():
            tasks_action.collect_tasks()
            tasks_action.collect_daily_quests()

        def job_adventure():
            result = adventure_action.auto_adventure(
                shorten=store.feature('adv_shorten_enabled', False),
                boost_difficulty=store.feature('adv_difficulty_enabled', False),
            )
            # Если auto_adventure вернул число — это cooldown в секундах
            # (duration * 2 + 30с буфер). Передаём в планировщик чтобы
            # следующий запуск был ровно когда герой вернётся, а не через
            # фиксированные 30 мин.
            if isinstance(result, (int, float)) and result > 60:
                scheduler.set_next_run('adventure', int(result))
                logger.info(
                    f"[adv] Следующий запуск приключения через "
                    f"{int(result)//60}м {int(result)%60}с (по таймеру героя)."
                )

        def job_celebration():
            """Запускает праздник в Ратуше во всех деревнях где он не идёт."""
            celebration_action.run()

        def job_smithy():
            """Авто-улучшение войск в Кузнице по очереди с приоритетами."""
            # Кузница подчиняется тому же ночному режиму что и стройка
            if attack_monitor.is_night_time() and not store.feature('build_night_enabled', False):
                wake = _seconds_until_morning() + random.randint(60, 600)
                scheduler.set_next_run('smithy', wake)
                logger.info(f"[smithy] Ночное время — кузница на паузе до утра.")
                return
            smithy_upgrader.run()

        def job_stats():
            """Лёгкий сбор статистики: ресурсы, войска, герой (одна страница)."""
            stats_collector.collect()

        def job_reports():
            """Читает новые боевые отчёты: добыча, потери, профит по войскам."""
            report_collector.collect()

        def job_village_round():
            """
            Grouped-режим: за ОДИН заход в деревню делаем все включённые
            действия (стройка → фарм войсками → фарм героем → тренировка → NPC),
            затем переходим к следующей. Минимум переключений деревень (newdid=).

            Компромисс: тонкие таймеры отдельных задач (например перезапуск
            стройки ровно к концу постройки) тут не применяются — весь обход
            идёт по одному интервалу. Зато меньше переключений и «человечнее».
            """
            smart_builder.use_ad_boost = store.feature('build_use_ads', True)
            npc_threshold = int(store.section('trade').get('npc_threshold_pct', 85))
            night = attack_monitor.is_night_time()
            build_at_night = store.feature('build_night_enabled', False)

            # Ночь и ночная стройка выключена — обход не нужен, спим до утра.
            if night and not build_at_night:
                wake = _seconds_until_morning() + random.randint(60, 600)
                scheduler.set_next_run('village_round', wake)
                logger.info("[village_round] Ночь — обход на паузе до утра.")
                return

            def per_village(vk):
                # 1) Стройка
                if store.feature('build_enabled', True):
                    plan = menu_manager._get_build_plan_for_village(vk)
                    if plan:
                        smart_builder.execute_plan(plan, village_key=vk)
                # Ночью (при включённой ночной стройке) — только стройка,
                # остальные «активные» действия не делаем.
                if night:
                    return
                # 2) Фарм войсками
                if store.feature('farm_enabled', True):
                    farm_manager.run_farm_cycle()
                # 3) Фарм героем (если включён отдельной фичей)
                if store.feature('hero_farm_enabled', False):
                    farm_manager.run_hero_farm()
                # 4) Тренировка войск
                if store.feature('train_enabled', False):
                    troop_trainer.auto_train(village_name=menu_manager._get_current_village_name())
                # 5) NPC-обмен при переполнении
                if store.feature('npc_trade_enabled', False):
                    trade_manager.npc_trade(threshold_pct=npc_threshold)

            for_each_village(per_village, "Обход деревень")

        def job_scan():
            """
            Принудительный скан карты (по требованию из GUI/Telegram).
            Пересканирует оазисы вокруг каждой деревни и обновляет фарм-лист,
            игнорируя кулдаун сканирования (force_rescan=True).
            """
            write_status({'last_action': '🗺️ Принудительный скан карты',
                          'current_village': farm_manager.current_village_id})
            for_each_village(
                lambda vk: farm_manager.run_farm_cycle(force_rescan=True),
                "Скан карты",
            )

        def job_rescan():
            """
            Быстрый перескан ТОЛЬКО известных оазисов (по требованию из GUI/Telegram).
            Не обходит весь радиус — перепроверяет клетки, найденные полным сканом.
            В разы быстрее полного скана.
            """
            write_status({'last_action': '♻️ Перескан известных оазисов',
                          'current_village': farm_manager.current_village_id})
            for_each_village(
                lambda vk: farm_manager.rescan_known_oases(),
                "Перескан оазисов",
            )

        # -- регистрация (интервалы в секундах, приоритет: меньше = важнее) --
        farm_interval = int(store.section('farm').get('interval_minutes', 60)) * 60

        # В grouped-режиме отдельные per-village задачи стоят на паузе —
        # их работу делает единый обход job_village_round.
        def _grouped() -> bool:
            return store.feature('grouped_cycle', False)

        # FIX: без initial_delay next_run = "сейчас", и планировщик выполнял
        # эвакуацию ОДИН раз сразу при старте бота — без всякой атаки.
        # initial_delay=10**9 гарантирует запуск ТОЛЬКО через run_now.
        scheduler.add('evade',     _guard('evade', job_evade),          interval_sec=10**9, priority=0,
                      initial_delay=10**9)  # только по run_now
        scheduler.add('farm',      _guard('farm', job_farm),            interval_sec=farm_interval, priority=2)
        scheduler.add('hero_farm', _guard('hero_farm', job_hero_farm),  interval_sec=farm_interval, priority=2,
                      enabled_check=lambda: store.feature('hero_farm_enabled', False) and not _grouped(),
                      initial_delay=90)
        scheduler.add('build',     _guard('build', job_build),          interval_sec=7 * 60,  priority=3,
                      enabled_check=lambda: store.feature('build_enabled', True) and not _grouped())
        scheduler.add('train',     _guard('train', job_train),          interval_sec=15 * 60, priority=4,
                      enabled_check=lambda: store.feature('train_enabled', False) and not _grouped())
        scheduler.add('tasks',     _guard('tasks', job_tasks),          interval_sec=30 * 60, priority=5,
                      enabled_check=lambda: store.feature('tasks_enabled', True), initial_delay=60)
        scheduler.add('adventure', _guard('adventure', job_adventure),  interval_sec=30 * 60, priority=6,
                      enabled_check=lambda: store.feature('adventure_enabled', True), initial_delay=120)
        scheduler.add('npc_trade', _guard('npc_trade', job_npc_trade),  interval_sec=30 * 60, priority=7,
                      enabled_check=lambda: store.feature('npc_trade_enabled', False) and not _grouped(),
                      initial_delay=180)
        transfer_interval = int(store.section('trade').get('transfer_interval_min', 60)) * 60
        scheduler.add('transfer',    _guard('transfer', job_transfer),       interval_sec=transfer_interval, priority=7,
                      enabled_check=lambda: store.feature('transfer_enabled', False), initial_delay=240)
        scheduler.add('celebration', _guard('celebration', job_celebration), interval_sec=60 * 60, priority=6,
                      enabled_check=lambda: store.feature('celebration_enabled', False), initial_delay=300)
        scheduler.add('smithy',      _guard('smithy', job_smithy),           interval_sec=30 * 60, priority=6,
                      enabled_check=lambda: store.feature('smithy_enabled', False), initial_delay=120)
        scheduler.add('stats',     _guard('stats', job_stats),          interval_sec=5 * 60,  priority=8,
                      initial_delay=30)
        scheduler.add('reports',   _guard('reports', job_reports),      interval_sec=20 * 60, priority=8,
                      enabled_check=lambda: store.feature('reports_enabled', True), initial_delay=200)
        # Единый обход деревень «пачкой» (grouped-режим). По умолчанию выключен —
        # включается тумблером; тогда farm/build/train/npc/hero_farm стоят на паузе.
        scheduler.add('village_round', _guard('village_round', job_village_round),
                      interval_sec=farm_interval, priority=2,
                      enabled_check=_grouped, initial_delay=45)
        # Скан карты — только по требованию (run_now из idle_hook при команде из GUI)
        scheduler.add('scan',      _guard('scan', job_scan),            interval_sec=10**9, priority=1,
                      initial_delay=10**9)
        scheduler.add('rescan',    _guard('rescan', job_rescan),        interval_sec=10**9, priority=1,
                      initial_delay=10**9)

        # фарм можно выключить из GUI (и он на паузе в grouped-режиме)
        scheduler.jobs['farm'].enabled_check = lambda: store.feature('farm_enabled', True) and not _grouped()

        # --- ПОРЯДОК ЗАДАЧ (настраивается перетаскиванием в GUI) ----
        # Периодические задачи, порядок которых пользователь задаёт в дашборде.
        # Срочные (evade/scan/rescan) сюда НЕ входят — они всегда важнее.
        ORDERABLE_TASKS = [
            "farm", "hero_farm", "build", "train", "tasks", "adventure",
            "celebration", "smithy", "npc_trade", "transfer", "stats", "reports",
        ]
        _PRIORITY_BASE = 10  # чтобы orderable-задачи всегда были ниже срочных (0-1)

        def apply_task_order():
            """Читает порядок из настроек и переназначает приоритеты задач.
            Меньший индекс в списке => меньший priority => выполняется раньше."""
            saved = store.section('task_order').get('order') or []
            # оставляем только известные задачи, недостающие дописываем в дефолтном порядке
            ordered = [k for k in saved if k in ORDERABLE_TASKS]
            for k in ORDERABLE_TASKS:
                if k not in ordered:
                    ordered.append(k)
            for idx, key in enumerate(ordered):
                job = scheduler.jobs.get(key)
                if job:
                    job.priority = _PRIORITY_BASE + idx
            return ordered

        _current_order = [apply_task_order()]

        def idle_hook():
            """Между задачами: heartbeat + срочная эвазия + команды из GUI + живой интервал фарма."""
            _refresh_night()  # окно ночи из GUI на лету
            if _attack_flag.is_set():
                scheduler.run_now('evade')
            # команды из GUI/Telegram (например, принудительный скан карты)
            try:
                for action in pop_commands(name):
                    if action == 'scan':
                        logger.info("📥 Команда из GUI: принудительный скан карты.")
                        scheduler.run_now('scan', priority=1)
                    elif action == 'rescan':
                        logger.info("📥 Команда из GUI: перескан известных оазисов.")
                        scheduler.run_now('rescan', priority=1)
                    elif action == 'force_farm':
                        # Принудительная атака войсками: запускаем фарм немедленно.
                        # run_now ставит задачу в срочную очередь, а после её
                        # выполнения next_run сбросится на now+interval — т.е.
                        # счётчик до следующего фарма фактически обнуляется.
                        logger.info("📥 Команда из GUI: принудительная атака войсками (сброс счётчика фарма).")
                        scheduler.run_now('farm', priority=1)
            except Exception as e:
                logger.debug(f"pop_commands error: {e}")
            # интервал фарма можно поменять в GUI на лету
            new_interval = int(store.section('farm').get('interval_minutes', 60)) * 60
            if new_interval != scheduler.jobs['farm'].interval:
                scheduler.jobs['farm'].interval = new_interval
                logger.info(f"🔄 Интервал фарма обновлён: {new_interval // 60} мин.")
            # порядок задач можно поменять в GUI на лету (перетаскиванием)
            new_order = apply_task_order()
            if new_order != _current_order[0]:
                _current_order[0] = new_order
                logger.info(f"🔀 Порядок задач обновлён: {' → '.join(new_order)}")
            if attack_monitor.is_night_time():
                write_status({'last_action': '🌙 Ночной режим', 'current_village': '—'})
            else:
                write_status({'last_action': '💤 Жду следующую задачу', 'current_village': farm_manager.current_village_id})

        # --- СТАРТ --------------------------------------------------
        write_status({'last_action': 'Запущен', 'current_village': '—'})
        try:
            scheduler.run_forever(idle_hook=idle_hook)
        except KeyboardInterrupt:
            logger.info("\n🛑 Остановлен пользователем.")
        except Exception as e:
            logger.critical(f"💥 Критическая ошибка: {e}", exc_info=True)
            config.notifier.error(f"{name}: критическая", e)
        finally:
            _stop_monitor.set()
            write_status({'last_action': 'Остановлен', 'current_village': '—', 'alive': False})
            browser.close()
            logger.info("🛑 Браузер закрыт.")


def main():
    """
    Запускает бота.
      python runner.py                  — все аккаунты (config.yaml + GUI)
      python runner.py --account acc2   — ТОЛЬКО один аккаунт (независимый процесс)

    Флаг --account используется GUI: каждый аккаунт стартует/останавливается
    отдельным процессом и никак не зависит от остальных.
    """
    parser = argparse.ArgumentParser(description="Travian bot runner")
    parser.add_argument("--account", help="Запустить только указанный аккаунт")
    args = parser.parse_args()

    # Единый реестр: config.yaml + accounts_gui.json (добавленные из GUI)
    from utils.accounts import load_accounts
    accounts = load_accounts()
    if not accounts:
        print("❌ Нет аккаунтов (config.yaml / accounts_gui.json)")
        return

    if args.account:
        acc = next((a for a in accounts if a.get("name") == args.account), None)
        if not acc:
            print(f"❌ Аккаунт '{args.account}' не найден.")
            return
        # Одиночный режим: без multiprocessing — процессом управляет вызывающий (GUI)
        run_bot(acc)
        return

    processes = []
    for acc in accounts:
        p = multiprocessing.Process(target=run_bot, args=(acc,), name=acc.get('name', 'bot'))
        p.start()
        processes.append(p)
        time.sleep(3)

    print(f"✅ Запущено {len(processes)} аккаунт(ов). Ctrl+C для остановки.")
    print("🖥️ GUI: запустите `uvicorn app:app --port 8000` и откройте http://localhost:8000")
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\n🛑 Останавливаю все процессы...")
        for p in processes:
            p.terminate()


if __name__ == '__main__':
    multiprocessing.freeze_support()  # для Windows
    main()
