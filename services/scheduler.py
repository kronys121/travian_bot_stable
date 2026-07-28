import heapq
import itertools
import logging
import random
import threading
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
      - если умер браузер — планировщик НЕ крутится вечно, а выбрасывает
        исключение наружу: вызывающий закроет браузер и завершит процесс.
      - если задачи просто падают подряд (сервер недоступен, профилактика) —
        планировщик уводит все задачи на паузу и продолжает работать.
        Выходить из процесса тут нельзя: перезапускать бота в проекте некому.
    """

    # Сколько задач подряд может упасть, прежде чем считаем, что сервер лежит.
    MAX_CONSECUTIVE_FAILURES = 5

    # На сколько разводим все задачи после серии падений.
    BACKOFF_AFTER_FAILURES = 10 * 60

    # Фразы playwright, означающие «браузер/страница/драйвер мертвы».
    # Именно фразы, а не отдельные слова: см. комментарий в _looks_like_dead_browser.
    _DEAD_BROWSER_PHRASES = (
        'has been closed',            # Target page, context or browser has been closed
        'target closed',
        'browser closed',
        'page closed',
        'context closed',
        'connection closed',          # Connection closed while reading from the driver
        'browser has disconnected',
    )

    def __init__(self, logger=None, on_fatal=None):
        self.log = logger or logging.getLogger(__name__)
        self.jobs: dict[str, Job] = {}
        self._urgent: list = []            # heap: (priority, seq, name)
        self._urgent_names: set[str] = set()
        # run_now() зовётся и из потока мониторинга атак, а теперь у очереди
        # два связанных состояния (heap + set) — менять их надо атомарно.
        self._urgent_lock = threading.Lock()
        self._seq = itertools.count()
        self._stopped = False
        # on_fatal(job_name, exc, reason) — вызывается перед тем, как бросить
        # исключение наружу. Статус-файл и уведомления — забота вызывающего
        # (runner), планировщик про них ничего не знает.
        self.on_fatal = on_fatal
        self._consecutive_failures = 0

    def add(self, name, fn, interval_sec, priority=5, enabled_check=None, initial_delay=0):
        job = Job(name, fn, interval_sec, priority, enabled_check)
        job.next_run = time.time() + initial_delay
        self.jobs[name] = job

    def run_now(self, name, priority=0):
        """Поставить задачу в срочную очередь.

        ФИКС: раньше каждый вызов клал НОВЫЙ элемент в heap. idle_hook
        вызывает run_now('evade') пока держится флаг атаки, и очередь
        набивалась десятками копий одной и той же эвакуации — после
        первого выполнения остальные крутились вхолостую и блокировали
        обычные задачи.
        """
        if name not in self.jobs:
            return
        with self._urgent_lock:
            if name in self._urgent_names:
                return
            self._urgent_names.add(name)
            heapq.heappush(self._urgent, (priority, next(self._seq), name))

    def set_next_run(self, name: str, in_seconds: float):
        """
        Явно установить время следующего запуска задачи через `in_seconds` секунд.
        Используется SmartBuilder: когда очередь занята, бот точно знает
        сколько ждать — передаёт это время планировщику вместо фиксированного
        интервала, чтобы задача build запустилась ровно когда постройка освободится.
        """
        job = self.jobs.get(name)
        if job is None:
            return
        try:
            delay = float(in_seconds)
        except (TypeError, ValueError):
            self.log.warning(f"set_next_run({name!r}): нечисловое значение {in_seconds!r} — игнорирую.")
            return
        job.next_run = time.time() + max(10.0, delay)

    def stop(self):
        self._stopped = True

    @staticmethod
    def _looks_like_dead_browser(e: Exception) -> bool:
        """Похоже, что браузер/страница закрыты — дальше крутиться бессмысленно.

        Тип исключения определяем ПО ИМЕНИ: планировщик не должен тянуть
        playwright в импорты (он же используется в тестах без браузера).
        """
        type_name = type(e).__name__
        if 'TargetClosedError' in type_name or 'BrowserClosed' in type_name:
            return True
        text = str(e).lower()
        # ФИКС: искать просто 'closed' рядом со словом 'page' нельзя — playwright
        # подставляет в начало сообщения имя метода ("Page.goto: ..."), поэтому
        # обычная сетевая ошибка net::ERR_CONNECTION_CLOSED принималась за
        # мёртвый браузер и убивала процесс. Сверяем целые фразы playwright.
        return any(p in text for p in Scheduler._DEAD_BROWSER_PHRASES)

    def _fatal(self, job_name: str, e: Exception, reason: str):
        """Сообщить вызывающему о фатальной ситуации (статус/уведомление — его дело)."""
        self.log.critical(f"💥 Планировщик остановлен: {reason} (задача [{job_name}]): {e}")
        if self.on_fatal:
            try:
                self.on_fatal(job_name, e, reason)
            except Exception as ce:
                self.log.error(f"❌ on_fatal упал: {ce}")

    def _pause_all(self, seconds: float):
        """Разводит все задачи на паузу.

        ФИКС: раньше сдвигался только next_run, а срочная очередь оставалась
        полной — и сразу после объявленной «паузы 10 минут» планировщик продолжал
        крутить накопившиеся срочные задачи по лежащему серверу.
        """
        pause_until = time.time() + seconds
        for j in self.jobs.values():
            j.next_run = max(j.next_run, pause_until)
        with self._urgent_lock:
            self._urgent.clear()
            self._urgent_names.clear()

    def _pick_next(self):
        """Срочные задачи — первыми; иначе ближайшая по времени (при равенстве — по приоритету)."""
        while True:
            with self._urgent_lock:
                if not self._urgent:
                    break
                _, _, name = heapq.heappop(self._urgent)
                self._urgent_names.discard(name)
            job = self.jobs.get(name)
            if job:
                return job, True
        now = time.time()
        ready = [j for j in self.jobs.values() if j.next_run <= now]
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
            self._consecutive_failures = 0
        except KeyboardInterrupt:
            raise
        except Exception as e:
            # ФИКС: раньше любое исключение просто гасилось, задача
            # переставлялась на now+interval, а статус оставался «жив». Когда
            # умирал Chromium, бот вечно крутил падающие задачи и рапортовал,
            # что всё хорошо.
            self._consecutive_failures += 1
            self.log.error(
                f"❌ Задача [{job.name}] упала "
                f"({self._consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES}): {e}"
            )
            if self._looks_like_dead_browser(e):
                # Единственный по-настоящему невосстановимый случай: страницы
                # больше нет, продолжать в этом процессе бессмысленно.
                self._fatal(job.name, e, "браузер закрыт")
                raise
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                # А вот тут раньше стоял raise — и бот выходил из процесса.
                # Перезапускать его в проекте некому (app.start_account зовётся
                # только руками из GUI), поэтому обычная недоступность сервера
                # или профилактика Travian гасили аккаунт до прихода человека.
                # Правильнее переждать: разводим все задачи на паузу и живём дальше.
                self._fatal(job.name, e,
                            f"{self._consecutive_failures} задач подряд упали — пауза "
                            f"{self.BACKOFF_AFTER_FAILURES // 60} мин")
                self._pause_all(self.BACKOFF_AFTER_FAILURES)
                self._consecutive_failures = 0
                return
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
