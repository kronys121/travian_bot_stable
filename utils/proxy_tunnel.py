"""
proxy_tunnel.py — локальный HTTP-прокси-туннель для обхода ограничения Chromium:
"Browser does not support socks5 proxy authentication".

Chromium поддерживает SOCKS5 без логина/пароля, но не с аутентификацией.
Решение: поднять на свободном localhost-порту простой HTTP-прокси,
который авторизуется в SOCKS5 сам — Playwright видит его как обычный http://127.0.0.1:PORT.

Использование в runner.py:
    from utils.proxy_tunnel import Socks5Tunnel
    with Socks5Tunnel(proxy_str) as tunnel:
        launch_kwargs["proxy"] = tunnel.playwright_proxy()
        browser = p.chromium.launch(**launch_kwargs)

Если proxy_str не содержит credentials или схема не socks5 — туннель не нужен,
Socks5Tunnel.needed(proxy_str) вернёт False и обёртка ничего не делает.
"""

from __future__ import annotations

import socket
import threading
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Проверка зависимости
# ──────────────────────────────────────────────────────────────────────────────
try:
    import socks  # PySocks
    _PYSOCKS_OK = True
except ImportError:
    _PYSOCKS_OK = False


class ProxyTunnelError(RuntimeError):
    """Туннель не удалось поднять — запускать браузер без прокси нельзя."""


# ──────────────────────────────────────────────────────────────────────────────
# Однопоточный HTTP-прокси (CONNECT + plain GET/POST)
# ──────────────────────────────────────────────────────────────────────────────

class _TunnelHandler(threading.Thread):
    """Обрабатывает одно входящее соединение от браузера."""

    BUF = 65536

    def __init__(self, client: socket.socket,
                 socks_host: str, socks_port: int,
                 socks_user: str | None, socks_pass: str | None):
        super().__init__(daemon=True)
        self.client = client
        self.socks_host = socks_host
        self.socks_port = socks_port
        self.socks_user = socks_user
        self.socks_pass = socks_pass

    def _make_socks5_socket(self, target_host: str, target_port: int) -> socket.socket:
        """Открыть TCP-сокет до target_host:target_port через SOCKS5 с авторизацией.

        rdns=True (по умолчанию у socksocket) — имя резолвит сам прокси.
        Иначе DNS-запрос ушёл бы с нашего IP и выдал реальное местоположение.
        """
        s = socks.socksocket()
        s.set_proxy(
            socks.SOCKS5,
            self.socks_host,
            self.socks_port,
            rdns=True,
            username=self.socks_user,
            password=self.socks_pass,
        )
        s.settimeout(30)
        s.connect((target_host, target_port))
        return s

    def _fail(self, status: bytes, why: str):
        """Ответить браузеру внятной ошибкой, а не молча закрыть сокет."""
        logger.warning(f"[proxy_tunnel] {why}")
        try:
            self.client.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\n"
                                b"Connection: close\r\n\r\n")
        except OSError:
            pass

    def _pipe(self, a: socket.socket, b: socket.socket):
        """Двунаправленная прокачка трафика между двумя сокетами."""
        def fwd(src, dst):
            try:
                while True:
                    data = src.recv(self.BUF)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                logging.debug("suppressed error in utils/proxy_tunnel:88", exc_info=True)
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        logging.debug("suppressed error in utils/proxy_tunnel:94", exc_info=True)

        t = threading.Thread(target=fwd, args=(b, a), daemon=True)
        t.start()
        fwd(a, b)
        t.join()

    def run(self):
        try:
            self._handle()
        except Exception as e:
            logger.debug(f"[proxy_tunnel] handler error: {e}")
        finally:
            try:
                self.client.close()
            except Exception:
                logging.debug("suppressed error in utils/proxy_tunnel:110", exc_info=True)

    MAX_HEADER = 64 * 1024

    def _handle(self):
        # Читаем запрос целиком до конца заголовков.
        # БЫЛО: сначала ждали первую \r\n, а потом искали \r\n\r\n в ОСТАТКЕ.
        # Для запроса без единого заголовка ("CONNECT host:port HTTP/1.1\r\n\r\n")
        # в остатке лежит ровно "\r\n" — и цикл вечно ждал данных, которые
        # никто уже не пришлёт. Соединение висело до таймаута.
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.client.recv(4096)
            if not chunk:
                return
            buf += chunk
            if len(buf) > self.MAX_HEADER:
                self._fail(b"431 Request Header Fields Too Large", "слишком длинные заголовки")
                return

        head, _, pending = buf.partition(b"\r\n\r\n")
        first_line, _, rest = head.partition(b"\r\n")
        parts = first_line.split(b" ")
        if len(parts) < 2:
            return
        method = parts[0].upper()

        if method == b"CONNECT":
            # HTTPS-туннель: CONNECT host:port HTTP/1.1
            host_port = parts[1].decode(errors="replace")
            if ":" in host_port:
                host, port_s = host_port.rsplit(":", 1)
                port = int(port_s)
            else:
                host, port = host_port, 443

            # pending — то, что клиент прислал ВСЛЕД за заголовками (например
            # первые байты TLS, если он не стал ждать ответа). Раньше терялось.
            try:
                remote = self._make_socks5_socket(host, port)
            except Exception as e:
                # Раньше соединение просто рвалось, и Chromium показывал
                # непонятный ERR_EMPTY_RESPONSE вместо причины.
                self._fail(b"502 Bad Gateway", f"SOCKS5 не дал соединение до {host}:{port}: {e}")
                return
            self.client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            if pending:
                remote.sendall(pending)
            self._pipe(self.client, remote)

        else:
            # Обычный HTTP (GET/POST) — Travian не использует, но на всякий случай
            target = parts[1].decode(errors="replace")
            u = urlparse(target if target.startswith("http") else "http://" + target)
            host = u.hostname or ""
            port = u.port or 80

            try:
                remote = self._make_socks5_socket(host, port)
            except Exception as e:
                self._fail(b"502 Bad Gateway", f"SOCKS5 не дал соединение до {host}:{port}: {e}")
                return
            # Перестраиваем запрос: в абсолютной форме (proxy-style) origin-сервер
            # его не поймёт. rest — заголовки уже без завершающей пустой строки,
            # поэтому терминатор дописываем сами, а следом — тело, если оно было.
            path = u.path or "/"
            if u.query:
                path += "?" + u.query
            rebuilt = (method + b" " + path.encode() + b" HTTP/1.1\r\n"
                       + rest + b"\r\n\r\n" + pending)
            remote.sendall(rebuilt)
            self._pipe(self.client, remote)


