"""
Unit-тесты чистой логики (без Playwright и сети).

Запуск:  cd travian_bot && python3 -m pytest tests/ -v
    или:  cd travian_bot && python3 -m unittest tests.test_pure_logic -v
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

# Позволяем запускать из корня репозитория и из travian_bot/
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.night_time import is_night, seconds_until_morning


class TestNightTime(unittest.TestCase):
    """Ночное окно sleep_hours: обычное и с переходом через полночь."""

    def test_empty_sleep_hours_is_never_night(self):
        self.assertFalse(is_night(()))
        self.assertFalse(is_night(None))
        self.assertFalse(is_night((23,)))

    def test_midnight_crossing_window(self):
        # окно 23 -> 7
        sh = (23, 7)
        self.assertTrue(is_night(sh, datetime(2026, 1, 1, 23, 30)))
        self.assertTrue(is_night(sh, datetime(2026, 1, 1, 2, 0)))
        self.assertTrue(is_night(sh, datetime(2026, 1, 1, 6, 59)))
        self.assertFalse(is_night(sh, datetime(2026, 1, 1, 7, 0)))
        self.assertFalse(is_night(sh, datetime(2026, 1, 1, 12, 0)))
        self.assertFalse(is_night(sh, datetime(2026, 1, 1, 22, 59)))

    def test_same_day_window(self):
        # окно 1 -> 5 (без перехода через полночь)
        sh = (1, 5)
        self.assertTrue(is_night(sh, datetime(2026, 1, 1, 3, 0)))
        self.assertFalse(is_night(sh, datetime(2026, 1, 1, 0, 30)))
        self.assertFalse(is_night(sh, datetime(2026, 1, 1, 5, 0)))

    def test_seconds_until_morning_before_midnight(self):
        # 23:00, утро в 7:00 -> 8 часов
        sh = (23, 7)
        s = seconds_until_morning(sh, datetime(2026, 1, 1, 23, 0))
        self.assertEqual(s, 8 * 3600)

    def test_seconds_until_morning_after_midnight(self):
        # 5:00, утро в 7:00 -> 2 часа
        sh = (23, 7)
        s = seconds_until_morning(sh, datetime(2026, 1, 1, 5, 0))
        self.assertEqual(s, 2 * 3600)

    def test_seconds_until_morning_no_window(self):
        self.assertEqual(seconds_until_morning((), default=1800), 1800)

    def test_seconds_until_morning_minimum(self):
        # 6:59:30, утро в 7:00 -> минимум 60 секунд
        sh = (23, 7)
        s = seconds_until_morning(sh, datetime(2026, 1, 1, 6, 59, 30))
        self.assertGreaterEqual(s, 60)


class TestBuildTemplates(unittest.TestCase):
    """Выбор плана стройки из шаблонов."""

    def test_known_template_returns_plan(self):
        from config.build_templates import TEMPLATES, get_template_plan
        for tid in TEMPLATES:
            plan = get_template_plan(tid, fallback_x1=[('a', 1)], fallback_x3=[('b', 1)])
            self.assertIsInstance(plan, list, f"template {tid}")
            if tid != 'none':  # 'none' — пустой план (стройка отключена)
                self.assertGreater(len(plan), 0, f"template {tid} is empty")

    def test_unknown_template_falls_back(self):
        from config.build_templates import get_template_plan
        fb = [('fallback', 1)]
        plan = get_template_plan('no_such_template', fallback_x1=fb, fallback_x3=[])
        self.assertEqual(plan, fb)


try:
    import yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


@unittest.skipUnless(_HAS_YAML, "pyyaml не установлен")
class TestResolveCredentials(unittest.TestCase):
    """Приоритет источников логина/пароля."""

    def test_account_fields_priority(self):
        from utils.accounts import resolve_credentials
        email, password = resolve_credentials(
            {'email': 'a@b.c', 'password': 'secret', 'name': 'x'}
        )
        self.assertEqual(email, 'a@b.c')
        self.assertEqual(password, 'secret')

    def test_missing_returns_none(self):
        import os
        from utils.accounts import resolve_credentials
        # подчищаем возможные env-переменные для чистоты теста
        saved = {}
        for k in list(os.environ):
            if k.startswith('TRAVIAN_'):
                saved[k] = os.environ.pop(k)
        try:
            email, password = resolve_credentials({'name': 'zzz_nonexistent'})
            self.assertIsNone(email)
            self.assertIsNone(password)
        finally:
            os.environ.update(saved)


class TestSettingsStoreDefaults(unittest.TestCase):
    """Дефолтные настройки: ключевые фичи присутствуют."""

    def test_default_settings_shape(self):
        from utils.settings_store import DEFAULT_SETTINGS
        feats = DEFAULT_SETTINGS.get('features', DEFAULT_SETTINGS)
        for key in ('build_enabled', 'build_night_enabled', 'build_use_ads'):
            self.assertIn(key, feats, f"missing default: {key}")

    def test_build_night_disabled_by_default(self):
        from utils.settings_store import DEFAULT_SETTINGS
        feats = DEFAULT_SETTINGS.get('features', DEFAULT_SETTINGS)
        self.assertFalse(feats['build_night_enabled'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
