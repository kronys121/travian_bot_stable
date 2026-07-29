"""
Умный фарм оазисов — надстройка над FarmManager.

Почему подкласс, а не правки в oasis_action.py: там 70 КБ работающего
кода (скан, парсинг клеток, герой, отправка формы), и всё это переиспользуется
как есть. Меняется только ТРИ решения: куда идти, сколько слать и куда
эвакуироваться.

Что делает иначе, чем родитель
-----------------------------------
1. БЕЗОПАСНОСТЬ ПО СИЛЕ, а не по абсолютному порогу.
   Родитель сравнивал защиту животных с max_animal_defense — одним числом
   на любой тип и любое количество юнитов. Здесь считается атака
   конкретной пачки (таблица config/unit_stats.py) и передаётся в
   attack_oasis(max_defense=...) — тот же механизм, что уже использовался
   для героя. Следствие: большая пачка может фармить слабые ЗАНЯТЫЕ
   оазисы, а маленькая не полезет туда, куда раньше полезла бы.
2. ПРИОРИТЕТ ПО ПРИБЫЛЬНОСТИ. Родитель сортировал цели по дистанции;
   здесь — по ожидаемому луту на минуту занятости войск, по истории из
   farm_stats.json. Если истории нет (отчёты выключены) — молча ведёт себя
   как раньше, по дистанции.
3. РАЗМЕР ПАЧКИ ПОД ЦЕЛЬ. troops_per_raid теперь — ПОТОЛОК, а не
   жёсткое число: если оазис отдаёт ~300, а юнит несёт 50 — шлём 6,
   а не 20. Остальные 14 в это время фармят другую цель.
4. СКОРОСТЬ ПО ТИПУ ЮНИТА. Кулдаун цели считался по одной скорости
   на аккаунт, хотя фарм умеет чередовать пехоту и конницу.
5. БЕЗОПАСНАЯ ЭВАКУАЦИЯ. Родитель уводил ВСЮ армию в ближайший
   оазис из списка БЕЗ проверки клетки. Если там успел заспавниться
   крокодил — вся армия гибла именно в момент спасения. Теперь цель
   проверяется живым запросом, кандидатов несколько.

Новые настройки (секция farm)
--------------------------------
  smart_farm         bool  вкл/выкл умного режима (по умолчанию вкл)
  smart_safety_pct   int   запас прочности против животных, % (200)
  smart_weak_animals bool  фармить ли слабые занятые оазисы (вкл)
  smart_min_units    int   нижняя граница пачки (1)
  min_loot_per_raid  int   выбрасывать цели беднее этого (0 = не выбрасывать)
  troops_per_raid    int   теперь ПОТОЛОК пачки, а не точное число
Всё остальное (max_distance, cooldown_minutes, farm_troop_indices, tribe,
max_animal_defense, тумблеры hero_only/hero_with_troops) работает как раньше.
С smart_farm=false класс полностью отдаёт работу родителю — откат мгновенный.
"""
import logging
import random
import time

from actions import farm_intel as FI
from actions.oasis_action import FarmManager
from config import unit_stats as US


