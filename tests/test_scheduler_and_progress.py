"""
Тесты планировщика и прогресса стройки — двух мест, где «починка» легко
превращается в новую поломку.

Планировщик: падение задачи не должно убивать процесс (перезапускать бота
в проекте некому), но мёртвый браузер должен пробрасываться наружу.

Прогресс стройки: номер шага бессмыслен без длины плана — на укороченном
шаблоне сохранённый шаг совпадал с маркером «план пройден», и деревня
переставала строиться навсегда.

Запуск:  python -m unittest tests.test_scheduler_and_progress -v
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.scheduler import Scheduler
from utils import paths as paths_mod


class _Boom(Exception):
    pass


class TestSchedulerFailureHandling(unittest.TestCase):

    def setUp(self):
        self.sched = Scheduler()
        self.fatal = []
        self.sched.on_fatal = lambda job, e, reason: self.fatal.append((job, reason))

    def _add_failing(self, name="job"):
        def boom():
            raise _Boom("сервер недоступен")
        self.sched.add(name, boom, interval_sec=60)
        return self.sched.jobs[name]

    def test_single_failure_is_swallowed_and_rescheduled(self):
        job = self._add_failing()
        self.sched._run_job(job, urgent=False)
        self.assertGreater(job.next_run, 0)
        self.assertEqual(self.fatal, [])

    def test_burst_of_failures_backs_off_instead_of_killing_the_process(self):
        # Регресс: тут стоял raise, и профилактика Travian гасила аккаунт
        # до тех пор, пока человек не нажмёт «Старт» в дашборде.
        job = self._add_failing()
        import time as _t
        before = _t.time()
        for _ in range(Scheduler.MAX_CONSECUTIVE_FAILURES):
            self.sched._run_job(job, urgent=False)  # не должно бросить
        self.assertEqual(len(self.fatal), 1)
        self.assertGreaterEqual(job.next_run, before + Scheduler.BACKOFF_AFTER_FAILURES - 5)
        # счётчик обнулён — следующая серия снова получит свои 5 попыток
        self.assertEqual(self.sched._consecutive_failures, 0)

    def test_dead_browser_propagates(self):
        def dead():
            raise RuntimeError("Page.goto: Target page, context or browser has been closed")
        self.sched.add("dead", dead, interval_sec=60)
        with self.assertRaises(RuntimeError):
            self.sched._run_job(self.sched.jobs["dead"], urgent=False)
        self.assertEqual(len(self.fatal), 1)

    def test_ordinary_network_error_is_not_a_dead_browser(self):
        # 'Page.goto: net::ERR_CONNECTION_CLOSED' содержит и 'page', и 'closed' —
        # наивная эвристика по словам принимала это за мёртвый браузер.
        e = RuntimeError("Page.goto: net::ERR_CONNECTION_CLOSED at https://ts30.travian.com/")
        self.assertFalse(Scheduler._looks_like_dead_browser(e))

    def test_successful_run_resets_failure_counter(self):
        job = self._add_failing("flaky")
        self.sched._run_job(job, urgent=False)
        self.assertEqual(self.sched._consecutive_failures, 1)
        job.fn = lambda: None
        self.sched._run_job(job, urgent=False)
        self.assertEqual(self.sched._consecutive_failures, 0)

    def test_disabled_job_is_not_counted_as_failure(self):
        self.sched.add("off", lambda: None, interval_sec=60, enabled_check=lambda: False)
        self.sched._run_job(self.sched.jobs["off"], urgent=False)
        self.assertEqual(self.sched._consecutive_failures, 0)


class TestBuildProgress(unittest.TestCase):
    """SmartBuilder.save_step / get_saved_progress без браузера и конфига."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._saved = (paths_mod.PROJECT_ROOT, paths_mod.DATA_DIR)
        paths_mod.PROJECT_ROOT = self.dir
        paths_mod.DATA_DIR = self.dir / "data"
        from services.smart_builder import SmartBuilder
        self.sb = SmartBuilder.__new__(SmartBuilder)   # без __init__: нужен только файл
        self.sb._progress_path = paths_mod.account_file("Acc", "build_progress")

    def tearDown(self):
        paths_mod.PROJECT_ROOT, paths_mod.DATA_DIR = self._saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_roundtrip_with_plan_length(self):
        self.sb.save_step("v1", 7, plan_len=30)
        self.assertEqual(self.sb.get_saved_progress("v1"), (7, 30))
        self.assertEqual(self.sb.get_saved_step("v1"), 7)

    def test_legacy_int_entry_still_readable(self):
        from utils.jsonio import write_json
        write_json(self.sb._progress_path, {"v1": 5})
        self.assertEqual(self.sb.get_saved_progress("v1"), (5, None))

    def test_unknown_village_starts_at_one(self):
        self.assertEqual(self.sb.get_saved_progress("nope"), (1, None))

    def test_garbage_entry_starts_at_one(self):
        from utils.jsonio import write_json
        write_json(self.sb._progress_path, {"v1": {"step": "не число"}})
        self.assertEqual(self.sb.get_saved_progress("v1"), (1, None))

    def test_plan_length_change_is_detectable(self):
        # Ради этого длина и хранится: шаг 12 старого 30-шагового плана
        # на новом 11-шаговом плане выглядит как маркер «пройден» (len+1).
        self.sb.save_step("v1", 12, plan_len=30)
        step, saved_len = self.sb.get_saved_progress("v1")
        new_plan_len = 11
        self.assertNotEqual(saved_len, new_plan_len)
        self.assertEqual(step, 12)

    def test_reset_progress_for_one_village(self):
        self.sb.save_step("v1", 4, plan_len=10)
        self.sb.save_step("v2", 9, plan_len=10)
        self.sb.reset_progress("v1")
        self.assertEqual(self.sb.get_saved_step("v1"), 1)
        self.assertEqual(self.sb.get_saved_step("v2"), 9)


class TestNightWindowEdgeCases(unittest.TestCase):

    def test_equal_start_and_end_is_not_permanent_night(self):
        # Регресс: start == end проваливался в ветку «через полночь»,
        # где условие `hour >= start or hour < end` истинно всегда,
        # и бот засыпал навсегда.
        from datetime import datetime
        from utils.night_time import is_night
        for hour in (0, 5, 12, 23):
            self.assertFalse(is_night((3, 3), datetime(2026, 1, 1, hour)), hour)


if __name__ == "__main__":
    unittest.main()
