"""
Тест подсчёта своих войск с обзора точки сбора (TroopTrainer._parse_owned_troops).

Считаем дом + в пути (набеги/возврат) — иначе после отправки войск на
оазисы бот видит «дома мало» и переобучает. HTML воспроизводит реальную
структуру tt=1 (table.troop_details[data-did] / .outRaid / .inReturn,
строка чисел tbody.units.last, ячейки td.unit / td.unit.none).

Запуск:  python3 -m unittest tests.test_owned_troops -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.troop_trainer import TroopTrainer


def _counts_row(counts):
    cells = "".join(
        f'<td class="unit{" none" if c == 0 else ""}">{c}</td>' for c in counts
    )
    return f'<tbody class="units last"><tr><th>Войска</th>{cells}</tr></tbody>'


def _table(cls, counts, extra=""):
    return f'<table class="{cls}" {extra}>{_counts_row(counts)}</table>'


# дом: t1=48, t4=2, t6=13, герой(t11)=1
HOME = _table("troop_details ", [48, 0, 0, 2, 0, 13, 0, 0, 0, 0, 1], 'data-did="34352"')
# возвращается набег: t1=10
IN_RETURN = _table("troop_details inReturn", [10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
# в пути набег: t4=10
OUT_RAID = _table("troop_details outRaid", [0, 0, 0, 10, 0, 0, 0, 0, 0, 0, 0])

PAGE = f'<div id="build">{IN_RETURN}{OUT_RAID}{HOME}</div>'


class TestOwnedTroops(unittest.TestCase):
    def setUp(self):
        self.t = TroopTrainer.__new__(TroopTrainer)

    def test_sum_home_and_moving(self):
        totals = self.t._parse_owned_troops(PAGE)
        self.assertEqual(totals.get(1), 58)   # 48 дома + 10 возвращается
        self.assertEqual(totals.get(4), 12)   # 2 дома + 10 в набеге
        self.assertEqual(totals.get(6), 13)   # 13 дома
        self.assertEqual(totals.get(11), 1)   # герой дома

    def test_home_only_when_no_movements(self):
        totals = self.t._parse_owned_troops(f'<div>{HOME}</div>')
        self.assertEqual(totals.get(1), 48)
        self.assertEqual(totals.get(4), 2)

    def test_no_tables_is_none(self):
        # страница без таблиц войск → None (неизвестно, не заказываем вслепую)
        self.assertIsNone(self.t._parse_owned_troops("<div>нет войск</div>"))
        self.assertIsNone(self.t._parse_owned_troops(""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
