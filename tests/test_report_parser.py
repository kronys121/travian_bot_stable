"""
Тесты парсера боевых отчётов (actions/report_parser.py).

HTML воспроизводит реальную разметку сервера, включая bidi-символы
(‭ U+202D, ‬ U+202C) вокруг чисел в координатах и добыче.

Запуск:  python3 -m unittest tests.test_report_parser -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from actions.report_parser import parse_report_list, parse_report_detail

# bidi-маркеры как на сервере
LRO = "\u202d"
PDF = "\u202c"


def _coord(x, y):
    return (f'{LRO}<span class="coordinates coordinatesWrapper">'
            f'<span class="coordinateX">({LRO}{x}{PDF}</span>'
            f'<span class="coordinatePipe">|</span>'
            f'<span class="coordinateY">{LRO}{y}{PDF})</span></span>{PDF}')


LIST_HTML = f"""
<table id="overview" class="row_table_data"><tbody>
  <tr>
    <td class="sel"><input class="check report" type="checkbox" name="ids[]" value="12892031"></td>
    <td class="sub ">
      <img class="iReport iReport1 " alt="выиграли без потерь">
      <a class="reportInfoIcon" href="/build.php?id=39&tt=2&reportId=12892031&readReport=1">
        <img alt="111/350" class="reportInfo carry half"></a>
      <div class=""><a href="?id=12892031%7C35445117&s=1">Деревня Samopal проводит набег на Свободный оазис {_coord(83, 36)}</a></div>
    </td>
    <td class="dat">сегодня, 21:08</td>
  </tr>
  <tr>
    <td class="sel"><input class="check report" type="checkbox" name="ids[]" value="12518965"></td>
    <td class="sub ">
      <img class="iReport iReport2 " alt="выиграли, но с потерями">
      <a class="reportInfoIcon" href="/build.php?id=39&tt=2&reportId=12518965&readReport=1">
        <img alt="8/315" class="reportInfo carry half"></a>
      <div class=""><a href="?id=12518965%7Cb033aeb0&s=1">Деревня Samopal проводит набег на Свободный оазис {_coord(94, 55)}</a></div>
    </td>
    <td class="dat">сегодня, 18:37</td>
  </tr>
  <tr>
    <td class="sel"><input class="check report" type="checkbox" name="ids[]" value="12559965"></td>
    <td class="sub ">
      <img class="iReport iReport3 " alt="вы проиграли">
      <div class=""><a href="?id=12559965%7C9eba7ce4&s=1">Деревня Samopal проводит набег на Свободный оазис {_coord(92, 59)}</a></div>
    </td>
    <td class="dat">сегодня, 18:53</td>
  </tr>
  <tr>
    <td class="sel"><input class="check report" type="checkbox" name="ids[]" value="12720736"></td>
    <td class="sub ">
      <img class="iReport iReport21 " alt="Отчёт о приключении">
      <div class=""><a class="adventure" href="?id=12720736&s=1">Деревня Samopal исследований</a></div>
    </td>
    <td class="dat">сегодня, 19:58</td>
  </tr>
  <tr>
    <td class="sel"><input class="check report" type="checkbox" name="ids[]" value="12703539"></td>
    <td class="sub ">
      <img class="iReport iReport22 " alt="Поселенцы основали деревню">
      <div class=""><a href="?id=12703539&s=1">Деревня Samopal основал деревню.</a></div>
    </td>
    <td class="dat">сегодня, 19:51</td>
  </tr>
