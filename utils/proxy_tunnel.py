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


def _free_port() -> int:
    """Найти свободный TCP-порт на localhost."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        """Открыть TCP-сокет до target_host:target_port через SOCKS5 с авторизацией."""
        s = socks.socksocket()
        s.set_proxy(
            socks.SOCKS5,
            self.socks_host,
            self.socks_port,
            username=self.socks_user,
            password=self.socks_pass,
        )
        s.settimeout(30)
        s.connect((target_host, target_port))
        return s

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

    def _handle(self):
        # Читаем первую строку запроса
        buf = b""
        while b"\r\n" not in buf:
            chunk = self.client.recv(4096)
            if not chunk:
                return
            buf += chunk

        first_line, rest = buf.split(b"\r\n", 1)
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

            # Дочитываем заголовки до пустой строки
            header_buf = rest
            while b"\r\n\r\n" not in header_buf:
                chunk = self.client.recv(4096)
                if not chunk:
                    return
                header_buf += chunk

            remote = self._make_socks5_socket(host, port)
            self.client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self._pipe(self.client, remote)

        else:
            # Обычный HTTP (GET/POST) — Travian не использует, но на всякий случай
            target = parts[1].decode(errors="replace")
            u = urlparse(target if target.startswith("http") else "http://" + target)
            host = u.hostname or ""
            port = u.port or 80

            remote = self._make_socks5_socket(host, port)
            # Перестраиваем запрос без прокси-заголовков
            path = u.path or "/"
            if u.query:
                path += "?" + u.query
            rebuilt = method + b" " + path.encode() + b" HTTP/1.1\r\n" + rest
            remote.sendall(rebuilt)
            self._pipe(self.client, remote)


class _TunnelServer(threading.Thread):
    """Слушает localhost:port, принимает соединения от Playwright."""

    def __init__(self, port: int,
                 socks_host: str, socks_port: int,
                 socks_user: str | None, socks_pass: str | None):
        super().__init__(daemon=True)
        self.port = port
        self.socks_host = socks_host
        self.socks_port = socks_port
        self.socks_user = socks_user
        self.socks_pass = socks_pass
        self._stop_event = threading.Event()
        self._srv: socket.socket | None = None

    def run(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", self.port))
        self._srv.listen(64)
        self._srv.settimeout(1.0)
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

    @staticmethod
    def needed(proxy_str: str | None) -> bool:
        """True если прокси — socks5 с логином/паролем (Chromium не поддерживает)."""
        if not proxy_str:
            return False
        raw = str(proxy_str).strip()
        if "://" not in raw:
            raw = "http://" + raw
        u = urlparse(raw)
        return u.scheme.lower() == "socks5" and bool(u.username)

    def __enter__(self) -> "Socks5Tunnel":
        raw = self._proxy_str
        if "://" not in raw:
            raw = "http://" + raw
        u = urlparse(raw)

        if self.needed(self._proxy_str):
            if not _PYSOCKS_OK:
                raise RuntimeError(
                    "PySocks не установлен. Выполни: pip install PySocks\n"
                    "Без него SOCKS5 с паролем не работает."
                )
            self._port = _free_port()
            self._server = _TunnelServer(
                port=self._port,
                socks_host=u.hostname,
                socks_port=u.port or 1080,
                socks_user=u.username,
                socks_pass=u.password,
            )
            self._server.start()
            logger.info(
                f"[proxy_tunnel] HTTP->SOCKS5 туннель запущен: "
                f"127.0.0.1:{self._port} -> {u.hostname}:{u.port}"
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
