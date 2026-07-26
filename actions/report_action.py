"""
Сбор боевых отчётов: читает /report, открывает НОВЫЕ отчёты о набегах,
достаёт добычу/потери/тип войск и складывает в FarmStats.

Идемпотентность: отчёты в Travian имеют возрастающие id. Храним id последнего
обработанного (last_report_id) и берём только те, у кого id больше. На первом
запуске делаем ограниченный бэкофилл (max_reports).

Экземпляр FarmStats — ОБЩИЙ с FarmManager (передаётся из runner), чтобы данные
о набегах и о добыче писались в один файл без гонок (планировщик однопоточный).
"""
import logging

from utils.base_action import BaseAction
from actions.report_parser import (
    parse_report_list, parse_report_detail, parse_village_names,
)


class ReportCollector(BaseAction):
    LOCATORS = {
        'reports_url': 'report',
    }

    # Сколько раз пробуем перечитать отчёт, который не разобрался, прежде
    # чем пропустить его окончательно. Без этого один битый отчёт держал бы
    # водяной знак на месте вечно.
    MAX_DETAIL_RETRIES = 3

    def __init__(self, page, config, farm_stats, villages_fn=None):
        super().__init__(page, config)
        self.farm_stats = farm_stats
        # villages_fn: callable без аргументов -> [{'id':.., 'name':..}].
        # Нужен, чтобы отсеять оборонительные отчёты (набег НА нас).
        self.villages_fn = villages_fn
        self._failed: dict[int, int] = {}
        # id отчётов, уже учтённых в статистике, но ещё НЕ покрытых водяным
        # знаком: если отчёт перед ними не разобрался, знак стоит на месте и
        # они попадут в выборку ещё раз — без этой памяти их добыча
        # засчитывалась бы по второму разу.
        self._recorded: set[int] = set()

    # --- отсев чужих (оборонительных) отчётов -------------------------

    def _our_village_names(self, our_villages=None) -> set:
        """Имена наших деревень в нижнем регистре.
        Пустое множество = список неизвестен, фильтр выключен."""
        src = our_villages
        if src is None and self.villages_fn:
            try:
                src = self.villages_fn()
            except Exception as e:
                logging.debug(f"report: villages_fn error: {e}")
                src = None
        names = set()
        for v in (src or []):
            nm = v.get('name') if isinstance(v, dict) else v
            if nm:
                names.add(str(nm).strip().casefold())
        return names

    @staticmethod
    def _is_ours(attacker, ours: set) -> bool:
        """True, если набег отправляли МЫ. Если список деревень неизвестен
        или нападающего не удалось прочитать — считаем своим (ведём себя
        как раньше), иначе один неудачный парсинг обнулил бы всю статистику."""
        if not ours or not attacker:
            return True
        return str(attacker).strip().casefold() in ours

    def collect(self, max_reports: int = 40, max_pages: int = 3,
                our_villages=None) -> int:
        """Обрабатывает новые отчёты о набегах. Возвращает число учтённых."""
        last_id = int(self.farm_stats.data.get('last_report_id') or 0)
        ours = self._our_village_names(our_villages)
        new_rows: list[dict] = []
        seen: set = set()  # отчёт может съехать между страницами за 1-2с паузы

        for page_num in range(1, max_pages + 1):
            url = f"{self.config.base_url}/{self.LOCATORS['reports_url']}"
            if page_num > 1:
                url += f"?page={page_num}"
            self.safe_goto(url)
            self.human_sleep(1.0, 2.0)

            html = self.page.content()
            if not ours:
                # Сайдбар с деревнями есть и на /report — берём список
                # оттуда, лишней навигации не нужно.
                ours = {n.strip().casefold() for n in parse_village_names(html)}
            rows = parse_report_list(html)
            raids = [r for r in rows if r['is_raid'] and r['id']]
            if not raids:
                break
            fresh = [r for r in raids if int(r['id']) > last_id]
            for r in fresh:
                if r['id'] in seen:
                    continue
                seen.add(r['id'])
                new_rows.append(r)
            # если на странице попались уже обработанные — дальше только старее, стоп
            if len(fresh) < len(raids):
                break

        if not new_rows:
            logging.info("📊 Новых отчётов о набегах нет.")
            return 0

        # Страховка: если ни один отчёт не совпал с нашими деревнями, значит
        # имена читаются не так, как ждём (другая локаль/разметка). Молча
        # выкинуть ВСЮ статистику хуже, чем посчитать лишний отчёт.
        if ours and not any(self._is_ours(r.get('attacker'), ours) for r in new_rows):
            logging.warning(
                "📊 Ни один отчёт не совпал с нашими деревнями — "
                "фильтр чужих отчётов отключён на этот заход."
            )
            ours = set()

        # От старых к новым и режем ХВОСТ, а не голову: раньше стояло
        # [-max_reports:], то есть самые старые необработанные отчёты
        # выбрасывались, а водяной знак прыгал на самый новый id — и они
        # не читались уже никогда.
        new_rows.sort(key=lambda r: int(r['id']))
        new_rows = new_rows[:max_reports]

        # Водяной знак двигаем только по ПОДРЯД идущим разобранным отчётам:
        # упавший отчёт должен перечитаться в следующий заход.
        ok_max = last_id
        blocked = False
        count = 0
        skipped_foreign = 0
        for row in new_rows:
            rid = int(row['id'])
            done = False
            try:
                if rid in self._recorded:
                    done = True  # уже учтён в прошлый заход, второй раз не считаем
                elif not self._is_ours(row.get('attacker'), ours):
                    skipped_foreign += 1
                    done = True
                else:
                    detail = self._open_and_parse(row)
                    if detail is None:
                        done = True  # нет ссылки на отчёт — читать нечего
                    elif not self._is_ours(detail.get('attacker') or row.get('attacker'), ours):
                        skipped_foreign += 1
                        done = True
                    else:
                        self.farm_stats.record_report(detail)
                        self._recorded.add(rid)
                        count += 1
                        done = True
                self._failed.pop(rid, None)
            except Exception as e:
                tries = self._failed.get(rid, 0) + 1
                self._failed[rid] = tries
                logging.warning(f"⚠️ Отчёт {rid}: не удалось разобрать ({e}), попытка {tries}.")
                done = tries >= self.MAX_DETAIL_RETRIES
            if not done:
                blocked = True
            elif not blocked:
                ok_max = max(ok_max, rid)

        if ok_max > last_id:
            self.farm_stats.set_last_report_id(ok_max)
        # ниже водяного знака помнить нечего — эти отчёты больше не выберутся
        self._failed = {k: v for k, v in self._failed.items() if k > ok_max}
        self._recorded = {i for i in self._recorded if i > ok_max}
        self.farm_stats.save()
        logging.info(
            f"📊 Отчёты: учтено {count}, добыча и потери записаны."
            + (f" Чужих (набеги на нас) пропущено: {skipped_foreign}." if skipped_foreign else "")
        )
        return count

    def _open_and_parse(self, row: dict) -> dict | None:
        """Открывает отдельный отчёт и разбирает его. Координаты/лут при
        отсутствии в детали берём из строки списка (фолбэк)."""
        href = row.get('detail_href')
        if not href:
            return None
        url = f"{self.config.base_url}/{self.LOCATORS['reports_url']}{href}"
        self.safe_goto(url)
        self.human_sleep(0.8, 1.6)

        detail = parse_report_detail(self.page.content())
        if detail.get('x') is None:
            detail['x'], detail['y'] = row.get('x'), row.get('y')
        if not detail.get('looted_total') and row.get('looted'):
            detail['looted_total'] = row['looted']
        if not detail.get('attacker'):
            detail['attacker'] = row.get('attacker')
        return detail