</tbody></table>
"""


def _unit_row(marker, counts):
    """counts: список из 11 значений (t1..t10 + герой)."""
    cells = "".join(
        f'<td class="unit{" last" if i == 10 else ""}">{c}</td>'
        for i, c in enumerate(counts)
    )
    return f'<tbody class="units"><tr><th><i class="{marker}"> </i></th>{cells}</tr></tbody>'


DETAIL_HTML = f"""
<div id="reportWrapper">
  <div class="header"><div class="headline"><div class="subject">
    Деревня Samopal проводит набег на Свободный оазис {_coord(83, 36)}</div></div></div>
  <div class="body">
    <div class="role attacker">
      <div class="header"><h2>Нападение</h2></div>
      <table>
        <tbody class="units"><tr><th class="coords"></th>
          <td class="uniticon"><img class="unit u21" alt="Фаланга"></td>
          <td class="uniticon last"><img class="unit uhero" alt="Герой"></td>
        </tr></tbody>
        {_unit_row("troopCount_small", [10,0,0,0,0,0,0,0,0,0,0])}
        {_unit_row("troopDead_small",  [0,0,0,0,0,0,0,0,0,0,0])}
      </table>
      <table class="additionalInformation"><tbody class="infos"><tr>
        <th>Добыча</th>
        <td><div><div class="res"><div class="inlineIconList resourceWrapper">
          <div class="inlineIcon resources"><i class="lumber"></i><span class="value ">60</span></div>
          <div class="inlineIcon resources"><i class="clay"></i><span class="value ">17</span></div>
          <div class="inlineIcon resources"><i class="iron"></i><span class="value ">17</span></div>
          <div class="inlineIcon resources"><i class="crop"></i><span class="value ">17</span></div>
        </div></div>
        <div class="inlineIcon carry"><i class="carry half"></i><span class="value ">{LRO}{LRO}111{PDF}/{LRO}350{PDF}{PDF}</span></div></div></td>
      </tr></tbody></table>
    </div>
    <div class="role defender">
      <div class="header"><h2>Оборона</h2></div>
      <table>
        <tbody class="units"><tr><th class="coords"></th>
          <td class="uniticon"><img class="unit u31" alt="Крыса"></td>
        </tr></tbody>
        {_unit_row("troopCount_small", [0,0,0,0,0,0,0,0,0,0,0])}
        {_unit_row("troopDead_small",  [0,0,0,0,0,0,0,0,0,0,0])}
      </table>
    </div>
  </div>
</div>
"""


class TestReportList(unittest.TestCase):
    def setUp(self):
        self.rows = parse_report_list(LIST_HTML)
        self.by_id = {r['id']: r for r in self.rows}

    def test_all_rows_parsed(self):
        self.assertEqual(len(self.rows), 5)

    def test_raid_flag(self):
        self.assertTrue(self.by_id['12892031']['is_raid'])
        self.assertTrue(self.by_id['12518965']['is_raid'])
        self.assertTrue(self.by_id['12559965']['is_raid'])  # проигранный набег — тоже набег
        self.assertFalse(self.by_id['12720736']['is_raid'])  # приключение
        self.assertFalse(self.by_id['12703539']['is_raid'])  # основание деревни

    def test_coords(self):
        self.assertEqual((self.by_id['12892031']['x'], self.by_id['12892031']['y']), (83, 36))
        self.assertEqual((self.by_id['12518965']['x'], self.by_id['12518965']['y']), (94, 55))

    def test_loot_and_capacity(self):
        self.assertEqual(self.by_id['12892031']['looted'], 111)
        self.assertEqual(self.by_id['12892031']['capacity'], 350)
        self.assertEqual(self.by_id['12518965']['looted'], 8)

    def test_outcome(self):
        self.assertEqual(self.by_id['12892031']['outcome'], 'won')
        self.assertEqual(self.by_id['12518965']['outcome'], 'won_losses')
        self.assertEqual(self.by_id['12559965']['outcome'], 'lost')

    def test_lost_raid_has_no_loot(self):
        self.assertEqual(self.by_id['12559965']['looted'], 0)

    def test_detail_href(self):
        self.assertEqual(self.by_id['12892031']['detail_href'], '?id=12892031%7C35445117&s=1')


class TestReportDetail(unittest.TestCase):
    def setUp(self):
        self.d = parse_report_detail(DETAIL_HTML)

    def test_coords(self):
        self.assertEqual((self.d['x'], self.d['y']), (83, 36))

    def test_loot_breakdown(self):
        self.assertEqual(self.d['loot'], {'lumber': 60, 'clay': 17, 'iron': 17, 'crop': 17})
        self.assertEqual(self.d['looted_total'], 111)

    def test_capacity(self):
        self.assertEqual(self.d['capacity'], 350)

    def test_sent_and_troop_index(self):
        # отправлено 10 юнитов типа t1 (первая колонка), потерь нет
        self.assertEqual(self.d['sent'], {1: 10})
        self.assertEqual(self.d['dead'], {})
        self.assertEqual(self.d['troop_index'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
