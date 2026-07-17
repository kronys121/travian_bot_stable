import heapq
import itertools
import logging
import random
import time


class Job:
    __slots__ = ("name", "fn", "interval", "priority", "enabled_check", "next_run")

    def __init__(self, name, fn, interval, priority=5, enabled_check=None):
        self.name = name
        self.fn = fn
        self.interval = interval          # секунд между запусками
        self.priority = priority          # меньше = важнее
        self.enabled_check = enabled_check  # callable -> bool (живая проверка из настроек)
        self.next_run = time.time()


class Scheduler:
    """
    Центральный планировщик задач бота.

    Гарантии:
      - В один момент времени выполняется РОВНО ОДНА задача =>
        задачи не перебивают друг друга и не дерутся за page.
      - Задача должна быть короткой: сделала шаг — вернула управление.
        Длинные паузы (интервалы, ночной режим) — забота планировщика.
      - run_now(name) — срочный запуск (например, эвазия при атаке):
        задача выполнится сразу после завершения текущей.
    """

    def __init__(self, logger=None):
        self.log = logger or logging.getLogger(__name__)
        self.jobs: dict[str, Job] = {}
        self._urgent: list = []            # heap: (priority, seq, name)
        self._seq = itertools.count()
        self._stopped = False

    def add(self, name, fn, interval_sec, priority=5, enabled_check=None, initial_delay=0):
        job = Job(name, fn, interval_sec, priority, enabled_check)
        job.next_run = time.time() + initial_delay
        self.jobs[name] = job

    def run_now(self, name, priority=0):
        """Поставить задачу в срочную очередь (потокобезопасно для CPython)."""
        if name in self.jobs:
            heapq.heappush(self._urgent, (priority, next(self._seq), name))

    def set_next_run(self, name: str, in_seconds: float):
        """
        Явно установить время следующего запуска задачи через `in_seconds` секунд.
        Используется SmartBuilder: когда очередь занята, бот точно знает
        сколько ждать — передаёт это время планировщику вместо фиксированного
        интервала, чтобы задача build запустилась ровно когда постройка освободится.
        """
        if name in self.jobs:
            self.jobs[name].next_run = time.time() + max(10, float(in_seconds))

    def stop(self):
        self._stopped = True

    def _pick_next(self):
        """Срочные задачи — первыми; иначе ближайшая по времени (при равенстве — по приоритету)."""
        while self._urgent:
            _, _, name = heapq.heappop(self._urgent)
            job = self.jobs.get(name)
            if job:
                return job, True
        ready = [j for j in self.jobs.values() if j.next_run <= time.time()]
        if not ready:
            return None, False
        ready.sort(key=lambda j: (j.priority, j.next_run))
        return ready[0], False

    def _run_job(self, job: Job, urgent: bool):
        if job.enabled_check and not job.enabled_check():
            self.log.debug(f"⏭️ [{job.name}] выключено в настройках — пропуск.")
            job.next_run = time.time() + max(30, job.interval / 4)
            return
        label = "⚡срочно" if urgent else "▶️"
        self.log.info(f"{label} Задача [{job.name}] стартует.")
        started = time.time()
        # Запоминаем next_run ДО запуска — если задача вызвала set_next_run
        # (например SmartBuilder передал точный таймер постройки), не перезатираем.
        next_run_before = job.next_run
        try:
            job.fn()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            self.log.error(f"❌ Задача [{job.name}] упала: {e}")
        took = time.time() - started
        if job.next_run != next_run_before:
            # set_next_run уже установил нужное время — не трогаем.
            secs_left = max(0, job.next_run - time.time())
            when = f"через {int(secs_left//60)}м {int(secs_left%60)}с (по таймеру)"
        else:
            # Стандартный интервал + джиттер ±10%
            jitter = job.interval * random.uniform(-0.1, 0.1)
            job.next_run = time.time() + max(15, job.interval + jitter)
            if job.interval >= 86400 * 30:
                when = "по требованию (run_now)"
            else:
                when = f"через ~{int(job.interval / 60)} мин"
        self.log.info(f"⏹️ [{job.name}] завершена за {int(took)}с. Следующий запуск: {when}.")

    def run_forever(self, idle_hook=None):
        """
        Главный цикл.
        idle_hook() — вызывается, когда нет готовых задач (например,
        проверка ночного режима или heartbeat статуса). Должен быть быстрым.
        """
        while not self._stopped:
            job, urgent = self._pick_next()
            if job is None:
                if idle_hook:
                    try:
                        idle_hook()
                    except Exception as e:
                        self.log.debug(f"idle_hook: {e}")
                # спим до ближайшей задачи, но не дольше 20с (чтобы ловить срочные)
                upcoming = min((j.next_run for j in self.jobs.values()), default=time.time() + 20)
                time.sleep(min(max(upcoming - time.time(), 1), 20))
                continue
            self._run_job(job, urgent)
            # человеческая микропауза между задачами
            time.sleep(random.uniform(2.0, 5.0))
