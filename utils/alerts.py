"""
Логика умных уведомлений: сравнивает свежую статистику с прошлым состоянием
и дёргает нужный метод нотифаера ТОЛЬКО на переходе «стало плохо» — чтобы не
слать одно и то же каждые 5 минут, пока условие держится.

Чистая функция (без сети/браузера) — легко тестируется.
"""
import logging


def check_alerts(stats: dict, notifier, state: dict) -> list:
    """Проверяет условия и шлёт уведомления через notifier.

    state — словарь-память между вызовами (ключ условия -> bool).
    Возвращает список сработавших ключей (удобно для тестов/логов).
    """
    fired = []
    if not stats:
        return fired

    def once(key, cond, fire):
        # БЫЛО: state[key] выставлялся ВСЕГДА, а результат fire() игнорировался.
        # Notifier.send() не бросает исключение, а возвращает False — поэтому
        # одна сетевая ошибка навсегда затыкала алерт: условие держится,
        # state[key] уже True, второй попытки не будет.
        ok = True
        if cond and not state.get(key):
            try:
                # None считаем успехом: часть методов нотифаера ничего не
                # возвращает. Провал — только явный False.
                ok = fire() is not False
            except Exception:
                ok = False
                logging.exception(f"❌ Не удалось отправить алерт {key}")
            if ok:
                fired.append(key)
        state[key] = bool(cond) and ok

    # Герой погиб
    hero = stats.get("hero") or {}
    hp = hero.get("health")
    hstatus = str(hero.get("status") or "").lower()
    dead = (hp == 0) or ("мёрт" in hstatus) or ("мертв" in hstatus) or ("dead" in hstatus)
    once("hero_dead", dead, lambda: notifier.hero_died())

    # По деревням: голод по зерну и переполнение складов (дерево/глина/железо)
    #
    # Ключ состояния раньше был просто именем деревни: две безымянные или
    # одноимённые деревни делили один слот, и вторая молча не уведомляла.
    # Основной ключ — всё же имя, а не id: stats_collector обнуляет id
    # АКТИВНОЙ деревни (stats_collector.py:119-120), причём активной каждый
    # раз оказывается другая, поэтому ключ по id «прыгал» бы между запусками
    # и алерт дублировался. Неуникальное/пустое имя дополняем id или индексом.
    villages = stats.get("villages", []) or []
    _name_counts = {}
    for v in villages:
        _name_counts[v.get("name") or ""] = _name_counts.get(v.get("name") or "", 0) + 1

    for idx, v in enumerate(villages):
        raw_name = v.get("name") or ""
        vn = raw_name or "деревня"
        if raw_name and _name_counts.get(raw_name) == 1:
            vkey = raw_name
        elif v.get("id"):
            # префикс id, чтобы «Имя#17» (id) не совпало с «Имя#17» (индекс)
            vkey = f"{raw_name}#id{v['id']}"
        else:
            vkey = f"{vn}#{idx}"
        r = v.get("resources") or {}
        prod = r.get("production") or {}
        storage = r.get("storage") or {}
        cap = r.get("capacity") or {}

        cp = prod.get("crop")
        once(f"crop_{vkey}", cp is not None and cp < 0,
             lambda vn=vn, cp=cp: notifier.crop_starving(vn, cp))

        for rk, ru in (("wood", "дерево"), ("clay", "глина"), ("iron", "железо")):
            cur, mx = storage.get(rk), cap.get(rk)
            full = bool(mx) and cur is not None and cur >= mx
            once(f"full_{vkey}_{rk}", full,
                 lambda vn=vn, ru=ru: notifier.storage_full(vn, ru))

    return fired
