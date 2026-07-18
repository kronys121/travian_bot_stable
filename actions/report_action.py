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
from actions.report_parser import parse_report_list, parse_report_detail


class ReportCollector(BaseAction):
    LOCATORS = {
        'reports_url': 'report',
    }

    def __init__(self, page, config, farm_stats):
        super().__init__(page, config)
        self.farm_stats = farm_stats

    def collect(self, max_reports: int = 40, max_pages: int = 3) -> int:
        """Обрабатывает новые отчёты о набегах. Возвращает число учтённых."""
        last_id = int(self.farm_stats.data.get('last_report_id') or 0)
        new_rows: list[dict] = []

        for page_num in range(1, max_pages + 1):
            url = f"{self.config.base_url}/{self.LOCATORS['reports_url']}"
            if page_num > 1:
                url += f"?page={page_num}"
            self.safe_goto(url)
            self.human_sleep(1.0, 2.0)

            rows = parse_report_list(self.page.content())
            raids = [r for r in rows if r['is_raid'] and r['id']]
            if not raids:
                break
            fresh = [r for r in raids if int(r['id']) > last_id]
            new_rows.extend(fresh)
            # если на странице попались уже обработанные — дальше только старее, стоп
            if len(fresh) < len(raids):
                break

        if not new_rows:
            logging.info("📊 Новых отчётов о набегах нет.")
            return 0

        # от старых к новым, ограничиваем объём за один заход
        new_rows.sort(key=lambda r: int(r['id']))
        new_rows = new_rows[-max_reports:]

        processed_max = last_id
        count = 0
        for row in new_rows:
            rid = int(row['id'])
            try:
                detail = self._open_and_parse(row)
                if detail:
                    self.farm_stats.record_report(detail)
                    count += 1
            except Exception as e:
                logging.warning(f"⚠️ Отчёт {rid}: не удалось разобрать ({e}).")
            processed_max = max(processed_max, rid)

        self.farm_stats.set_last_report_id(processed_max)
        self.farm_stats.save()
        logging.info(f"📊 Отчёты: учтено {count}, добыча и потери записаны.")
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
        return detail
