[Русский](README.md) | English

# Travian Bot

A bot for Travian Legends written in Python and Playwright. It builds your village from a plan, farms oases, trains troops, upgrades them in the smithy, sends the hero on adventures, trades through the NPC merchant, watches for incoming attacks and evacuates troops, and shows all of it in a web panel with settings and statistics.

It runs several accounts at once: each one gets its own process, its own cookies and its own proxy. The browser is real (Chromium via Playwright) with a stealth mode, and delays and clicks imitate a human.

> Important: automating the game breaks Travian's rules. This project was made for personal use and for learning, use it at your own risk.

## What it looks like

The dashboard, an account card with statistics (resources, troops, hero, farm stats with net profit):

![Dashboard](docs/dashboard-en.png)

Account settings: modules toggle on the fly, night mode, farming, per-village training, smithy, build templates, trading:

![Account settings](docs/dashboard-settings-en.png)

## What it can do

Building:
- Smart plan-based builder (SmartBuilder): keeps the queue full, computes the effective level accounting for a slot already under construction, and never queues a redundant upgrade.
- Ready-made per-village build templates: standard x1, fast start x1 (focus on culture points and early settling), non-raid x3/x5, Gauls x1, farmer, capital, offense, defense.
- Free-crop check before an upgrade so you do not go negative on upkeep.
- Building through video ads (section2, minus 25% time), with a fallback to the normal way.
- Night mode: during set hours the bot sleeps, but building and the smithy can be left running at night.

Farming:
- Map scan around the village, marking oases (empty, with animals, occupied, crop oases).
- Raids by a list of troops plus separate hero farming of animals (based on hero strength).
- Animal re-check right before sending: if animals have spawned in the oasis, the raid is cancelled.
- Never sends a leftover: if there are fewer troops than the raid requires, that type is skipped instead of flying in part.
- On-disk cooldowns (they survive a restart), accounting for travel time to the target and back.

Troops and smithy:
- Training toward a target with a separate queue for each village.
- Counts troops at home plus in transit (on raids and returning), so it does not re-train when the army is out farming.
- Auto-upgrade of units in the smithy by priority, optionally through ads.

Hero, quests, celebrations:
- Auto-adventures, optionally with watching a video (to shorten the time or raise the difficulty).
- Collecting task rewards and daily quests.
- Auto-celebrations in the Town Hall for culture points.

Defense and monitoring:
- A separate thread watches for incoming attacks and, when needed, pulls all troops out in a single raid (evasion) with a cooldown.
- Statistics collection: resources, troops, hero, build queue for each village.
- Battle report parsing: loot by resource, losses, profit by troop type.
- Farm statistics with net profit (loot minus the cost of lost troops) and a dedicated page with interactive charts.

Trading and logistics:
- NPC exchange when warehouses overflow.
- Moving surplus resources between your own villages by rules.

Management:
- FastAPI web panel: per-account settings on the fly, start and stop individually, logs, statistics.
- Telegram mini-app and notifications (captcha, attacks, important events) if you set a token.
- Scheduler: one task at a time, task order set by drag and drop, urgent tasks (evasion, scan) cut to the front.
- Batched village round mode: everything for a village is done in one visit, fewer switches.

## Tech stack

- Python 3.11
- Playwright 1.44 (Chromium, sync API) plus playwright-stealth
- BeautifulSoup4 for page parsing
- requests and PySocks for direct map-tile requests and SOCKS5 proxies
- FastAPI and uvicorn for the control panel
- PyYAML and python-dotenv for configs and secrets

## Installation

You need Python 3.11+.

```bash
git clone https://github.com/kronys121/travian_bot_stable.git
cd travian_bot_stable

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

## Configuration

Accounts can be set two ways: with a `config.yaml` file or straight from the panel (then they land in `accounts_gui.json`). Secrets are best kept in `.env`. These files are not committed to the repo (they are in .gitignore), you create them yourself.

Example `config.yaml`:

```yaml
accounts:
  - name: main
    server: ts30.x3.international.travian.com
    rate: 1               # server speed: 1, 3, 5
    headless: false       # true - no browser window
    proxy: ""             # socks5://user:pass@host:port, empty - no proxy
    sleep_hours: [2, 8]   # night mode 02:00-08:00, can be changed in the panel
    # you can put the login here, or move it to .env (see below)
    email: ""
    password: ""
    # telegram notifications (optional)
    telegram_token: ""
    telegram_chat_id: ""
```

Example `.env` (an alternative to the login in yaml):

```env
# shared login if you have one account
TRAVIAN_EMAIL=you@example.com
TRAVIAN_PASSWORD=your_password

# or per account name (name from config.yaml) if there are several
TRAVIAN_EMAIL_main=you@example.com
TRAVIAN_PASSWORD_main=your_password

# telegram for all accounts at once
TELEGRAM_TOKEN=123456:abc
TELEGRAM_CHAT_ID=123456789
```

The login priority is: account fields, then `TRAVIAN_EMAIL_<name>`, then the shared `TRAVIAN_EMAIL`. If the cookies are still alive, the bot logs in with them, so the email and password are only needed for the first login.

## Running

The control panel (the recommended way):

```bash
uvicorn app:app --port 8080
```

Open [http://localhost:8080](http://127.0.0.1:8080). From here you can add an account, enable the features you want, start and stop the bot, and view logs and statistics. Each account runs as its own process.

Running the bots directly, without the panel:

```bash
# all accounts from config.yaml and accounts_gui.json
python runner.py

# a single account by name
python runner.py --account main
```

A manual menu for debugging a single account (opens a browser with a window):

```bash
python main.py --interactive
```

## Control panel

- Dashboard at `/`: a card per account with the current status, resources, troops, hero, build queue and incoming attacks.
- Modules toggle on the fly with switches: farming, building, training, smithy, adventures, celebrations, NPC exchange, transfer, evasion, report reading and others.
- Settings by section: farming (units, distance, cooldowns), training (a queue per village), smithy, per-village build template, trading and transfer.
- Night mode: the toggle and the hours are set right in the panel.
- Logs behind a button (`/account/<name>/logs`).
- Farm statistics with charts (`/account/<name>/farm`): loot by day and resource, profit by troop, top oases, net profit accounting for losses.
- Telegram mini-app at `/miniapp`.

## Project layout

```
main.py                production run and debug menu
runner.py              Chromium launch, authorization, task scheduler
app.py                 FastAPI: panel, accounts API, mini-app
telegram_miniapp.py    HTML of the telegram mini-app
config/                config and build plans (templates)
services/              builder, training, trading, scheduler, cookies, notifications, menu
actions/               oasis farming, adventures, attack monitoring, smithy, statistics, quests, celebrations, reports
utils/                 base action class, locators, accounts, settings, proxy, paths, i18n
static/                web panel and the farm statistics page
tests/                 unit tests of pure logic
```

Each account's data lives in `data/<account>/`: cookies, status, statistics, build progress. Account settings sit in `bot_settings_<account>.json`. All of this is created automatically and is not committed to the repo.

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

The tests cover pure logic without a browser or network: the night window, build template selection, report and oasis parsers, troop counting, the training queue.

## Notes

- Playwright runs in sync mode, so all browser code is synchronous. FastAPI is async, but the bot spins in a separate process.
- Game selectors are gathered in `utils/locators.py`. When Travian changes its markup, this is the first file to fix.
- Some features (report reading, charts) load Chart.js from a CDN, so the machine running the bot needs internet (it needs it for the game anyway).
