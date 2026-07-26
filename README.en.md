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

Custom build-template editor: add buildings, set the target level, drag ⠿ to reorder, tribe-aware (the wall and unique buildings have different IDs per tribe):

![Build template editor](docs/build-editor-en.png)

## What it can do

Building:
- Smart plan-based builder (SmartBuilder): keeps the queue full, computes the effective level accounting for a slot already under construction, and never queues a redundant upgrade.
- Ready-made per-village build templates: standard x1, fast start x1 (focus on culture points and early settling), non-raid x3/x5, Gauls x1, farmer, capital, offense, defense.
- A custom build-template editor right in the panel: a builder with a list of buildings, target levels and order (drag by ⠿), aware of the different building IDs per tribe.
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
- Hero HP threshold: a wounded hero is not sent to farm or adventures (configurable).
- Collecting task rewards and daily quests.
- Auto-celebrations in the Town Hall for culture points.

Defense and monitoring:
- A separate thread watches for incoming attacks and, when needed, pulls all troops out in a single raid (evasion) with a cooldown.
- Statistics collection: resources, troops, hero, build queue for each village.
- Battle report parsing: loot by resource, losses, profit by troop type.
- Farm statistics with net profit (loot minus the cost of lost troops) and a dedicated page with interactive charts.
- Analytics: resources, production, troops and hero HP over time on a dedicated page.
- Smart Telegram alerts: a screenshot on CAPTCHA, hero death, crop starvation, storage overflow (no spam - only on transition).

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

# password for the control panel (see below) — required if the port is reachable by anyone else
DASHBOARD_TOKEN=pick-a-long-random-string
```

The login priority is: account fields, then `TRAVIAN_EMAIL_<name>`, then the shared `TRAVIAN_EMAIL`. If the cookies are still alive, the bot logs in with them, so the email and password are only needed for the first login.

### Proxies

Four forms are supported, one proxy per account:

```
http://host:port
http://user:pass@host:port
socks5://host:port
socks5://user:pass@host:port
```

The last one is a special case: Chromium cannot authenticate to a SOCKS5 proxy. Such a proxy used to be rejected outright and the bot would not start; now a local HTTP→SOCKS5 tunnel is started for it (`utils/proxy_tunnel.py`), the browser sees a plain `http://127.0.0.1:<port>`, and the tunnel supplies the credentials. The port is picked automatically and lives exactly as long as the browser.

All of the account's traffic goes through the proxy, including the background incoming-attack check — it hits `dorf1.php` directly rather than through the browser. **Those requests used to bypass the proxy entirely, going out from the machine's real IP with the account's cookies every two minutes** — to the game the account looked active from two addresses at once. Hostnames are resolved by the proxy itself (`socks5h`), so DNS lookups do not leak your address either.

Proxy reachability is checked before the browser starts: if it does not answer, the bot refuses to start and writes the reason into its status instead of going into the game from your own address. The password may contain any character except a space — including `@` and `/`.

### Panel access

By default (`DASHBOARD_TOKEN` unset) the panel runs without a password — convenient on your own machine, and a warning about it is logged at startup. In that case bind it to localhost only:

```bash
uvicorn app:app --host 127.0.0.1 --port 8080
```

As soon as the port is reachable by anyone else — a tunnel for the Telegram mini-app, LAN forwarding, a VPS — set `DASHBOARD_TOKEN`. The panel fully controls the bot (start, stop, delete an account) and knows your proxy, so an open port means a given-away account.

With the token set, every request must carry it — either in the `X-Auth-Token` header or as a query parameter:

```
http://localhost:8080/?token=your-token
```

The pages propagate the token to all of their own requests and links, so opening the panel with such a link is enough. For the mini-app, use the same URL with `?token=` in the WebApp button you configure in BotFather.

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
- Analytics (`/account/<name>/analytics`): charts of resources, production, troops and hero HP over time.
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

All of an account's data lives in one place — `data/<account>/`: cookies, status, statistics, settings (`settings.json`), build progress, cooldowns, discovered oases, browser fingerprint. Some of these files used to be scattered across the repo root (`cooldowns_<acc>.json`, `occupied_oases_<acc>.json`, `bot_settings_<acc>.json` and others) — the old files are moved into `data/<account>/` automatically on the first run, nothing to do by hand. All of this is created automatically and is not committed to the repo.

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

The panel's HTTP tests need a client for `fastapi.testclient` (not a runtime dependency of the bot):

```bash
pip install httpx2
```

The linter that catches typos in variable names (neither `compileall` nor the tests see those):

```bash
pip install pyflakes && python -m pyflakes app.py runner.py main.py telegram_miniapp.py services actions utils config
```

The tests cover pure logic without a browser or network: the night window, build template selection, report and oasis parsers, troop counting, the training queue, smart alerts, and an encoding guard (no broken characters). The same checks run automatically on every push via GitHub Actions (`.github/workflows/ci.yml`).

## Notes

- Playwright runs in sync mode, so all browser code is synchronous. FastAPI is async, but the bot spins in a separate process.
- Game selectors are gathered in `utils/locators.py`. When Travian changes its markup, this is the first file to fix.
- Some features (report reading, charts) load Chart.js from a CDN, so the machine running the bot needs internet (it needs it for the game anyway).
