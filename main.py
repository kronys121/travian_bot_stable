"""
Точка входа Travian Bot.

FIX: раньше main.py и runner.py были двумя РАЗНЫМИ входами с
дублирующейся и разъехавшейся логикой (захардкожен cookies.json,
не обновлялся base_url при входе по кукам, не писался статус).

Теперь:
    python main.py                # = python runner.py (боевой режим, планировщик)
    python main.py --interactive  # ручное меню для отладки (один аккаунт)

GUI-дашборд (отдельным процессом):
    uvicorn app:app --port 8000
"""
import os
import sys
import logging
import multiprocessing

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def run_interactive():
    """Отладочный режим: ручное меню на первом аккаунте из config.yaml."""
    import yaml
    from playwright.sync_api import sync_playwright

    from config.config import BotConfig
    from services.cookie_manager import CookieManager
    from services.menu_manager import MenuManager
    from services.smart_builder import SmartBuilder
    from services.troop_trainer import TroopTrainer
    from services.trade_manager import TradeManager
    from services.notifier import create_notifier
    from actions.adventure_action import HeroAdventure
    from actions.tasks_action import TasksAction
    from actions.oasis_action import FarmManager
    from actions.attack_monitor import AttackMonitor
    from utils.settings_store import SettingsStore
    from utils.base_action import get_random_viewport, get_random_user_agent

    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            accounts = yaml.safe_load(f).get("accounts", [])
    except FileNotFoundError:
        accounts = []
    acc = accounts[0] if accounts else {}

    config = BotConfig()
    config.name = acc.get('name', 'debug')
    config.server = acc.get('server', config.server)
    from utils.paths import account_file
    config.cookie_file = acc.get('cookies') or str(account_file(config.name, 'cookies'))
    config.notifier = create_notifier(config)

    store = SettingsStore(config.name, acc)
    config.settings_store = store
    config.evasion_enabled = store.feature('evasion_enabled', True)

    email = acc.get('email') or os.getenv("TRAVIAN_EMAIL")
    password = acc.get('password') or os.getenv("TRAVIAN_PASSWORD")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = browser.new_context(
            viewport=get_random_viewport(),
            user_agent=get_random_user_agent(),
        )
        page = context.new_page()
        try:
            from playwright_stealth import Stealth
            stealth = Stealth()
            stealth.apply_stealth_sync(context)
            stealth.apply_stealth_sync(page)
            logging.info("🥷 Stealth активирован.")
        except Exception:
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

        cookie_manager = CookieManager(context, config.cookie_file)
        tasks_action = TasksAction(page, config)
        adventure_action = HeroAdventure(page, config)
        smart_builder = SmartBuilder(page, config, tasks_action, settings_store=store)
        farm_manager = FarmManager(page, config, settings_store=store)
        attack_monitor = AttackMonitor(page, config)
        troop_trainer = TroopTrainer(page, config, settings_store=store)
        trade_manager = TradeManager(page, config)

        menu_manager = MenuManager(
            page, smart_builder, adventure_action,
            tasks_action, farm_manager, config,
            attack_monitor=attack_monitor,
            troop_trainer=troop_trainer,
            trade_manager=trade_manager,
        )

        try:
            cookie_manager.load_cookies()
            page.goto(config.login_url)
            page.wait_for_load_state("domcontentloaded")
            if page.locator('input[name="name"]').is_visible():
                if not email or not password:
                    logging.error("❌ Куки не подошли, а TRAVIAN_EMAIL/TRAVIAN_PASSWORD не заданы.")
                    return
                logging.info("🔑 Вход по логину/паролю...")
                page.locator('input[name="name"]').fill(email)
                page.locator('input[name="password"]').fill(password)
                page.locator('button[type="submit"]').click()
                page.wait_for_selector('#sidebarBoxActiveVillage', timeout=15000)
                cookie_manager.save_cookie()
            else:
                logging.info("🍪 Вход по кукам.")
            # FIX: base_url теперь обновляется и при входе по кукам
            config.base_url = page.url.split("/dorf1.php")[0]

            menu_manager.show_menu()
        except Exception as e:
            logging.error(f"❌ Ошибка авторизации: {e}")
        finally:
            browser.close()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--interactive' in sys.argv:
        run_interactive()
    else:
        from runner import main
        main()
