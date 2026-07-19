"""
Тесты выбора очереди тренировки по деревням (TroopTrainer._get_train_queue).

Ключевое: очередь конкретной деревни — решающая. Если у деревни задан
ключ (даже пустой) — используется он; пустая очередь = не тренировать,
без фолбэка на глобальную. Только для деревни БЕЗ своего ключа работает
фолбэк «*» → глобальная → старый одиночный формат.

Запуск:  python3 -m unittest tests.test_train_queue -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.troop_trainer import TroopTrainer


def make_trainer(settings: dict) -> TroopTrainer:
    t = TroopTrainer.__new__(TroopTrainer)
    t.settings = settings
    t.settings_store = None
    return t


class TestTrainQueue(unittest.TestCase):
    def test_village_own_queue_used(self):
        t = make_trainer({"village_queues": {
            "Столица": [{"troop_type_index": 1, "target_count": 200, "building": "barracks"}],
            "Деревня 2": [{"troop_type_index": 4, "target_count": 50, "building": "stable"}],
        }})
        q = t._get_train_queue("Столица")
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["troop_type_index"], 1)
        self.assertEqual(q[0]["target_count"], 200)

    def test_empty_village_queue_trains_nothing(self):
        # У деревни есть КЛЮЧ, но очередь пустая → ничего не тренируем,
        # НЕ падаем на глобальную (это и был баг: тренировал «как для всех»).
        t = make_trainer({
            "village_queues": {"Деревня 2": []},
            "queue": [{"troop_type_index": 1, "target_count": 100, "building": "barracks"}],
        })
        self.assertEqual(t._get_train_queue("Деревня 2"), [])

    def test_unconfigured_village_falls_back_to_global(self):
        # Деревни нет в village_queues → фолбэк на глобальную очередь.
        t = make_trainer({
            "village_queues": {"Столица": [{"troop_type_index": 1, "target_count": 200}]},
            "queue": [{"troop_type_index": 2, "target_count": 80, "building": "barracks"}],
        })
        q = t._get_train_queue("Новая деревня")
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["troop_type_index"], 2)
        self.assertEqual(q[0]["target_count"], 80)

    def test_star_rule_for_unconfigured(self):
        t = make_trainer({"village_queues": {
            "*": [{"troop_type_index": 3, "target_count": 30, "building": "barracks"}],
        }})
        q = t._get_train_queue("Любая")
        self.assertEqual(q[0]["troop_type_index"], 3)

    def test_old_single_format_fallback(self):
        t = make_trainer({"troop_type_index": 5, "target_count": 120, "building": "stable"})
        q = t._get_train_queue("Деревня")
        self.assertEqual(q, [{"troop_type_index": 5, "target_count": 120, "building": "stable"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
