"""
Тест умных уведомлений (utils.alerts.check_alerts): алерт шлётся один раз на
переходе «стало плохо» и повторяется только после того, как условие ушло и
вернулось. Без сети — нотифаер подменяем на счётчик вызовов.

Запуск:  python3 -m unittest tests.test_alerts -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.alerts import check_alerts


class FakeNotifier:
    def __init__(self):
        self.calls = []
    def hero_died(self):                 self.calls.append(("hero_died",))
    def crop_starving(self, v, p):       self.calls.append(("crop_starving", v, p))
    def storage_full(self, v, r):        self.calls.append(("storage_full", v, r))


def _village(name, prod_crop=100, wood=0, wcap=8000):
    return {
        "name": name,
        "resources": {
            "production": {"crop": prod_crop},
            "storage": {"wood": wood, "clay": 0, "iron": 0, "crop": 0},
            "capacity": {"wood": wcap, "clay": wcap, "iron": wcap, "crop": wcap},
        },
    }


class AlertsTest(unittest.TestCase):
    def test_hero_death_fires_once_then_rearms(self):
        n, state = FakeNotifier(), {}
        alive = {"hero": {"health": 80, "status": "дома"}, "villages": []}
        dead = {"hero": {"health": 0, "status": "мёртв"}, "villages": []}
        self.assertEqual(check_alerts(alive, n, state), [])
        self.assertIn("hero_dead", check_alerts(dead, n, state))      # переход → алерт
        self.assertEqual(check_alerts(dead, n, state), [])            # держится → молчим
        check_alerts(alive, n, state)                                 # ожил
        self.assertIn("hero_dead", check_alerts(dead, n, state))      # снова умер → алерт
        self.assertEqual(sum(1 for c in n.calls if c[0] == "hero_died"), 2)

    def test_crop_starving_on_negative_production(self):
        n, state = FakeNotifier(), {}
        ok = {"villages": [_village("Столица", prod_crop=50)]}
        bad = {"villages": [_village("Столица", prod_crop=-30)]}
        self.assertEqual(check_alerts(ok, n, state), [])
        fired = check_alerts(bad, n, state)
        self.assertIn("crop_Столица", fired)
        self.assertIn(("crop_starving", "Столица", -30), n.calls)

    def test_storage_full_when_at_capacity(self):
        n, state = FakeNotifier(), {}
        ok = {"villages": [_village("Столица", wood=5000, wcap=8000)]}
        full = {"villages": [_village("Столица", wood=8000, wcap=8000)]}
        self.assertEqual(check_alerts(ok, n, state), [])
        self.assertIn("full_Столица_wood", check_alerts(full, n, state))
        self.assertIn(("storage_full", "Столица", "дерево"), n.calls)

    def test_empty_stats_no_crash(self):
        n, state = FakeNotifier(), {}
        self.assertEqual(check_alerts({}, n, state), [])
        self.assertEqual(check_alerts(None, n, state), [])
        self.assertEqual(n.calls, [])


if __name__ == "__main__":
    unittest.main()
