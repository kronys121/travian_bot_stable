"""
Учёт статистики фарма по каждому аккаунту.

Что считаем сейчас (надёжно, без чтения отчётов):
  - сколько набегов отправлено (всего / по типам войск / по дням);
  - сколько юнитов ушло в набеги;
  - по каким оазисам и сколько раз фармили (уникальные цели).

Хранится в data/<acc>/farm_stats.json. Пополняется из FarmManager после
каждого успешного набега, читается дашбордом (app.py).

Добыча (лут) и потери войск берутся из боевых отчётов — их парсинг
добавляется отдельно (Фаза 2). Поля loot/lost уже заведены в структуре,
чтобы профит по типам войск считался, как только появится чтение отчётов.
"""
import json
import logging
import os
from datetime import datetime

from utils.paths import account_file


def _now() -> str:
    return datetime.now().isoformat()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class FarmStats:
    """Накопитель статистики фарма. Живёт весь процесс, копит в памяти,
    сохраняется на диск в конце каждого цикла фарма."""

    def __init__(self, account_name: str):
        self.name = account_name
        self.path = account_file(account_name, 'farm_stats')
        self.data = self._load()

    def _default(self) -> dict:
        return {
            "totals": {"raids": 0, "units_sent": 0, "loot": 0, "lost": 0, "reports": 0,
                       "loot_res": {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}},
            # "1": {"raids": int, "units": int, "loot": int, "lost": int}
            "by_troop": {},
            # "x|y": {"raids": int, "units": int, "loot": int, "lost": int, "last": iso}
            "oases": {},
            # "YYYY-MM-DD": {"raids": int, "units": int}
            "daily": {},
            # id последнего обработанного отчёта (отчёты имеют возрастающие id)
            "last_report_id": 0,
            "started_at": _now(),
            "updated_at": None,
        }

    def _load(self) -> dict:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    base = self._default()
                    # мягкая миграция: дополняем недостающие ключи
                    for k, v in base.items():
                        d.setdefault(k, v)
                    return d
        except Exception:
            logging.debug("farm_stats load error", exc_info=True)
        return self._default()

    def record_raid(self, target_x, target_y, troop_index: int,
                    count: int, distance: float = 0.0):
        """Фиксирует один успешно отправленный набег."""
        d = self.data
        ti = str(int(troop_index))
        count = int(count)
        now = _now()

        d["totals"]["raids"] += 1
        d["totals"]["units_sent"] += count

        bt = d["by_troop"].setdefault(ti, {"raids": 0, "units": 0, "loot": 0, "lost": 0})
        bt["raids"] += 1
        bt["units"] += count

        key = f"{target_x}|{target_y}"
        oa = d["oases"].setdefault(key, {"raids": 0, "units": 0, "last": None})
        oa["raids"] += 1
        oa["units"] += count
        oa["last"] = now

        day = d["daily"].setdefault(_today(), {"raids": 0, "units": 0})
        day["raids"] += 1
        day["units"] += count

        d["updated_at"] = now

    def record_report(self, rep: dict):
        """Учитывает разобранный отчёт о набеге: добычу (по ресурсам и суммой)
        и потери войск. Профит по типам войск: лут вешаем на доминирующий тип
        набега, потери — на каждый тип по строке погибших."""
        d = self.data
        looted = int(rep.get("looted_total") or 0)
        loot_res = rep.get("loot") or {}
        dead = rep.get("dead") or {}
        total_dead = sum(int(v) for v in dead.values())

        tot = d.setdefault("totals", {})
        tot["loot"] = tot.get("loot", 0) + looted
        tot["lost"] = tot.get("lost", 0) + total_dead
        tot["reports"] = tot.get("reports", 0) + 1
        lr = tot.setdefault("loot_res", {"lumber": 0, "clay": 0, "iron": 0, "crop": 0})
        for k in ("lumber", "clay", "iron", "crop"):
            lr[k] = lr.get(k, 0) + int(loot_res.get(k, 0))

        ti = rep.get("troop_index")
        if ti is not None:
            bt = d["by_troop"].setdefault(str(ti), {"raids": 0, "units": 0, "loot": 0, "lost": 0})
            bt["loot"] = bt.get("loot", 0) + looted
        for k, v in dead.items():
            bt = d["by_troop"].setdefault(str(k), {"raids": 0, "units": 0, "loot": 0, "lost": 0})
            bt["lost"] = bt.get("lost", 0) + int(v)

        if rep.get("x") is not None:
            key = f"{rep['x']}|{rep['y']}"
            oa = d["oases"].setdefault(key, {"raids": 0, "units": 0, "last": None})
            oa["loot"] = oa.get("loot", 0) + looted
            oa["lost"] = oa.get("lost", 0) + total_dead

        # дневная добыча/потери (для графиков во времени)
        day = d["daily"].setdefault(_today(), {"raids": 0, "units": 0})
        day["loot"] = day.get("loot", 0) + looted
        day["lost"] = day.get("lost", 0) + total_dead

        d["updated_at"] = _now()

    def set_last_report_id(self, report_id):
        try:
            self.data["last_report_id"] = int(report_id)
        except (TypeError, ValueError):
            pass

    def save(self):
        """Атомарная запись на диск (tmp + replace)."""
        try:
            tmp = str(self.path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(self.path))
        except Exception as e:
            logging.warning(f"⚠️ Не удалось сохранить farm_stats: {e}")
