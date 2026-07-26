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
import copy
import re
from bs4 import BeautifulSoup


# bidi-маркеры, неразрывные пробелы и разделители разрядов. Убираем ДО
# поиска чисел: без этого «1 750» разваливалось на 1 и 750 (в статистику
# уходило 1), а «1.250» — на 1 и 250.
_SEPARATORS_RE = re.compile('[\\u202a-\\u202e\\u200b\\u200e\\u200f\\ufeff\\u00a0\\s.,]')


def _nums(text: str) -> list[int]:
    """Все числа из текста (устойчиво к bidi-символам ‭ ‬ и разделителям
    разрядов). Знак минуса сохраняем — иначе координата (-83|36) читалась
    как (83|36) и один оазис расползался на две строки в аналитике."""
    cleaned = _SEPARATORS_RE.sub('', text or '')
    return [int(n) for n in re.findall(r'-?\d+', cleaned)]


def _num(text: str) -> int:
    n = _nums(text)
    return n[0] if n else 0


def _outcome_from_class(cls) -> str:
    """Тип исхода по классу иконки. Сравниваем ЦЕЛЫЕ классы: подстрочный
    поиск считал 'iReport21' (отчёт о приключении) за 'iReport2'."""
    if isinstance(cls, str):
        classes = set(cls.split())
    else:
        classes = set(cls or ())
    if 'iReport3' in classes:
        return 'lost'
    if 'iReport2' in classes:
        return 'won_losses'
    return 'won'


# «Деревня Samopal проводит набег на …» — имя деревни-нападающего.
# Нужно, чтобы отличить НАШ набег от набега НА НАС: подпись у обоих
# одинаковая, и оборонительные отчёты попадали в нашу добычу.
_ATTACKER_RE = re.compile(
    r'(?:деревня|village|dorf|villaggio|aldea)\s+(.+?)\s+'
    r'(?:проводит|нападает|совершает|атакует|raids?|attacks?|greift)',
    re.IGNORECASE,
)


def _attacker_from_subject(text: str) -> str | None:
    """Имя деревни-нападающего из подписи отчёта или None, если разметка
    незнакомая (тогда вызывающий не фильтрует — лучше лишний отчёт,
    чем потерянная статистика)."""
    m = _ATTACKER_RE.search(text or '')
    if not m:
        return None
    name = re.sub(r'\s+', ' ', m.group(1)).strip()
    return name or None


# хвост вида "(83|36)" / "(-83|36)" после имени деревни
_COORDS_TAIL_RE = re.compile(r'\s*\(\s*-?\d+\s*\|\s*-?\d+\s*\)\s*$')


def parse_village_names(html: str) -> set:
    """Имена деревень аккаунта из сайдбара — он есть на ЛЮБОЙ странице игры,
    включая /report, так что список достаётся без лишней навигации.
    Нужен, чтобы отличить наш набег от набега на нас."""
    soup = BeautifulSoup(html or '', 'html.parser')
    names = set()
    for node in soup.select('.villageList .listEntry, #sidebarBoxVillages .listEntry'):
        # .name строго приоритетнее <a>: в <a> вместе с именем лежат
        # координаты и счётчики.
        el = node.select_one('.name') or node.select_one('a')
        if el is None:
            continue
        el = copy.copy(el)  # работаем с копией, дерево не портим
        for junk in el.select('.coordinates, .coordinatesWrapper, .coordinateX,'
                              ' .coordinateY, .coordinatePipe'):
            junk.decompose()
        nm = re.sub(r'\s+', ' ', el.get_text(" ", strip=True)).strip()
        nm = _COORDS_TAIL_RE.sub('', nm).strip()
        if nm:
            names.add(nm)
    return names


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
        icon_cls = icon.get('class', []) if icon else []

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
            # деревня-нападающий (None, если подпись незнакомая)
            'attacker': _attacker_from_subject(subj_text),
        })
    return out


_UNIT_CLASS_RE = re.compile(r'^u(\d+)$')

# Позиция героя в строке войск (t1..t10 + герой) — последняя, 11-я.
_HERO_SLOT = 11


def _unit_slot_from_icon(classes) -> int | None:
    """Позиция юнита (1-based, 11 = герой) по классу иконки uNN.

    Раньше индекс брался из enumerate() присутствующих иконок: в отчёте
    показываются только НЕнулевые колонки, поэтому герой (слот 11)
    сохранялся как names[2] и подпись войска в статистике была навсегда
    неверной. uNN у Travian сквозной по племенам (римляне 1-10,
    тевтоны 11-20, галлы 21-30, природа 31-40, ...), отсюда %10.
    """
    for cls in (classes or ()):
        if cls == 'uhero':
            return _HERO_SLOT
        m = _UNIT_CLASS_RE.match(cls)
        if m:
            n = int(m.group(1))
            if n > 0:
                return ((n - 1) % 10) + 1
    return None


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
        'names': {},  # {позиция(1-based) -> название юнита из alt иконки}
        'attacker': None,  # деревня-нападающий (для отсева чужих отчётов)
    }

    subj = soup.select_one('.subject')
    if subj:
        cx = subj.select_one('.coordinateX')
        cy = subj.select_one('.coordinateY')
        if cx and cy:
            res['x'], res['y'] = _num(cx.text), _num(cy.text)
        res['attacker'] = _attacker_from_subject(subj.get_text(" ", strip=True))

    attacker = soup.select_one('.role.attacker')
    if attacker:
        res['sent'] = _troop_row_counts(attacker, 'troopCount_small')
        res['dead'] = _troop_row_counts(attacker, 'troopDead_small')

        # Названия юнитов из строки иконок (td.uniticon img.unit alt="Фаланга").
        # Позицию берём из класса uNN, а не из порядка иконок — см.
        # _unit_slot_from_icon; иконки с неизвестным классом пропускаем,
        # чтобы не подписать чужое имя чужому слоту.
        for img in attacker.select('td.uniticon img.unit'):
            alt = (img.get('alt') or '').strip()
            if not alt:
                continue
            slot = _unit_slot_from_icon(img.get('class') or [])
            if slot is not None:
                res['names'][slot] = alt

        # Добыча: строка th="Добыча" в table.additionalInformation
        for tr in attacker.select('table.additionalInformation tbody.infos tr'):
            th = tr.select_one('th')
            if not th or 'Добыч' not in th.get_text():
                continue
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
