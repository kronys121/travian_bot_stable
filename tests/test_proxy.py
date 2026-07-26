"""
Тесты прокси: разбор строки, выбор транспорта и локальный HTTP->SOCKS5 туннель.

Здесь поднимается НАСТОЯЩИЙ мини-SOCKS5-сервер с логином/паролем и проверяется,
что через туннель проходит CONNECT — то, ради чего туннель и написан
(Chromium не умеет SOCKS5-авторизацию и раньше такой прокси просто отклонялся).

Сеть наружу не нужна: всё крутится на 127.0.0.1.

Запуск:  python -m unittest tests.test_proxy -v
"""
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.accounts import parse_proxy, requests_proxies, split_proxy
from utils.proxy_tunnel import Socks5Tunnel


# ─────────────────────────── мини-SOCKS5 сервер ───────────────────────────

class FakeSocks5(threading.Thread):
    """SOCKS5 с обязательной авторизацией по логину/паролю (RFC 1928 + 1929)."""

    def __init__(self, user=b"bot", password=b"s3cret"):
        super().__init__(daemon=True)
        self.user, self.password = user, password
        self.saw_auth = None          # какие креды реально прислал клиент
        self.requested_host = None    # какое имя клиент попросил резолвить
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.srv.settimeout(0.5)
        self.port = self.srv.getsockname()[1]
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()
        try:
            self.srv.close()
        except OSError:
            pass

    def run(self):
        while not self._stop.is_set():
            try:
                client, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, c):
        try:
            c.settimeout(5)
            # --- приветствие: VER, NMETHODS, METHODS
            head = c.recv(2)
            if len(head) < 2:
                return
            c.recv(head[1])
            c.sendall(b"\x05\x02")            # выбираем метод 0x02 (user/pass)

            # --- авторизация: VER, ULEN, UNAME, PLEN, PASSWD
            c.recv(1)
            ulen = c.recv(1)[0]
            user = c.recv(ulen)
            plen = c.recv(1)[0]
            pwd = c.recv(plen)
            self.saw_auth = (user, pwd)
            if (user, pwd) != (self.user, self.password):
                c.sendall(b"\x01\x01")        # отказ
                return
            c.sendall(b"\x01\x00")            # успех

            # --- запрос: VER, CMD, RSV, ATYP, ADDR, PORT
            hdr = c.recv(4)
            if len(hdr) < 4:
                return
            atyp = hdr[3]
            if atyp == 1:                      # IPv4
                host = socket.inet_ntoa(c.recv(4))
            elif atyp == 3:                    # доменное имя (rdns)
                host = c.recv(c.recv(1)[0]).decode()
            else:
                return
            port = int.from_bytes(c.recv(2), "big")
            self.requested_host = host

            try:
                remote = socket.create_connection((host, port), timeout=5)
            except OSError:
                c.sendall(b"\x05\x01\x00\x01" + b"\x00" * 6)   # general failure
                return
            c.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)       # succeeded
            self._pipe(c, remote)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    @staticmethod
    def _pipe(a, b):
        def fwd(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
        t = threading.Thread(target=fwd, args=(b, a), daemon=True)
        t.start()
        fwd(a, b)
        t.join(timeout=5)


class EchoServer(threading.Thread):
    """Цель за прокси: отвечает фиксированной строкой и закрывает соединение."""

    def __init__(self, payload=b"HELLO-FROM-TARGET"):
        super().__init__(daemon=True)
        self.payload = payload
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.srv.settimeout(0.5)
        self.port = self.srv.getsockname()[1]
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()
        try:
            self.srv.close()
        except OSError:
            pass

    def run(self):
        while not self._stop.is_set():
            try:
                c, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            try:
                c.recv(4096)
                c.sendall(self.payload)
            except OSError:
                pass
            finally:
                try:
                    c.close()
                except OSError:
                    pass


# ────────────────────────────── сами тесты ──────────────────────────────

class TestProxyStringParsing(unittest.TestCase):

    def test_needed_only_for_socks5_with_credentials(self):
        self.assertTrue(Socks5Tunnel.needed("socks5://u:p@1.2.3.4:1080"))
        self.assertFalse(Socks5Tunnel.needed("socks5://1.2.3.4:1080"))   # без логина Chromium умеет
        self.assertFalse(Socks5Tunnel.needed("http://u:p@1.2.3.4:8080"))  # http-авторизацию умеет
        self.assertFalse(Socks5Tunnel.needed(""))
        self.assertFalse(Socks5Tunnel.needed(None))

    def test_needed_survives_password_with_slash(self):
        # Регресс: слэш в пароле заканчивал netloc для urlparse, логин терялся,
        # туннель не поднимался — и Chromium падал на socks5-авторизации.
        # Ровно так и выглядело «SOCKS не работает, только HTTP».
        self.assertTrue(Socks5Tunnel.needed("socks5://user:pa/ss@1.2.3.4:1080"))

    def test_needed_covers_socks5h_scheme(self):
        self.assertTrue(Socks5Tunnel.needed("socks5h://u:p@1.2.3.4:1080"))

    def test_needed_is_case_insensitive(self):
        self.assertTrue(Socks5Tunnel.needed("SOCKS5://u:p@1.2.3.4:1080"))

    def test_parse_proxy_never_hands_chromium_socks5h(self):
        # Chromium не понимает схему socks5h — запуск падал бы целиком.
        self.assertEqual(parse_proxy("socks5h://1.2.3.4:1080")["server"],
                         "socks5://1.2.3.4:1080")

    def test_split_proxy_keeps_special_characters_in_password(self):
        p = split_proxy("socks5://user:pa/s@s@1.2.3.4:1080")
        self.assertEqual(p["host"], "1.2.3.4")
        self.assertEqual(p["port"], 1080)
        self.assertEqual(p["username"], "user")
        self.assertEqual(p["password"], "pa/s@s")

    def test_split_proxy_rejects_garbage(self):
        for bad in ("", None, "не прокси", "host-без-порта", "http://host:порт", "1.2.3.4:99999"):
            self.assertIsNone(split_proxy(bad), bad)

    def test_requests_proxies_uses_socks5h_for_remote_dns(self):
        # socks5h, а не socks5: иначе имя резолвится у нас и DNS-запрос
        # уходит с настоящего IP, выдавая местоположение.
        p = requests_proxies("socks5://u:p@1.2.3.4:1080")
        self.assertEqual(p["https"], "socks5h://u:p@1.2.3.4:1080")
        self.assertEqual(p["http"], p["https"])

    def test_requests_proxies_escapes_special_characters(self):
        p = requests_proxies("socks5://us er:p@ss/word@1.2.3.4:1080")
        self.assertIn("us%20er", p["https"])
        self.assertIn("p%40ss%2Fword", p["https"])
        self.assertTrue(p["https"].endswith("@1.2.3.4:1080"))

    def test_requests_proxies_plain_http(self):
        self.assertEqual(requests_proxies("http://1.2.3.4:8080")["https"], "http://1.2.3.4:8080")

    def test_requests_proxies_empty(self):
        self.assertIsNone(requests_proxies(""))
        self.assertIsNone(requests_proxies(None))

    def test_bare_host_port_defaults_to_http(self):
        self.assertEqual(requests_proxies("1.2.3.4:8080")["https"], "http://1.2.3.4:8080")
        self.assertEqual(parse_proxy("1.2.3.4:8080")["server"], "http://1.2.3.4:8080")


class TestTunnelPassthrough(unittest.TestCase):
    """Без socks5-авторизации туннель не поднимается и отдаёт прокси как есть."""

    def test_http_proxy_is_passed_through_untouched(self):
        with Socks5Tunnel("http://u:p@1.2.3.4:8080") as t:
            self.assertEqual(t.playwright_proxy(),
                             {"server": "http://1.2.3.4:8080", "username": "u", "password": "p"})

    def test_no_proxy_gives_none(self):
        with Socks5Tunnel("") as t:
            self.assertIsNone(t.playwright_proxy())

    def test_exit_is_safe_without_enter(self):
        # runner зовёт __exit__ в общем finally, даже если прокси не настроен.
        Socks5Tunnel("").__exit__(None, None, None)


class TestTunnelEndToEnd(unittest.TestCase):
    """Полный путь: клиент -> локальный туннель -> SOCKS5 с паролем -> цель."""

    def setUp(self):
        self.target = EchoServer()
        self.target.start()
        self.socks = FakeSocks5()
        self.socks.start()
        self.tunnel = Socks5Tunnel(f"socks5://bot:s3cret@127.0.0.1:{self.socks.port}")
        self.tunnel.__enter__()

    def tearDown(self):
        self.tunnel.__exit__(None, None, None)
        self.socks.stop()
        self.target.stop()

    def _connect_through_tunnel(self, host, port, timeout=10):
        cfg = self.tunnel.playwright_proxy()
        _, _, hostport = cfg["server"].partition("://")
        thost, tport = hostport.split(":")
        s = socket.create_connection((thost, int(tport)), timeout=timeout)
        s.settimeout(timeout)
        s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        return s

    def test_tunnel_listens_on_localhost_http(self):
        cfg = self.tunnel.playwright_proxy()
        self.assertTrue(cfg["server"].startswith("http://127.0.0.1:"))
        # Playwright-конфиг туннеля не должен содержать креды: их знает туннель
        self.assertNotIn("username", cfg)

    def test_connect_reaches_target_through_socks5_auth(self):
        s = self._connect_through_tunnel("127.0.0.1", self.target.port)
        head = s.recv(4096)
        self.assertIn(b"200", head.split(b"\r\n")[0])
        s.sendall(b"GET / HTTP/1.1\r\n\r\n")
        body = s.recv(4096)
        s.close()
        self.assertEqual(body, b"HELLO-FROM-TARGET")
        # Пароль реально дошёл до SOCKS5-сервера — авторизация состоялась
        self.assertEqual(self.socks.saw_auth, (b"bot", b"s3cret"))

    def test_hostname_is_resolved_by_the_proxy_not_by_us(self):
        # ATYP=3 (доменное имя) означает, что DNS делает прокси. Если бы
        # резолвили мы, сервер увидел бы готовый IPv4 (ATYP=1) и наш DNS-запрос
        # ушёл бы в сеть с настоящего адреса.
        s = self._connect_through_tunnel("localhost", self.target.port)
        s.recv(4096)
        s.close()
        self.assertEqual(self.socks.requested_host, "localhost")

    def test_dead_upstream_returns_502_instead_of_dropping(self):
        # Цель выключена: раньше туннель молча рвал соединение и Chromium
        # показывал невнятный ERR_EMPTY_RESPONSE.
        self.target.stop()
        closed_port = self.target.port
        s = self._connect_through_tunnel("127.0.0.1", closed_port)
        head = s.recv(4096)
        s.close()
        self.assertIn(b"502", head.split(b"\r\n")[0])


class TestMonitorTrafficGoesThroughProxy(unittest.TestCase):
    """
    Главный фикс: поток мониторинга атак ходит на dorf1.php обычным requests,
    мимо браузера. Раньше он делал это НАПРЯМУЮ — с настоящего IP машины и с
    куками аккаунта, каждые 2 минуты. Прокси при этом терял всякий смысл.
    """

    def setUp(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><div class='typ'><span class='att1'>x</span></div></html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = self.http.server_port
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.socks = FakeSocks5()
        self.socks.start()

    def tearDown(self):
        self.http.shutdown()
        self.socks.stop()

    def test_requests_session_reaches_target_via_socks5_with_auth(self):
        import requests
        session = requests.Session()
        session.proxies.update(
            requests_proxies(f"socks5://bot:s3cret@127.0.0.1:{self.socks.port}")
        )
        resp = session.get(f"http://127.0.0.1:{self.http_port}/dorf1.php", timeout=10)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("att1", resp.text)
        # Доказательство, что трафик реально прошёл через прокси, а не напрямую
        self.assertEqual(self.socks.saw_auth, (b"bot", b"s3cret"))

    def test_session_without_proxy_never_touches_it(self):
        # Контроль: без прокси SOCKS5-сервер не видит ни одного соединения —
        # именно так и вёл себя монитор до починки.
        import requests
        requests.Session().get(f"http://127.0.0.1:{self.http_port}/dorf1.php", timeout=10)
        self.assertIsNone(self.socks.saw_auth)


class TestMapScannerGoesThroughProxy(unittest.TestCase):
    """
    Сканер оазисов бьёт по /api/v1/map/tile-details напрямую через requests:
    полный скан радиуса 10 — это сотни запросов с куками аккаунта. Они обязаны
    идти через прокси, иначе один скан «светит» настоящий IP сотни раз подряд.
    """

    class _FakeCtx:
        @staticmethod
        def cookies():
            return [{"name": "JSESSIONID", "value": "abc", "domain": "travian.com"}]

    class _FakePage:
        context = None

    def _session_for(self, config):
        from actions.oasis_action import FarmManager
        fm = FarmManager.__new__(FarmManager)     # без браузера и настроек
        page = self._FakePage()
        page.context = self._FakeCtx()
        fm.page = page
        fm.config = config
        return fm._get_session()

    def test_session_uses_configured_proxy(self):
        class Cfg:
            requests_proxies = {"http": "socks5h://u:p@1.2.3.4:1080",
                                "https": "socks5h://u:p@1.2.3.4:1080"}
            user_agent = "Mozilla/5.0 (X11; Linux x86_64) TestUA/1.0"
        s = self._session_for(Cfg())
        self.assertEqual(s.proxies.get("https"), "socks5h://u:p@1.2.3.4:1080")
        self.assertEqual(s.headers["User-Agent"], Cfg.user_agent)

    def test_session_without_proxy_config_still_works(self):
        # Аккаунт без прокси — сессия просто без proxies, не падает.
        class Cfg:
            pass
        s = self._session_for(Cfg())
        self.assertFalse(s.proxies)
        self.assertIn("Chrome", s.headers["User-Agent"])

    def test_runner_publishes_proxy_and_ua_on_config(self):
        # Страховка от расхождения: сканер читает config.requests_proxies /
        # config.user_agent, а заполняет их runner. Если имена разъедутся,
        # прокси молча перестанет применяться — поэтому проверяем связь.
        src = (Path(__file__).parent.parent / "runner.py").read_text(encoding="utf-8")
        self.assertIn("config.requests_proxies", src)
        self.assertIn("config.user_agent", src)


class TestTunnelStartupFailure(unittest.TestCase):

    def test_bad_credentials_surface_as_502_not_a_hang(self):
        socks_srv = FakeSocks5(user=b"bot", password=b"right")
        socks_srv.start()
        tunnel = Socks5Tunnel(f"socks5://bot:wrong@127.0.0.1:{socks_srv.port}")
        tunnel.__enter__()
        try:
            cfg = tunnel.playwright_proxy()
            _, _, hostport = cfg["server"].partition("://")
            thost, tport = hostport.split(":")
            s = socket.create_connection((thost, int(tport)), timeout=10)
            s.settimeout(10)
            s.sendall(b"CONNECT 127.0.0.1:9 HTTP/1.1\r\n\r\n")
            head = s.recv(4096)
            s.close()
            self.assertIn(b"502", head.split(b"\r\n")[0])
        finally:
            tunnel.__exit__(None, None, None)
            socks_srv.stop()


if __name__ == "__main__":
    unittest.main()