class _TunnelServer(threading.Thread):
    """Слушает localhost:port, принимает соединения от Playwright."""

    def __init__(self, socks_host: str, socks_port: int,
                 socks_user: str | None, socks_pass: str | None):
        super().__init__(daemon=True)
        self.socks_host = socks_host
        self.socks_port = socks_port
        self.socks_user = socks_user
        self.socks_pass = socks_pass
        self._stop_event = threading.Event()

        # Слушающий сокет открываем ЗДЕСЬ, а не в run().
        # Было две проблемы: (1) bind() в потоке — гонка, Chromium успевал
        # постучаться раньше, чем сокет начинал слушать, и получал
        # ERR_PROXY_CONNECTION_FAILED; (2) исключение из run() умирало вместе
        # с потоком, и бот стартовал «с прокси», которого на самом деле нет.
        # Порт 0 = ядро само выдаёт свободный (без гонки за занятый порт).
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(64)
        self._srv.settimeout(1.0)
        self.port = self._srv.getsockname()[1]

    def run(self):
        while not self._stop_event.is_set():
            try:
                client, _ = self._srv.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            _TunnelHandler(
                client,
                self.socks_host, self.socks_port,
                self.socks_user, self.socks_pass,
            ).start()

    def stop(self):
        self._stop_event.set()
        if self._srv:
            try:
                self._srv.close()
            except Exception:
                logging.debug("suppressed error in utils/proxy_tunnel:205", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
# Публичный API
# ──────────────────────────────────────────────────────────────────────────────

class Socks5Tunnel:
    """
    Контекстный менеджер.  Если туннель нужен — запускает его, иначе no-op.

    with Socks5Tunnel(proxy_str) as tunnel:
        pw_proxy = tunnel.playwright_proxy()  # None или {"server": "http://127.0.0.1:PORT"}
        if pw_proxy:
            launch_kwargs["proxy"] = pw_proxy
        browser = p.chromium.launch(**launch_kwargs)
    """

    def __init__(self, proxy_str: str | None):
        self._proxy_str = proxy_str or ""
        self._server: _TunnelServer | None = None
        self._port: int | None = None
        self._original_proxy: dict | None = None   # для случая без туннеля

    # socks5h — та же схема, только DNS резолвит прокси. Chromium её вообще
    # не знает, так что для него это тем более случай «нужен туннель».
    SOCKS_SCHEMES = ("socks5", "socks5h")

    @staticmethod
    def needed(proxy_str: str | None) -> bool:
        """True если прокси — socks5 с логином/паролем (Chromium не поддерживает).

        Разбор через split_proxy, а НЕ через urlparse. С urlparse тут было две
        дыры, и обе выглядели одинаково — «SOCKS не работает, только HTTP»:
          - пароль со слэшем (socks5://user:pa/ss@host:port): слэш заканчивал
            netloc, логин терялся, needed() возвращал False, туннель не
            поднимался, и Chromium получал socks5 с авторизацией, которую
            не умеет;
          - схема socks5h:// не совпадала с жёстким == "socks5".
        """
        from utils.accounts import split_proxy
        p = split_proxy(proxy_str)
        if not p:
            return False
        return p["scheme"] in Socks5Tunnel.SOCKS_SCHEMES and bool(p["username"])

    def __enter__(self) -> "Socks5Tunnel":
        from utils.accounts import split_proxy
        p = split_proxy(self._proxy_str)

        if p and self.needed(self._proxy_str):
            if not _PYSOCKS_OK:
                raise ProxyTunnelError(
                    "PySocks не установлен. Выполни: pip install PySocks — "
                    "без него SOCKS5 с логином/паролем не работает."
                )
            try:
                self._server = _TunnelServer(
                    socks_host=p["host"],
                    socks_port=p["port"],
                    socks_user=p["username"],
                    socks_pass=p["password"],
                )
            except OSError as e:
                raise ProxyTunnelError(f"не удалось открыть локальный порт туннеля: {e}") from e
            self._port = self._server.port
            self._server.start()
            logger.info(
                f"[proxy_tunnel] HTTP->SOCKS5 туннель запущен: "
                f"127.0.0.1:{self._port} -> {p['host']}:{p['port']}"
            )
        else:
            # Не socks5-с-паролем — используем прокси напрямую как раньше
            from utils.accounts import parse_proxy
            self._original_proxy = parse_proxy(self._proxy_str)

        return self

    def playwright_proxy(self) -> dict | None:
        """Возвращает dict для Playwright launch(proxy=...) или None."""
        if self._server and self._port:
            return {"server": f"http://127.0.0.1:{self._port}"}
        return self._original_proxy

    def __exit__(self, *_):
        if self._server:
            self._server.stop()
            logger.info("[proxy_tunnel] Туннель остановлен.")
