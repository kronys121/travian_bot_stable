"""
Логика умных уведомлений: сравнивает свежую статистику с прошлым состоянием
и дёргает нужный метод нотифаера ТОЛЬКО на переходе «стало плохо» — чтобы не
слать одно и то же каждые 5 минут, пока условие держится.

Чистая функция (без сети/браузера) — легко тестируется.
"""


def check_alerts(stats: dict, notifier, state: dict) -> list:
    """Проверяет условия и шлёт уведомления через notifier.

    state — словарь-память между вызовами (ключ условия -> bool).
    Возвращает список сработавших ключей (удобно для тестов/логов).
    """
    fired = []
    if not stats:
        return fired

    def once(key, cond, fire):
        if cond and not state.get(key):
            fired.append(key)
            try:
                fire()
            except Exception:
                pass
        state[key] = bool(cond)

    # Герой погиб
    hero = stats.get("hero") or {}
    hp = hero.get("health")
    hstatus = str(hero.get("status") or "").lower()
    dead = (hp == 0) or ("мёрт" in hstatus) or ("мертв" in hstatus) or ("dead" in hstatus)
    once("hero_dead", dead, lambda: notifier.hero_died())

    # По деревням: голод по зерну и переполнение складов (дерево/глина/железо)
    for v in stats.get("villages", []):
        vn = v.get("name") or "деревня"
        r = v.get("resources") or {}
        prod = r.get("production") or {}
        storage = r.get("storage") or {}
        cap = r.get("capacity") or {}

        cp = prod.get("crop")
        once(f"crop_{vn}", cp is not None and cp < 0,
             lambda vn=vn, cp=cp: notifier.crop_starving(vn, cp))

        for rk, ru in (("wood", "дерево"), ("clay", "глина"), ("iron", "железо")):
            cur, mx = storage.get(rk), cap.get(rk)
            full = bool(mx) and cur is not None and cur >= mx
            once(f"full_{vn}_{rk}", full,
                 lambda vn=vn, ru=ru: notifier.storage_full(vn, ru))

    return fired
