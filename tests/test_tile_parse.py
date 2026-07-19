"""
Тест разбора попапа клетки (FarmManager._parse_tile_html) на реальном
HTML оазиса с животными (Кабан ×17, Волк ×13, Медведь ×9).

Запуск:  python3 -m unittest tests.test_tile_parse -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from actions.oasis_action import FarmManager

LRO = "\u202d"
PDF = "\u202c"

# Реальный ответ /api/v1/map/tile-details (поле html), сокращён до сути.
OASIS_HTML = f"""
<div id="tileDetails" class="oasis oasis-2">
  <h1 class="titleInHeader">Свободный оазис {LRO}<span class="coordinates coordinatesWrapper">
    <span class="coordinateX">({LRO}93{PDF}</span><span class="coordinatePipe">|</span>
    <span class="coordinateY">{LRO}41{PDF})</span></span>{PDF}</h1>
  <div id="map_details">
    <h4>Бонус</h4>
    <table id="distribution" class="transparent"><tbody>
      <tr><td class="ico"><i class="r1"></i></td><td class="val">{LRO}{LRO}25{PDF}%{PDF}</td><td class="desc">Древесина</td></tr>
    </tbody></table>
    <h4>Войска:</h4>
    <table id="troop_info" class="transparent"><tbody>
      <tr><td class="ico"><img class="unit u35" src="/img/x.gif" alt="Кабан"></td><td class="val">17</td><td class="desc">Кабанов</td></tr>
      <tr><td class="ico"><img class="unit u36" src="/img/x.gif" alt="Волк"></td><td class="val">13</td><td class="desc">Волков</td></tr>
      <tr><td class="ico"><img class="unit u37" src="/img/x.gif" alt="Медведь"></td><td class="val">9</td><td class="desc">Медведей</td></tr>
      <tr><td colspan="3"><a href="/build.php?id=39&tt=3&screen=combatSimulator&kid=64053" class="a arrow">Симулировать набег</a></td></tr>
    </tbody></table>
    <div id="oasis1InstantTabs" class="instantTabs">
      <div class="tabContainer">
        <table id="troop_info" class="rep transparent"><tbody><tr><td>Нет информации<br></td></tr></tbody></table>
      </div>
    </div>
  </div>
</div>
"""

EMPTY_OASIS_HTML = """
<div id="tileDetails" class="oasis oasis-1">
  <h1 class="titleInHeader">Свободный оазис (90|90)</h1>
  <div id="map_details">
    <h4>Войска:</h4>
    <table id="troop_info" class="transparent"><tbody>
      <tr><td colspan="3"><a href="#" class="a arrow">Симулировать набег</a></td></tr>
    </tbody></table>
  </div>
</div>
"""


class TestTileParse(unittest.TestCase):
    def setUp(self):
        self.fm = FarmManager.__new__(FarmManager)

    def test_oasis_with_animals(self):
        r = self.fm._parse_tile_html(OASIS_HTML)
        self.assertTrue(r["is_oasis"])
        self.assertFalse(r["is_conquered"])
        self.assertTrue(r["is_occupied"])
        self.assertFalse(r["has_player_troops"])
        self.assertEqual(r["animals"], {"u35": 17, "u36": 13, "u37": 9})

    def test_animal_defense_value(self):
        r = self.fm._parse_tile_html(OASIS_HTML)
        # Кабан 17*70, Волк 13*80, Медведь 9*140 (пехота) vs конная защита;
        # берём максимум из пехотной/конной.
        self.assertEqual(self.fm._animal_defense(r["animals"]), 3490)

    def test_empty_oasis_is_free(self):
        r = self.fm._parse_tile_html(EMPTY_OASIS_HTML)
        self.assertTrue(r["is_oasis"])
        self.assertFalse(r["is_occupied"])
        self.assertEqual(r["animals"], {})

    def test_empty_html_is_error(self):
        self.assertTrue(self.fm._parse_tile_html("").get("error"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
