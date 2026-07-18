"""
Парсер боевых отчётов Travian (страница /report и отдельный отчёт).

Чистые функции над HTML — без сети и Playwright, чтобы покрывать тестами.
Разметку берём как есть на сервере (см. tests/test_report_parser.py):

Список /report/overview:
  table#overview tbody tr
    td.sel input.check.report[value=<id>]        — id отчёта
    img.iReport.iReportN                          — тип (1=победа, 2=с потерями, 3=поражение)
    a.reportInfoIcon img.reportInfo.carry[alt="111/350"]  — добыча/вместимость
    td.sub a[href="?id=<id>|<hash>&s=1"]          — ссылка на отчёт + координаты цели

Отдельный отчёт:
  .subject .coordinateX/.coordinateY             — координаты цели
  .role.attacker table tbody.units               — 3 строки:
      иконки (td.uniticon img.unit.uXX),
      отправлено (th > i.troopCount_small + td.unit),
      погибло   (th > i.troopDead_small + td.unit)
  .role.attacker table.additionalInformation ... th="Добыча"
      .inlineIcon.resources (lumber/clay/iron/crop) + .value
"""
import re
from bs4 import BeautifulSoup


def _nums(text: str) -> list[int]:
    """Все группы цифр (устойчиво к bidi-символам ‭ ‬ вокруг чисел)."""
    return [int(n) for n in re.findall(r'\d+', text or '')]


def _num(text: str) -> int:
    n = _nums(text)
    return n[0] if n else 0


def _outcome_from_class(cls: str) -> str:
    if 'iReport3' in cls:
        return 'lost'
    if 'iReport2' in cls:
        return 'won_losses'
    return 'won'


def parse_report_list(html: str) -> list[dict]:
    """Возвращает список отчётов со страницы обзора.
    Каждый элемент: {id, x, y, is_raid, outcome, looted, capacity, detail_href}."""
    soup = BeautifulSoup(html or '', 'html.parser')
    out: list[dict] = []
    table = soup.select_one('table#overview')
    if not table:
        return out
    for tr in table.select('tbody tr'):
        cb = tr.select_one('input.check.report')
        if not cb or not cb.get('value'):
            continue
        rid = cb.get('value')

        icon = tr.select_one('img.iReport')
        icon_cls = ' '.join(icon.get('class', [])) if icon else ''

        subj = tr.select_one('td.sub a[href^="?id="]')
        subj_text = subj.get_text(" ", strip=True) if subj else ''
        is_raid = 'набег' in subj_text.lower()

        x = y = None
        if subj:
            cx = subj.select_one('.coordinateX')
            cy = subj.select_one('.coordinateY')
            if cx and cy:
                x, y = _num(cx.text), _num(cy.text)

        looted = capacity = 0
        carry = tr.select_one('a.reportInfoIcon img.reportInfo.carry, img.reportInfo.carry')
        if carry:
            pair = _nums(carry.get('alt', ''))
            if len(pair) >= 2:
                looted, capacity = pair[0], pair[1]

        out.append({
            'id': rid,
            'x': x,
            'y': y,
            'is_raid': is_raid and x is not None,
            'outcome': _outcome_from_class(icon_cls),
            'looted': looted,
            'capacity': capacity,
            'detail_href': subj.get('href') if subj else None,
        })
    return out


def _troop_row_counts(role, marker_class: str) -> dict:
    """Из строки с иконкой marker_class (troopCount_small/troopDead_small)
    собирает {позиция(1-based) -> число}. Позиция = тип войска tN, последняя = герой."""
    marker = role.select_one(f'i.{marker_class}')
    if not marker:
        return {}
    row = marker.find_parent('tr')
    if row is None:
        return {}
    result = {}
    for i, cell in enumerate(row.select('td.unit')):
        n = _num(cell.get_text())
        if n:
            result[i + 1] = n
    return result


def parse_report_detail(html: str) -> dict:
    """Разбирает отдельный отчёт о набеге.
    Возвращает {x, y, loot:{lumber,clay,iron,crop}, looted_total, capacity,
                sent:{idx:count}, dead:{idx:count}, troop_index}."""
    soup = BeautifulSoup(html or '', 'html.parser')
    res = {
        'x': None, 'y': None,
        'loot': {'lumber': 0, 'clay': 0, 'iron': 0, 'crop': 0},
        'looted_total': 0, 'capacity': 0,
        'sent': {}, 'dead': {}, 'troop_index': None,
    }

    subj = soup.select_one('.subject')
    if subj:
        cx = subj.select_one('.coordinateX')
        cy = subj.select_one('.coordinateY')
        if cx and cy:
            res['x'], res['y'] = _num(cx.text), _num(cy.text)

    attacker = soup.select_one('.role.attacker')
    if attacker:
        res['sent'] = _troop_row_counts(attacker, 'troopCount_small')
        res['dead'] = _troop_row_counts(attacker, 'troopDead_small')

        # Добыча: строка th="Добыча" в table.additionalInformation
        for tr in attacker.select('table.additionalInformation tbody.infos tr'):
            th = tr.select_one('th')
            if not th or 'Добыч' not in th.get_text():
                continue
            icons = tr.select('.inlineIconList .inlineIcon.resources, .inlineIcon.resources')
            for res_name in ('lumber', 'clay', 'iron', 'crop'):
                ic = tr.select_one(f'.inlineIcon.resources i.{res_name}')
                if ic:
                    val = ic.find_parent('div').select_one('.value')
                    res['loot'][res_name] = _num(val.text) if val else 0
            carry = tr.select_one('.inlineIcon.carry .value')
            if carry:
                pair = _nums(carry.get_text())
                if len(pair) >= 2:
                    res['capacity'] = pair[1]
            break

    res['looted_total'] = sum(res['loot'].values())
    if res['sent']:
        # доминирующий тип войск в набеге = с максимальным числом отправленных
        res['troop_index'] = max(res['sent'], key=lambda k: res['sent'][k])
    return res
