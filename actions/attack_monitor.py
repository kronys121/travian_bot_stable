import time
import logging
import re
from utils.base_action import BaseAction


class AttackMonitor(BaseAction):
    """
    Мониторинг входящих атак.

    Реальная HTML-структура Travian:
      td.typ .att1   — красные мечи (атака)
      td.mov .a1     — количество атакающих
      td.dur_r .timer — время до прибытия
    """

    def has_incoming_attack(self) -> bool:
        """Быстрая проверка: есть ли класс att1 в td.typ."""
        try:
            return self.page.locator('td.typ .att1').count() > 0
        except Exception as e:
            logging.debug(f"has_incoming_attack error: {e}")
            return False

    def parse_attacks(self) -> list[dict] | None:
        """
        Парсит все входящие атаки.
        Возвращает:
            [{
                'count':   3,
                'arrival': '00:14:32',
                'from_x':  42,
                'from_y':  18,
            }, ...]
        None — атака на странице есть, но НИ ОДНА строка не разобралась
        (раньше в этом случае возвращался пустой список и вызывающий
        считал, что всё спокойно).
        """
        attacks = []
        try:
            rows = self.page.locator('tr:has(.typ .att1)').all()
        except Exception as e:
            logging.error(f'❌ Ошибка поиска строк атак: {e}')
            rows = []

        for row in rows:
            # try/except ВНУТРИ цикла: одна кривая строка не должна
            # обнулять уже разобранные атаки.
            try:
                # Количество: td.mov .a1
                count = 1
                a1 = row.locator('.mov .a1').first
                if a1.count() > 0:
                    m = re.search(r'\d+', a1.text_content() or '')
                    if m:
                        count = int(m.group())

                # Время: td.dur_r .timer
                arrival = '?'
                timer = row.locator('.dur_r .timer').first
                if timer.count() > 0:
                    arrival = (timer.text_content() or '?').strip()

                # Координаты
                row_text = row.text_content() or ''
                coords = re.search(r'\((\-?\d+)\|(\-?\d+)\)', row_text)
                from_x = int(coords.group(1)) if coords else 0
                from_y = int(coords.group(2)) if coords else 0

                attacks.append({
                    'count':   count,
                    'arrival': arrival,
                    'from_x':  from_x,
                    'from_y':  from_y,
                })
            except Exception as e:
                logging.error(f'❌ Ошибка парсинга строки атаки: {e}')

        if not attacks and self.has_incoming_attack():
            return None
        return attacks

    def check_incoming(self) -> list[dict]:
        """Основной метод: проверяет атаки, логирует, шлёт Telegram."""
        if not self.has_incoming_attack():
            self._notified.clear()  # угроза ушла — можно снова уведомлять
            return []

        attacks = self.parse_attacks()
        if attacks is None:
            # Иконка атаки есть, разметку не поняли: считаем угрозу реальной,
            # чтобы эвазия всё-таки отработала.
            logging.warning('🚨 Атака есть, но строку разобрать не удалось — считаю угрозу активной.')
            return [{'count': 1, 'arrival': '?', 'from_x': 0, 'from_y': 0, 'unknown': True}]

        total   = sum(a['count'] for a in attacks)
        nearest = attacks[0]['arrival'] if attacks else '?'

        logging.warning(f'🚨 ВХОДЯЩИХ АТАК: {total} | Ближайшая через: {nearest}')

        notifier = getattr(self.config, 'notifier', None)
        if notifier:
            for atk in attacks:
                # Дедуп как в runner.py: без него каждый круг меню слал
                # телеграм-сообщение про одну и ту же атаку.
                key = f"{atk['from_x']}|{atk['from_y']}|{atk['count']}"
                if key in self._notified:
                    continue
                self._notified.add(key)
                try:
                    notifier.attack(
                        coords=(atk['from_x'], atk['from_y']),
                        arrival=atk['arrival'],
                    )
                except Exception as ne:
                    logging.debug(f"notifier.attack error: {ne}")

        return attacks

    def is_night_time(self) -> bool:
        """
        Проверяет ночные часы из config.sleep_hours.
        Формат: (23, 7) — спать с 23:00 до 07:00.
        """
        from utils.night_time import is_night
        return is_night(getattr(self.config, 'sleep_hours', ()))

    # Минимальный интервал между эвакуациями (сек). Защищает от того,
    # чтобы бот эвакуировался бесконечно при волнах атак каждые пару минут,
    # когда войска ещё не вернулись домой и уводить уже нечего.
    EVADE_COOLDOWN_SEC = 5 * 60

    def __init__(self, page, config):
        super().__init__(page, config)
        self._last_evade_ts = 0.0
        # ключи "x|y|count" уже отправленных уведомлений (антиспам)
        self._notified: set[str] = set()

    def can_evade_now(self) -> bool:
        """True, если с прошлой эвакуации прошло больше EVADE_COOLDOWN_SEC."""
        return (time.time() - self._last_evade_ts) >= self.EVADE_COOLDOWN_SEC

    def mark_evaded(self):
        """Отмечает успешную эвакуацию (запуск кулдауна). Публичный метод,
        чтобы вызывающие не трогали приватное поле напрямую."""
        self._last_evade_ts = time.time()

    def maybe_evade(self, farm_manager, attacks: list[dict]) -> bool:
        """Выводит войска в оазис при атаке (если evasion_enabled).
        Возвращает True ТОЛЬКО если эвакуация реально отработала — по
        этому флагу вызывающий решает, пропускать ли обычный фарм."""
        if not attacks:
            return False
        # Живой тумблер из GUI приоритетнее статичного yaml-конфига
        store = getattr(farm_manager, 'settings_store', None)
        if store is not None:
            if not store.feature('evasion_enabled', True):
                return False
        elif not getattr(self.config, 'evasion_enabled', False):
            return False

        # Кулдаун: не эвакуируемся чаще раза в EVADE_COOLDOWN_SEC —
        # иначе при волнах атак бот бесконечно жмёт "увести войска".
        if not self.can_evade_now():
            left = int(self.EVADE_COOLDOWN_SEC - (time.time() - self._last_evade_ts))
            logging.info(f"🏃 Эвазия на кулдауне ещё ~{left}с — пропуск.")
            return False

        logging.info('🏃 Эвазия: эвакуирую все войска...')
        # Настоящая эвакуация: все войска одним рейдом в ближайший оазис,
        # без кулдаунов и лимитов фарма (см. FarmManager.evade_all_troops)
        result = farm_manager.evade_all_troops()
        # Обновляем кулдаун только если реально что-то отправили либо
        # войск не осталось — в обоих случаях повторять сразу бессмысленно.
        if result in ("SUCCESS", "NO_TROOPS"):
            self.mark_evaded()
            return True
        return False
