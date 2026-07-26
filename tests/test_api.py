"""
Смоук-тесты HTTP-слоя дашборда (app.py).

До этих тестов у веб-части не было ни одного: PUT /api/accounts/{name}
падал с 500 на КАЖДОМ запросе (неверная арность upsert_gui_account), а CI
был зелёный, потому что compileall такое не ловит.

Тесты не трогают ни браузер, ни сеть: FastAPI TestClient ходит в приложение
напрямую, а корень проекта подменяется временным каталогом.

Запуск:  python -m unittest tests.test_api -v
"""
import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from fastapi.testclient import TestClient
    _HAS_TESTCLIENT = True
except Exception:  # httpx не установлен — не валим весь прогон
    _HAS_TESTCLIENT = False

from utils import paths as paths_mod


def _reload_app(token: str | None = None):
    """Перезагружает app.py с нужным DASHBOARD_TOKEN (он читается на импорте)."""
    if token is None:
        os.environ.pop("DASHBOARD_TOKEN", None)
    else:
        os.environ["DASHBOARD_TOKEN"] = token
    for mod in ("app", "utils.accounts", "utils.commands", "utils.settings_store"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    import app as app_module
    return importlib.reload(app_module)


@unittest.skipUnless(_HAS_TESTCLIENT, "нужен httpx для fastapi.testclient")
class ApiTestBase(unittest.TestCase):

    TOKEN = None

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._saved = (paths_mod.PROJECT_ROOT, paths_mod.DATA_DIR,
                       paths_mod.LOGS_DIR, paths_mod.PIDS_DIR)
        paths_mod.PROJECT_ROOT = self.dir
        paths_mod.DATA_DIR = self.dir / "data"
        paths_mod.LOGS_DIR = self.dir / "logs"
        paths_mod.PIDS_DIR = self.dir / "pids"
        # Пустой реестр аккаунтов во временном каталоге
        (self.dir / "accounts_gui.json").write_text(
            '{"accounts": [{"name": "Acc", "server": "ts1.x1.international.travian.com",'
            ' "proxy": "socks5://user:secret@1.2.3.4:9050"}]}', encoding="utf-8")
        self.app_module = _reload_app(self.TOKEN)
        self.client = TestClient(self.app_module.app)

    def tearDown(self):
        (paths_mod.PROJECT_ROOT, paths_mod.DATA_DIR,
         paths_mod.LOGS_DIR, paths_mod.PIDS_DIR) = self._saved
        os.environ.pop("DASHBOARD_TOKEN", None)
        shutil.rmtree(self.dir, ignore_errors=True)


class TestOpenMode(ApiTestBase):
    """Без DASHBOARD_TOKEN всё работает как раньше (локальный режим)."""

    def test_accounts_list_ok(self):
        r = self.client.get("/api/accounts")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([a["name"] for a in r.json()], ["Acc"])

    def test_proxy_password_is_not_exposed(self):
        # Регресс: раньше список аккаунтов отдавал прокси вместе с паролем.
        body = self.client.get("/api/accounts").text
        self.assertNotIn("secret", body)
        self.assertTrue(self.client.get("/api/accounts").json()[0]["has_proxy"])

    def test_put_account_saves_connection(self):
        # Регресс C4: этот роут возвращал 500 на каждом вызове.
        r = self.client.put("/api/accounts/Acc", json={"rate": 5})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/api/accounts").json()[0]["rate"], 5)

    def test_settings_roundtrip(self):
        r = self.client.post("/api/accounts/Acc/settings",
                             json={"farm": {"troops_per_raid": 7}})
        self.assertEqual(r.status_code, 200, r.text)
        got = self.client.get("/api/accounts/Acc/settings").json()
        self.assertEqual(got["farm"]["troops_per_raid"], 7)

    def test_out_of_range_setting_rejected(self):
        r = self.client.post("/api/accounts/Acc/settings",
                             json={"farm": {"interval_minutes": -5}})
        self.assertEqual(r.status_code, 422, r.text)

    def test_unknown_account_is_404_not_500(self):
        self.assertEqual(self.client.get("/api/accounts/Nope/settings").status_code, 404)

    def test_bad_rate_is_400_not_500(self):
        r = self.client.post("/api/accounts",
                             json={"name": "New", "server": "ts1.travian.com", "rate": "не число"})
        self.assertEqual(r.status_code, 400, r.text)


class TestNameValidation(ApiTestBase):
    """{name} из URL становится путём и подставляется в HTML — он обязан быть проверен."""

    BAD = ["..", "%2e%2e", "a b", 'x"onerror=alert(1)', "a.json"]

    def test_traversal_and_xss_names_rejected(self):
        for bad in self.BAD:
            for path in (f"/api/accounts/{bad}/logs",
                         f"/account/{bad}/logs",
                         f"/account/{bad}/farm",
                         f"/account/{bad}/analytics"):
                r = self.client.get(path)
                self.assertIn(r.status_code, (400, 404), f"{path} -> {r.status_code}")

    def test_stop_requires_known_account(self):
        # Раньше POST /api/accounts/<что угодно>/stop отвечал ok и делал
        # mkdir data/<что угодно>/ ещё до всякой проверки.
        r = self.client.post("/api/accounts/Nope/stop")
        self.assertIn(r.status_code, (400, 404))
        self.assertFalse((self.dir / "data" / "Nope").exists())

    def test_account_name_is_escaped_in_logs_page(self):
        r = self.client.get("/account/Acc/logs")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("<script>", r.text.lower().split("</head>")[0].replace(
            "<script>", "", 0))

    def test_analytics_page_renders_account_as_json_literal(self):
        r = self.client.get("/account/Acc/analytics")
        self.assertEqual(r.status_code, 200)
        self.assertIn('const ACCOUNT = "Acc"', r.text)
        self.assertNotIn("__ACCOUNT__", r.text)


class TestServerCheckSsrf(ApiTestBase):
    """/api/servers/check ходил куда угодно по строке из запроса."""

    def test_internal_targets_refused(self):
        for host in ("127.0.0.1:8080", "localhost", "169.254.169.254",
                     "10.0.0.1", "evil.com", "travian.com.attacker.net"):
            r = self.client.get("/api/servers/check", params={"host": host})
            self.assertEqual(r.status_code, 200)
            self.assertFalse(r.json().get("ok"), host)

    def test_response_does_not_leak_target(self):
        r = self.client.get("/api/servers/check", params={"host": "127.0.0.1:9"})
        self.assertNotIn("final_url", r.json())


class TestTokenMode(ApiTestBase):
    """С заданным DASHBOARD_TOKEN каждый роут закрыт."""

    TOKEN = "s3cret-token"

    def test_no_token_is_401(self):
        for method, path in (("get", "/api/accounts"),
                             ("get", "/"),
                             ("post", "/api/accounts/Acc/stop"),
                             ("delete", "/api/accounts/Acc")):
            r = getattr(self.client, method)(path)
            self.assertEqual(r.status_code, 401, f"{method} {path}")

    def test_wrong_token_is_401(self):
        r = self.client.get("/api/accounts", headers={"X-Auth-Token": "nope"})
        self.assertEqual(r.status_code, 401)

    def test_header_token_accepted(self):
        r = self.client.get("/api/accounts", headers={"X-Auth-Token": self.TOKEN})
        self.assertEqual(r.status_code, 200)

    def test_query_token_accepted(self):
        # Страницы открываются прямо в браузере — заголовок туда не подставить.
        self.assertEqual(self.client.get("/", params={"token": self.TOKEN}).status_code, 200)

    def test_openapi_schema_not_exposed(self):
        # /openapi.json и /docs — обычные роуты Starlette, глобальная
        # зависимость их не покрывает, поэтому они отключены при включённом токене.
        for path in ("/openapi.json", "/docs", "/redoc"):
            self.assertEqual(self.client.get(path).status_code, 404, path)


if __name__ == "__main__":
    unittest.main()
