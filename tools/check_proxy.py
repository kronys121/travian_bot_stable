"""
Диагностика прокси: показывает, с какого IP бот реально выходит в сеть.

Проверяет ровно те три пути, которыми ходит бот:
  1. requests напрямую (без прокси)      — ваш настоящий IP, для сравнения;
  2. requests через прокси               — монитор атак и сканер карты;
  3. локальный HTTP->SOCKS5 туннель      — то, что видит браузер (Chromium).

Если пункты 2 и 3 показывают IP прокси, а не ваш — прокси работает.
Если совпадает с пунктом 1 — трафик идёт мимо прокси.

Запуск:
    python tools/check_proxy.py socks5://user:pass@host:1080
    python tools/check_proxy.py --account Start1      # взять прокси из реестра

ВНИМАНИЕ: скрипт делает запрос к внешнему сервису (по умолчанию
https://api.ipify.org), чтобы узнать исходящий адрес. Свой сервис можно
задать через --url.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Консоль Windows по умолчанию cp1251 — без этого печать эмодзи роняет скрипт.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import requests

from utils.accounts import get_account, requests_proxies, split_proxy, validate_proxy
from utils.proxy_tunnel import ProxyTunnelError, Socks5Tunnel

DEFAULT_URL = "https://api.ipify.org"
TIMEOUT = 20


def _get(url, proxies=None):
    try:
        r = requests.get(url, proxies=proxies, timeout=TIMEOUT)
        return r.text.strip()[:80] if r.ok else f"HTTP {r.status_code}"
    except Exception as e:
        return f"ОШИБКА: {type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description="Проверка прокси бота")
    ap.add_argument("proxy", nargs="?", help="строка прокси, напр. socks5://user:pass@host:1080")
    ap.add_argument("--account", help="взять прокси из config.yaml / accounts_gui.json")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"чем узнавать IP (умолч. {DEFAULT_URL})")
    args = ap.parse_args()

    proxy_str = args.proxy
    if args.account:
        acc = get_account(args.account)
        if acc is None:
            print(f"❌ Аккаунт '{args.account}' не найден.")
            return 1
        proxy_str = acc.get("proxy") or ""
    if not proxy_str:
        print("❌ Прокси не задан. Укажи строкой или через --account.")
        return 1

    parsed = split_proxy(proxy_str)
    if not parsed:
        print(f"❌ Строку не удалось разобрать: {proxy_str!r}")
        print("   Ожидается host:port или scheme://[user:pass@]host:port")
        return 1

    shown = dict(parsed)
    if shown.get("password"):
        shown["password"] = "***"
    print(f"Разобрано: {shown}")
    print(f"Туннель для браузера нужен: {'да' if Socks5Tunnel.needed(proxy_str) else 'нет'}"
          f"  (нужен только для socks5 с логином/паролем)")
    print()

    ok, err = validate_proxy(proxy_str, timeout=10)
    print(f"1. TCP до {parsed['host']}:{parsed['port']} .... {'OK' if ok else 'НЕТ: ' + err}")
    if not ok:
        print("\n❌ Хост прокси недоступен — дальше проверять нечего.")
        return 1

    direct = _get(args.url)
    print(f"2. Без прокси (ваш IP) ......... {direct}")

    via_requests = _get(args.url, requests_proxies(proxy_str))
    print(f"3. requests через прокси ....... {via_requests}")

    try:
        with Socks5Tunnel(proxy_str) as tunnel:
            cfg = tunnel.playwright_proxy()
            if cfg and cfg["server"].startswith("http://127.0.0.1"):
                via_tunnel = _get(args.url, {"http": cfg["server"], "https": cfg["server"]})
                print(f"4. Через туннель (браузер) ..... {via_tunnel}")
            else:
                via_tunnel = via_requests
                print("4. Туннель не нужен — браузер идёт через прокси напрямую.")
    except ProxyTunnelError as e:
        via_tunnel = f"ОШИБКА: {e}"
        print(f"4. Через туннель (браузер) ..... {via_tunnel}")

    print()
    good = [v for v in (via_requests, via_tunnel) if not v.startswith("ОШИБКА") and v != direct]
    if len(good) == 2:
        print("✅ Прокси работает: и прямые запросы, и браузер выходят с чужого IP.")
        return 0
    if via_requests == direct:
        print("❌ requests идут МИМО прокси — виден настоящий IP.")
    if via_tunnel == direct:
        print("❌ Браузерный путь идёт МИМО прокси — виден настоящий IP.")
    for name, val in (("requests", via_requests), ("туннель", via_tunnel)):
        if isinstance(val, str) and val.startswith("ОШИБКА"):
            print(f"❌ {name}: {val}")
            if "SOCKS5 authentication failed" in val:
                print("   -> прокси не принял логин/пароль")
            elif "Connection refused" in val or "timed out" in val:
                print("   -> прокси не пускает наружу (или это не SOCKS5, а HTTP)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