class SmartFarmManager(FarmManager):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Подмена цели эвакуации на время одного вызова (см. _refresh_settings).
        self._evade_override = None

    # --- НАСТРОЙКИ -------------------------------------------------

    def _refresh_settings(self):
        """Родитель перечитывает настройки внутри evade_all_troops и затёр бы
        проверенную цель значением из настроек. Возвращаем её на место."""
        super()._refresh_settings()
        if self._evade_override:
            self.settings["evade_target"] = dict(self._evade_override)

    def _int_setting(self, key: str, default: int) -> int:
        try:
            return int(self.settings.get(key, default))
        except (TypeError, ValueError):
            return int(default)

    def _bool_setting(self, key: str, default: bool) -> bool:
        val = self.settings.get(key, default)
        return bool(default) if val is None else bool(val)

    def _smart_on(self) -> bool:
        return self._bool_setting("smart_farm", True)

    def _tribe(self):
        return self.settings.get("tribe")

    def _features(self) -> dict:
        def feat(name, fallback):
            if self.settings_store:
                return bool(self.settings_store.feature(name, False))
            return bool(self.settings.get(name, fallback))
        return {
            "troops": feat("farm_enabled", True),
            "hero_only": feat("hero_only", False),
            "hero_with_troops": feat("hero_with_troops", False),
        }

    def _troop_indices(self) -> list:
        raw = self.settings.get("farm_troop_indices") or []
        if isinstance(raw, (int, float)):
            raw = [int(raw)]
        out = []
        for value in raw:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if idx and idx not in out:
                out.append(idx)
        if not out:
            out = [self._int_setting("troop_type_index", 1)]
        return out

    # --- ЦИКЛ ------------------------------------------------------

    def run_farm_cycle(self, force_rescan: bool = False, force_send: bool = False):
        """Умный цикл. force_send (эвазия) и выключенный smart_farm — к родителю."""
        if force_send or not self._smart_on():
            return super().run_farm_cycle(force_rescan=force_rescan, force_send=force_send)
        try:
            return self._smart_cycle(force_rescan=force_rescan)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            # Ломать фарм из-за ошибки в логике выбора целей нельзя:
            # падаем на проверенный старый путь.
            logging.exception(f"⚠️ Умный фарм упал ({e}) — откат к базовому циклу.")
            return super().run_farm_cycle(force_rescan=False, force_send=False)

    def _smart_cycle(self, force_rescan: bool = False):
        feats = self._features()
        if not any(feats.values()):
            logging.info("⏭️ Фарм выключен в настройках — пропуск (скан не запускается).")
            return False

        self._refresh_settings()
        self._ensure_targets(force_rescan, feats)

        # Герой — логика родителя без изменений (там уже сравнение сил).
        if feats["hero_only"]:
            return self.run_hero_farm()
        hero_sent = self.run_hero_farm() if feats["hero_with_troops"] else False

        targets = self._collect_targets()
        if not targets:
            if hero_sent:
                logging.info("🤷 Целей для войск нет, но герой отправлен.")
                return True
            logging.warning("🤷 Список целей пуст. Нечего атаковать.")
            return False

        troop_indices = self._troop_indices()
        tribe = self._tribe()
        pct = FI.safety_pct(self.settings.get("smart_safety_pct", FI.DEFAULT_SAFETY_PCT))
        cooldown_h = max(0.25, self._int_setting("cooldown_minutes", 60) / 60.0)
        lead_speed = FI.effective_speed(tribe, troop_indices[0],
                                       self.settings.get("troop_speed_tph"))

        ranked, dropped = FI.rank_targets(
            targets, self.farm_stats.data,
            speed_tph=lead_speed,
            ref_hours=cooldown_h,
            min_loot=self._int_setting("min_loot_per_raid", 0),
        )
        if dropped:
            logging.info(f"🗑️ Пропущено бедных целей: {len(dropped)} "
                         f"(например {dropped[0]['x']}|{dropped[0]['y']} — {dropped[0]['drop_reason']})")
        if not ranked:
            logging.warning("🤷 Все цели отфильтрованы как бесполезные.")
            return hero_sent

        summary = FI.stats_summary(self.farm_stats.data)
        logging.info(
            f"🧠 Умный фарм: {len(ranked)} целей | типы "
            f"{'+'.join('t' + str(i) for i in troop_indices)} | запас {pct}% | "
            f"отчётов в истории: {summary['reports']}, целей с лутом: {summary['with_loot']}"
        )
        if not summary["with_loot"]:
            logging.info("ℹ️ Лут по целям ещё не известен (нужен сбор отчётов) — "
                         "порядок пока по дистанции.")

        return self._send_wave(ranked, troop_indices, tribe, pct) or hero_sent

    def _ensure_targets(self, force_rescan: bool, feats: dict):
        """Гарантирует наличие списков целей (скан — только при необходимости)."""
        has_list = self.load_saved_oases()
        if not has_list and self.load_occupied_oases():
            # Умный режим умеет фармить и занятые оазисы, значит список есть.
            has_list = True
        if has_list and not force_rescan:
            return
        if force_rescan or self._scan_is_stale():
            logging.info("📡 Запускаю скан оазисов...")
            cx, cy = self.get_current_village_coords()
            self.scan_oases_around(cx, cy)
            self.load_saved_oases()
        else:
            logging.info("⏭️ Скан пропущен: предыдущий был недавно (rescan_interval_hours).")

    def _collect_targets(self) -> list:
        """Пустые оазисы + (опционально) занятые животными."""
        max_dist = float(self.settings.get("max_distance", 0) or 0)
        out = []
        for o in (self.farm_list or []):
            out.append({"x": o.get("x"), "y": o.get("y"),
                        "distance": o.get("distance", 0.0),
                        "kind": "empty", "animals": {}})
        if self._bool_setting("smart_weak_animals", True):
            for o in self.load_occupied_oases():
                if o.get("has_player_troops"):
                    continue
                animals = o.get("animals") or {}
                if not animals:
                    continue  # захваченные игроком записаны без животных
                out.append({"x": o.get("x"), "y": o.get("y"),
                            "distance": o.get("distance", 0.0),
                            "kind": "animals", "animals": animals,
                            "desc": o.get("desc", "")})
        if max_dist > 0:
            before = len(out)
            out = [t for t in out if float(t.get("distance") or 0) <= max_dist]
            if before != len(out):
                logging.info(f"📏 Фильтр дистанции (<= {max_dist}): убрано {before - len(out)} целей.")
        return out

    def _send_wave(self, ranked: list, troop_indices: list, tribe, pct: int) -> bool:
        cap = max(1, self._int_setting("troops_per_raid", 10))
        floor_units = max(1, self._int_setting("smart_min_units", 1))
        home = self._read_home_troops(troop_indices)

        sent = 0
        skipped = 0
        unreachable = 0
        occupied_now = []
        exhausted = set()
        rr = 0

        def available():
            return [i for i in troop_indices if i not in exhausted]

        try:
            for target in ranked:
                pool = available()
                if not pool:
                    logging.info("🛑 Все типы войск закончились. Стоп.")
                    break

                result = None
                used_type = None
                used_count = 0

                while pool:
                    idx = pool[rr % len(pool)]
                    plan = self._plan_pack(target, tribe, idx, pct, cap, floor_units, home)
                    if plan is None:
                        # Этим типом цель не взять (слишком сильные животные или
                        # нет таблицы атаки) — пробуем следующий тип.
                        rr += 1
                        pool = [i for i in pool if i != idx]
                        continue
                    if plan == "EXHAUSTED":
                        exhausted.add(idx)
                        pool = available()
                        continue

                    count, defense, limit, speed = plan
                    used_type, used_count = idx, count
                    result = self._attack(target, idx, count, limit, speed)
                    if result == "NO_TROOPS":
                        exhausted.add(idx)
                        logging.info(f"🚫 Войска t{idx} закончились — исключаю из ротации.")
                        pool = available()
                        continue
                    if result == "SUCCESS" and home.get(idx, -1) != -1:
                        home[idx] = home[idx] - count
                    break

                if result is None:
                    unreachable += 1
                    continue
                if result == "OCCUPIED":
                    occupied_now.append((target["x"], target["y"]))
                if result in ("ANIMALS", "PLAYER_TROOPS"):
                    skipped += 1
                if result == "SUCCESS":
                    sent += 1
                    rr += 1
                    self.farm_stats.record_raid(
                        target["x"], target["y"], used_type, used_count,
                        target.get("distance", 0.0),
                    )
                    time.sleep(random.uniform(2.5, 4.5))
        except KeyboardInterrupt:
            logging.info("🛑 Фарм прерван.")
            raise
        finally:
            if sent:
                self.farm_stats.save()
            if occupied_now:
                self.farm_list = [o for o in self.farm_list
                                  if (o.get("x"), o.get("y")) not in occupied_now]
                self._save_to_json(self._file("unoccupied_oases"),
                                   self.current_village_id, self.farm_list)
                logging.info(f"🚩 Удалено занятых игроком целей: {len(occupied_now)}")

        msg = f"🏁 Фарм завершён. Отправлено набегов: {sent}"
        if skipped:
            msg += f" | пропущено из-за животных/подмоги: {skipped}"
        if unreachable:
            msg += f" | не по зубам имеющимся войскам: {unreachable}"
        logging.info(msg)

        try:
            self.page.goto(f"{self.config.base_url}/{self.LOCATORS['village_view']}")
            self.page.wait_for_load_state('domcontentloaded')
        except Exception:
            logging.debug("возврат на dorf1 после фарма не удался", exc_info=True)
        return sent > 0

    def _plan_pack(self, target: dict, tribe, idx: int, pct: int,
                   cap: int, floor_units: int, home: dict):
        """Сколько юнитов типа idx слать на цель.

        Возвращает (count, defense, limit, speed) | None (цель не для этого типа)
        | "EXHAUSTED" (у типа не хватает юнитов вообще).
        """
        is_cav = US.is_cavalry(tribe, idx)
        defense = FI.animal_defense(target.get("animals"), self.ANIMAL_STATS,
                                    vs_cavalry=is_cav)
        need = FI.units_needed_for(tribe, idx, defense, pct)
        if need < 0:
            # Нет таблицы атаки (неизвестное племя/индекс). На животных не идём.
            if defense > 0:
                return None
            need = 0

        carry = US.carry_of(tribe, idx)
        count = FI.recommended_count(
            target.get("exp_loot"), carry,
            default_count=cap, min_count=floor_units, max_count=cap,
            need_units=need,
        )
        # Животные сильнее, чем может потолок пачки — цель не наша.
        if need > cap:
            return None

        have = home.get(idx, -1)
        if have != -1:
            minimal = max(1, need, floor_units)
            if have < minimal:
                return "EXHAUSTED"
            count = min(count, have)

        limit = FI.safe_defense_limit(tribe, idx, count, pct)
        speed = FI.effective_speed(tribe, idx, self.settings.get("troop_speed_tph"))
        return count, defense, limit, speed

    def _attack(self, target: dict, idx: int, count: int, limit: int, speed: float) -> str:
        """Отправка через родительский attack_oasis.

        limit > 0 — разрешаем занятые оазисы с защитой до limit: та же
        механика, что у героя. Свежая проверка животных перед отправкой
        выполняется внутри attack_oasis — если зверь пришёл, вернётся ANIMALS.

        Скорость подменяется на время вызова: кулдаун цели внутри родителя
        считается из settings["troop_speed_tph"], а она у каждого типа своя.
        """
        prev_speed = self.settings.get("troop_speed_tph")
        self.settings["troop_speed_tph"] = speed
        try:
            if limit > 0:
                return self.attack_oasis(
                    target["x"], target["y"], count, idx,
                    allow_occupied=True, max_defense=limit,
                    distance=target.get("distance", 0.0),
                )
            return self.attack_oasis(
                target["x"], target["y"], count, idx,
                distance=target.get("distance", 0.0),
            )
        finally:
            self.settings["troop_speed_tph"] = prev_speed

    # --- ЭВАКУАЦИЯ ---------------------------------------------------

    def evade_all_troops(self) -> str:
        """То же, что у родителя, но цель СНАЧАЛА проверяется живым запросом.

        В эвакуацию уходит ВСЯ армия, поэтому отправлять её по слепку
        скана недопустимо: за часы с момента скана в оазисе могли
        заспавниться животные, и спасение войск превращалось в их гибель.
        """
        target = self._pick_safe_evade_target()
        if not target:
            logging.error("🏃 Эвакуация ОТМЕНЕНА: нет ни одной проверенно пустой цели. "
                          "Лучше пережить атаку, чем потерять армию на животных.")
            return "NO_TARGET"

        self._evade_override = target
        try:
            self.settings["evade_target"] = dict(target)
            return super().evade_all_troops()
        finally:
            self._evade_override = None

    def _pick_safe_evade_target(self):
        """Первая проверенно пустая клетка из кандидатов или None."""
        self.update_village_identity()
        self._refresh_settings()

        candidates = []
        manual = self.settings.get("evade_target")
        if isinstance(manual, dict) and manual.get("x") is not None:
            candidates.append({"x": int(manual["x"]), "y": int(manual["y"]),
                               "distance": 0, "kind": "manual"})
        self.load_saved_oases()
        candidates += FI.evade_candidates(self.farm_list, self.load_occupied_oases(),
                                         limit=6)

        if not candidates:
            return None

        session = self._get_session()
        for cand in candidates:
            x, y = cand.get("x"), cand.get("y")
            if x is None or y is None:
                continue
            status = self._fetch_tile(session, x, y)
            if status.get("error"):
                logging.warning(f"🏃 Клетка ({x}|{y}) не ответила — не рискуем, следующая.")
                continue
            if status.get("is_conquered"):
                logging.info(f"🏃 ({x}|{y}) захвачен игроком — мимо.")
                continue
            if status.get("is_occupied"):
                logging.info(f"🏃 ({x}|{y}) занят ({status.get('animals') or 'войска'}) — мимо.")
                continue
            logging.info(f"🏃 Цель эвакуации проверена и пуста: ({x}|{y}).")
            return {"x": x, "y": y}
        return None
