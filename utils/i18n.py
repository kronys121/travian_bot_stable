# -*- coding: utf-8 -*-
"""
Перевод строк логов на лету (RU -> EN) для отображения в GUI.

Логи бот пишет свободным русским текстом с эмодзи и подставленными
значениями (числа, координаты, имена). Здесь — словарь фраз на основе
регулярных выражений: русские куски заменяются на английские, а
динамические значения сохраняются через группы захвата.

Неизвестные строки возвращаются как есть (остаются на русском).
Эмодзи и временные метки не трогаются.
"""
import re

# Список правил (regex RU, замена EN). Порядок важен: более специфичные
# правила идут раньше более общих. Все правила применяются последовательно;
# английский текст не совпадает с кириллическими шаблонами, поэтому
# повторные замены безопасны.
_RAW_RULES = [
    # --- Фарм / оазисы ---
    (r"Оазис \((-?\d+)\|(-?\d+)\) на кулдауне \(~(\d+) мин, войска ещё в пути\)\.",
     r"Oasis (\1|\2) on cooldown (~\3 min, troops still returning)."),
    (r"Оазис \((-?\d+)\|(-?\d+)\): появились животные \(защита (\d+) > допустимо (\d+)\)\. Набег ОТМЕНЁН, цель остаётся в списке\.",
     r"Oasis (\1|\2): animals appeared (defense \3 > allowed \4). Raid CANCELLED, target kept in list."),
    (r"Оазис \((-?\d+)\|(-?\d+)\): войска игрока \(подмога\)\. Набег отменён, цель остаётся в списке\.",
     r"Oasis (\1|\2): player troops (reinforcement). Raid cancelled, target kept in list."),
    (r"Набег на \((-?\d+)\|(-?\d+)\) юнитами t(\d+)\.\.\.",
     r"Raiding (\1|\2) with t\3 units..."),
    (r"Фарм завершён\. Отправлено набегов: (\d+)",
     r"Farming complete. Raids sent: \1"),
    (r" \| пропущено из-за животных: (\d+)",
     r" | skipped due to animals: \1"),
    (r"(\d+) юнитов t(\d+) → \((-?\d+)\|(-?\d+)\)",
     r"\1 t\2 units -> (\3|\4)"),
    (r"Отправка войск: (\d+) целей \| (\d+) юнитов \(t(\d+)\)",
     r"Sending troops: \1 targets | \2 units (t\3)"),
    (r"Запускаю скан оазисов\.\.\.", r"Starting oasis scan..."),
    (r"Скан \(радиус (\d+)\) вокруг \((-?\d+)\|(-?\d+)\)\.\.\.",
     r"Scan (radius \1) around (\2|\3)..."),
    (r"Быстрый перескан (\d+) известных клеток\.\.\.",
     r"Quick rescan of \1 known tiles..."),
    (r"Нет сохранённых оазисов — запускаю полный скан\.",
     r"No saved oases — running full scan."),
    (r"Перепроверено (\d+)/(\d+) клеток\.\.\.", r"Rechecked \1/\2 tiles..."),
    (r"Просканировано (\d+) клеток\.\.\.", r"Scanned \1 tiles..."),
    (r"Перескан завершён! Пустых: (\d+) \| Занятых: (\d+)",
     r"Rescan complete! Empty: \1 | Occupied: \2"),
    (r"Скан завершён! Пустых: (\d+) \| Долин: (\d+)",
     r"Scan complete! Empty: \1 | Croppers: \2"),
    (r"Фильтр дистанции \(<= ([\d.]+)\): убрано (\d+) целей\.",
     r"Distance filter (<= \1): removed \2 targets."),
    (r"ПУСТОЙ: \((-?\d+)\|(-?\d+)\) \[Дист: ([\d.]+)\]",
     r"EMPTY: (\1|\2) [Dist: \3]"),
    (r"ЗАНЯТ \((-?\d+)\|(-?\d+)\) \[Дист: ([\d.]+)\]", r"OCCUPIED (\1|\2) [Dist: \3]"),
    (r"ДОЛИНА \((\w+) кропа\): \((-?\d+)\|(-?\d+)\) \[Дист: ([\d.]+)\]",
     r"CROPPER (\1 crop): (\2|\3) [Dist: \4]"),
    (r"Списка целей нет, а фарм выключен — скан пропущен\.",
     r"No target list and farming is off — scan skipped."),
    (r"Фарм выключен в настройках — пропуск \(скан не запускается\)\.",
     r"Farming disabled in settings — skipped (no scan)."),

    # --- Эвакуация / атаки ---
    (r"ВХОДЯЩИХ АТАК: (\d+) \| Ближайшая через: (.+)",
     r"INCOMING ATTACKS: \1 | Nearest in: \2"),
    (r"ЭВАКУАЦИЯ: увожу ВСЕ войска → \((-?\d+)\|(-?\d+)\)\.\.\.",
     r"EVACUATION: pulling ALL troops -> (\1|\2)..."),
    (r"ЭВАКУАЦИЯ: ~(\d+) юнитов уведено → \((-?\d+)\|(-?\d+)\)\. Вернутся сами\.",
     r"EVACUATION: ~\1 units sent -> (\2|\3). They will return on their own."),
    (r"Эвазия: эвакуирую все войска\.\.\.", r"Evasion: evacuating all troops..."),
    (r"Эвазия на кулдауне ещё ~(\d+)с — пропуск\.",
     r"Evasion on cooldown ~\1s more — skipped."),
    (r"Эвакуация: в деревне нет войск для увода\.",
     r"Evacuation: no troops in the village to pull."),
    (r"Эвакуация: кнопка подтверждения не найдена\.",
     r"Evacuation: confirm button not found."),
    (r"Эвакуация: нет цели \(список оазисов пуст, evade_target не задан\)\.",
     r"Evacuation: no target (oasis list empty, evade_target not set)."),
    (r"Эвакуация не удалась: (.+)", r"Evacuation failed: \1"),
    (r"CAPTCHA обнаружена! Бот приостановлен\.",
     r"CAPTCHA detected! Bot paused."),

    # --- Тренировка ---
    (r"Очередь тренировки: (\d+) тип\(ов\) войск\.",
     r"Training queue: \1 troop type(s)."),
    (r"\[(\w+)\] Войск t(\d+): (\d+)/(\d+)", r"[\1] Troops t\2: \3/\4"),
    (r"t(\d+): цель достигнута\.", r"t\1: target reached."),
    (r"t(\d+): нужно дотренировать (\d+) юнитов\.",
     r"t\1: need to train \2 more units."),
    (r"Отправлено в тренировку: (\d+) юнитов t(\d+)\.",
     r"Queued for training: \1 units t\2."),
    (r"Войска t(\d+) отсутствуют\.", r"No t\1 troops."),
    (r"Поле t(\d+) недоступно\.", r"Field t\1 unavailable."),
    (r"Тренировка выключена в настройках — пропуск\.",
     r"Training disabled in settings — skipped."),
    (r"Кнопка тренировки недоступна \(недостаточно ресурсов\?\)\.",
     r"Train button unavailable (not enough resources?)."),

    # --- Стройка ---
    (r"Запуск Smart Builder \(Деревня: (.+?), Шаг: (.+?)\)\.\.\.",
     r"Starting Smart Builder (Village: \1, Step: \2)..."),
    (r"Анализ плана постройки \(начиная с шага (\d+)\)\.\.\.",
     r"Analyzing build plan (starting from step \1)..."),
    (r"Наша текущая цель: \[(\d+)/(\d+)\] (.+?) \(до (\d+) ур\.\)",
     r"Current target: [\1/\2] \3 (to level \4)"),
    (r"\[(\d+)/(\d+)\] (.+?) уже на уровне (\d+)\.",
     r"[\1/\2] \3 already at level \4."),
    (r"План постройки для x(\d+) загружен!", r"Build plan for x\1 loaded!"),
    (r"План постройки для этой деревни полностью завершен!",
     r"Build plan for this village fully complete!"),
    (r"Продолжаю стройку с сохранённого шага (\d+)\.",
     r"Resuming build from saved step \1."),
    (r"Здание (.+?) успешно поставлено в очередь! Иду в другую деревню\.",
     r"Building \1 queued successfully! Moving to another village."),
    (r"Со второй попытки (.+?) заказано! Иду в другую деревню\.",
     r"Ordered \1 on second attempt! Moving to another village."),
    (r"Ищу чертеж здания \(GID: (\d+)\) во вкладках постройки \(через (.+?)\)\.\.\.",
     r"Looking for building (GID: \1) in build tabs (via \2)..."),
    (r"Чертеж найден! Пытаюсь построить\.\.\.", r"Building found! Trying to build..."),
    (r"Чертеж не найден ни в одной вкладке\.", r"Building not found in any tab."),
    (r"Очередь стройки: было (\d+), стало (\d+)\.",
     r"Build queue: was \1, now \2."),
    (r"Очередь постройки в этой деревне занята\. Перехожу к следующей деревне\.",
     r"Build queue in this village is busy. Moving to next village."),
    (r"Для деревни (.+?) нет плана\. Пропускаю\.",
     r"No plan for village \1. Skipping."),
    (r"Здание найдено, но кнопка недоступна \(не хватает ресов или требований\)\.",
     r"Building found, but button unavailable (missing resources or requirements)."),
    (r"Кнопка section2 недоступна — перехожу на обычную стройку\.",
     r"section2 button unavailable — switching to normal build."),
    (r"SmartBuilder прерван пользователем\. Возврат в меню\.\.\.",
     r"SmartBuilder interrupted by user. Returning to menu..."),

    # --- Реклама ---
    (r"Стройка через рекламу \(section2\), попытка (\d+)/(\d+)\.\.\.",
     r"Ad-boosted build (section2), attempt \1/\2..."),
    (r"Стройка через рекламу запущена \(-25% времени постройки\)!",
     r"Ad-boosted build started (-25% build time)!"),
    (r"После рекламы стройка не началась \(попытка (\d+)/(\d+)\)\.",
     r"Build did not start after ad (attempt \1/\2)."),
    (r"Реклама не сработала — строю обычным способом \(section1\)\.",
     r"Ad failed — building the normal way (section1)."),
    (r"Смотрю рекламу \(~(\d+)с\)\.\.\.", r"Watching ad (~\1s)..."),
    (r"Запустил воспроизведение видео\.", r"Started video playback."),
    (r"Нажал запасную кнопку воспроизведения\.", r"Clicked fallback play button."),
    (r"Подтвердил окно согласия на просмотр рекламы\.",
     r"Confirmed ad consent dialog."),
    (r"Отключил звук рекламы\.", r"Muted the ad."),

    # --- Ресурсы / зерно / склад ---
    (r"Ресурсы пополнены! Делаю вторую попытку\.\.\.",
     r"Resources replenished! Making a second attempt..."),
    (r"Не хватает ресурсов для (.+?)\. Пробую пополнить\.\.\.",
     r"Not enough resources for \1. Trying to replenish..."),
    (r"Ресурсы отправлены в \((-?\d+)\|(-?\d+)\): (.+)",
     r"Resources sent to (\1|\2): \3"),
    (r"Ресурсы перенесены\.", r"Resources transferred."),
    (r"Ресурсы перенесены \(без доп\. подтверждения\)\.",
     r"Resources transferred (no extra confirmation)."),
    (r"Мало свободного зерна — пробую улучшить ферму \(Cropland\)\.",
     r"Low free crop — trying to upgrade a Cropland field."),
    (r"Свободное зерно сейчас: (-?\d+)", r"Free crop now: \1"),
    (r"Улучшить ферму сейчас нельзя \(нет ресурсов или очередь\)\.",
     r"Cannot upgrade cropland now (no resources or queue busy)."),
    (r"Ферма отправлена на улучшение — зерно вырастет\.",
     r"Cropland sent to upgrade — crop will increase."),
    (r"Поля-фермы не найдены\.", r"Cropland fields not found."),
    (r"Выбран максимум ресурсов\.", r"Selected max resources."),
    (r"Склад (\d+)%, зернохранилище (\d+)% — обмен не нужен\.",
     r"Warehouse \1%, granary \2% — no trade needed."),
    (r"Обмен NPC: склад (\d+)%, зернохранилище (\d+)%",
     r"NPC trade: warehouse \1%, granary \2%"),
    (r"NPC-обмен выполнен: (.+)", r"NPC trade done: \1"),
    (r"Таб NPC недоступен \(возможно, нет МП или нет золота\)\.",
     r"NPC tab unavailable (maybe no marketplace or no gold)."),

    # --- Герой / приключения ---
    (r"Текущее здоровье: (\d+)%", r"Current health: \1%"),
    (r"Герой здоров! Проверяю список приключений\.\.\.",
     r"Hero is healthy! Checking adventures list..."),
    (r"Герой отправлен в приключение — фарм оазисов пропущен\.",
     r"Hero sent on adventure — oasis farming skipped."),
    (r"Герой уже в приключении \(кнопка disabled\)\.",
     r"Hero already on adventure (button disabled)."),
    (r"Герой успешно отправлен в приключение!",
     r"Hero sent on adventure successfully!"),
    (r"Сила героя: (\d+) \| Запас прочности: (\d+)%",
     r"Hero power: \1 | Safety margin: \2%"),
    (r"Не удалось определить силу героя — фарм героем пропущен\.",
     r"Could not determine hero power — hero farming skipped."),
    (r"Проверка ресурсов в инвентаре героя\.\.\.",
     r"Checking hero inventory resources..."),
    (r"Здоровье \((\d+)%\) ниже порога \((\d+)%\)\. Идти опасно!",
     r"Health (\1%) below threshold (\2%). Too risky to go!"),
    (r"Выбрано приключение: Дистанция: ([\d.]+), Сложность: (.+)",
     r"Adventure selected: Distance: \1, Difficulty: \2"),
    (r"Доступно приключений: (\d+)", r"Adventures available: \1"),
    (r"Список приключений пуст\.", r"Adventures list is empty."),
    (r"Список приключений пуст \(найдена заглушка\)\.",
     r"Adventures list is empty (placeholder found)."),
    (r"Таблица приключений не найдена на странице\.",
     r"Adventures table not found on the page."),
    (r"Кнопка отправки недоступна \(возможно герой уже в пути\)\.",
     r"Send button unavailable (hero may already be en route)."),

    # --- Задания / награды ---
    (r"Проверка ежедневных квестов\.\.\.", r"Checking daily quests..."),
    (r"Готовых ежедневных наград нет\.", r"No daily rewards ready."),
    (r"Блок ежедневных квестов не найден — пропуск\.",
     r"Daily quests block not found — skipped."),
    (r"Ежедневная награда #(\d+) собрана!", r"Daily reward #\1 collected!"),
    (r"Ежедневных наград собрано: (\d+)", r"Daily rewards collected: \1"),
    (r"Награда #(\d+) собрана!", r"Reward #\1 collected!"),
    (r"Сбор завершен! Успешных нажатий: (\d+)",
     r"Collection complete! Successful clicks: \1"),
    (r"Нажата кнопка collectRewards, жду collect\.\.\.",
     r"Clicked collectRewards, waiting for collect..."),
    (r"Перехожу в меню заданий\.\.\.", r"Opening quests menu..."),
    (r"Меню заданий не прогрузилось\.", r"Quests menu did not load."),

    # --- Деревни / переключение ---
    (r"=== АКТИВНАЯ ДЕРЕВНЯ ===", r"=== ACTIVE VILLAGE ==="),
    (r"=== ПЕРЕКЛЮЧЕНИЕ НА ДЕРЕВНЮ \[(\d+)\] ===",
     r"=== SWITCHING TO VILLAGE [\1] ==="),
    (r"Возвращаюсь в главную деревню\.\.\.", r"Returning to the capital..."),
    (r"Деревня: (\d+)", r"Village: \1"),
    (r"Найдена только 1 деревня на аккаунте\.",
     r"Only 1 village found on the account."),
    (r"Найдено деревень: (\d+)", r"Villages found: \1"),

    # --- Настройки / общее ---
    (r"Настройки перезагружены \(изменены в GUI\)\.",
     r"Settings reloaded (changed in GUI)."),
    (r"Настройки фарма загружены: (.+)", r"Farm settings loaded: \1"),
    (r"Настройки фарма сохранены: (.+)", r"Farm settings saved: \1"),
    (r"Прогресс стройки сброшен для всех деревень\.",
     r"Build progress reset for all villages."),
    (r"Прогресс стройки сброшен для деревни (.+)\.",
     r"Build progress reset for village \1."),
    (r"Круг завершен\. Сплю (\d+) мин (\d+) сек\.\.\.",
     r"Cycle complete. Sleeping \1 min \2 sec..."),
    (r"Микро-перерыв: (\d+) сек\.\.\.", r"Micro-break: \1 sec..."),

    # --- Авторизация / куки ---
    (r"Вход по кукам\.", r"Logging in via cookies."),
    (r"Вход по логину/паролю\.\.\.", r"Logging in via login/password..."),
    (r"Куки успешно загружены\.", r"Cookies loaded successfully."),
    (r"Сохранены куки: (\d+) шт\. в (.+)", r"Cookies saved: \1 in \2"),
    (r"Файл с куки пуст или не существует\.",
     r"Cookie file is empty or missing."),
    (r"Куки не подошли, а TRAVIAN_EMAIL/TRAVIAN_PASSWORD не заданы\.",
     r"Cookies rejected and TRAVIAN_EMAIL/TRAVIAN_PASSWORD are not set."),

    # --- Telegram ---
    (r"Telegram отправлено\.", r"Telegram sent."),
    (r"Telegram уведомления активны \(акк: (.+?)\)\.",
     r"Telegram notifications active (acc: \1)."),
    (r"Telegram не настроен — использую NullNotifier\.",
     r"Telegram not configured — using NullNotifier."),
    (r"Нажмите Ctrl\+C, чтобы остановить\.", r"Press Ctrl+C to stop."),

    # --- Общие обрывки (в конце, самые общие) ---
    (r"Ошибка авторизации: (.+)", r"Authorization error: \1"),
    (r"Ошибка атаки: (.+)", r"Attack error: \1"),
    (r"Ошибка отправки: (.+)", r"Send error: \1"),
    (r"Ошибка тренировки: (.+)", r"Training error: \1"),
    (r"Ошибка инвентаря: (.+)", r"Inventory error: \1"),
    (r"Ошибка NPC-обмена: (.+)", r"NPC trade error: \1"),
    (r"Ошибка при поиске деревень: (.+)", r"Village search error: \1"),
    (r"Ошибка при проверке здоровья: (.+)", r"Health check error: \1"),
    (r"Ошибка чтения склада: (.+)", r"Warehouse read error: \1"),
    (r"Ошибка чтения войск: (.+)", r"Troops read error: \1"),
    (r"Ошибка сохранения настроек: (.+)", r"Settings save error: \1"),
]

# Компилируем один раз
_RULES = [(re.compile(pat), repl) for pat, repl in _RAW_RULES]


def translate_log_line(line: str, lang: str = "ru") -> str:
    """Переводит одну строку лога на EN. Для ru возвращает как есть."""
    if lang != "en" or not line:
        return line
    out = line
    for rx, repl in _RULES:
        out = rx.sub(repl, out)
    return out


def translate_logs(lines, lang: str = "ru"):
    """Переводит список строк логов."""
    if lang != "en":
        return list(lines)
    return [translate_log_line(ln, lang) for ln in lines]
