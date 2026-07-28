"""
gui.py — десктопная панель управления Travian Bot (CustomTkinter).

Запуск:
    python gui.py
    (или start.bat -> пункт [2])

Архитектура
-----------
GUI НЕ дублирует логику бэкенда. Веб-панель (app.py) и это окно — два
равноправных клиента одних и тех же функций:

    реестр аккаунтов    -> utils.accounts
    старт/стоп процесса -> app.start_account / app.stop_account
    настройки           -> utils.settings_store.SettingsStore
    команды боту        -> utils.commands.push_command
    валидация настроек  -> app._validate_settings

Поэтому правка из окна сразу видна в браузере и наоборот: обе стороны пишут
в один и тот же data/<acc>/settings.json, а бот перечитывает его по mtime.

Потоки
------
Tk не терпит обращений из чужих потоков. Всё, что может подвиснуть
(stop_account ждёт процесс до 10 секунд, чтение статистики лезет на диск),
уходит в Worker и возвращается в UI через root.after(0, ...).
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import customtkinter as ctk
except ImportError:
    raise SystemExit(
        "\n  Не установлен customtkinter.\n"
        "  Выполни:  pip install -r requirements.txt\n"
        "  (или запусти start.bat и выбери пункт [3])\n"
    )

from app import (  # noqa: E402
    _validate_settings as validate_settings,
    get_last_logs,
    get_store,
    is_alive,
    load_stats,
    load_status,
    proc_running,
    start_account,
    stop_account,
)
from utils.accounts import (  # noqa: E402
    delete_gui_account,
    is_yaml_account,
    load_accounts,
    upsert_gui_account,
)
from utils.commands import push_command  # noqa: E402
from utils.jsonio import write_json  # noqa: E402
from utils.paths import account_file, is_valid_account_name, log_file  # noqa: E402

try:
    from config.build_templates import TEMPLATES as BUILD_TEMPLATES
except Exception:  # шаблоны не критичны для запуска окна
    BUILD_TEMPLATES = {"x3": None}


# ============================================================================
# Палитра и константы
# ============================================================================

CLR = {
    "bg":       "#0d1420",
    "panel":    "#141d2b",
    "panel2":   "#1b2636",
    "line":     "#243044",
    "text":     "#eef2f7",
    "hint":     "#8fa0b3",
    "accent":   "#5aa2e8",
    "accent2":  "#7ab8f5",
    "pos":      "#4ade80",
    "neg":      "#f87171",
    "warn":     "#fbbf24",
}

REFRESH_MS = 4000          # период опроса состояния аккаунтов
LOG_REFRESH_MS = 3000      # период обновления вкладки логов

# Три взаимоисключающих режима фарма (radio-логика).
FARM_MODES = [
    ("farm_enabled",     "Только войсками",  "войска по пустым оазисам"),
    ("hero_only",        "Только героем",    "герой по оазисам с животными"),
    ("hero_with_troops", "Герой + войска",   "герой по животным, войска по пустым"),
]

# Обычные тумблеры. Ключи — ровно из settings_store.DEFAULT_SETTINGS['features'].
FEATURES = [
    ("build_enabled",          "Автостройка",            "по плану застройки"),
    ("build_night_enabled",    "Стройка ночью",          "работать в ночном окне"),
    ("build_use_ads",          "Стройка через рекламу",  "-25% времени"),
    ("train_enabled",          "Тренировка войск",       "дотренировка до цели"),
    ("smithy_enabled",         "Кузница",                "авто-улучшение войск"),
    ("smithy_use_ads",         "Кузница через рекламу",  "-25% времени"),
    ("tasks_enabled",          "Задания",                "ежедневные квесты"),
    ("adventure_enabled",      "Приключения",            "герой ходит в приключения"),
    ("adv_shorten_enabled",    "Сокращать приключения",  "просмотр видео"),
    ("adv_difficulty_enabled", "Повышать сложность",     "просмотр видео"),
    ("celebration_enabled",    "Праздники",              "малый праздник в Ратуше"),
    ("npc_trade_enabled",      "NPC-торговля",           "авто-обмен ресурсов"),
    ("transfer_enabled",       "Переброска ресурсов",    "излишки между деревнями"),
    ("reports_enabled",        "Читать отчёты",          "добыча / потери / профит"),
    ("grouped_cycle",          "Обход пачкой",           "все действия за один заход"),
    ("evasion_enabled",        "Эвакуация",              "при входящих атаках"),
]

# (ключ, подпись, тип, min, max) — границы совпадают с app._SETTINGS_BOUNDS,
# чтобы серверная валидация никогда не отвергала то, что показало окно.
NUM_SPEC = {
    "farm": [
        ("troops_per_raid",    "Войск на рейд",                  int,   1, 5000),
        ("troop_type_index",   "Тип войск (индекс 1-10)",        int,   1, 10),
        ("scan_radius",        "Радиус сканирования",            int,   1, 50),
        ("interval_minutes",   "Интервал фарма, мин",            int,   1, 1440),
        ("cooldown_minutes",   "Кулдаун цели, мин",              int,   0, 10080),
        ("max_distance",       "Макс. расстояние (0 = без)",     float, 0, 500),
        ("troop_speed_tph",    "Скорость войск, клеток/ч",       int,   0, 100),
        ("max_animal_defense", "Макс. защита животных",          int,   0, 10 ** 9),
        ("hero_min_health",    "Мин. HP героя, %",               int,   0, 100),
        ("hero_safety_pct",    "Запас силы героя, %",            int,   0, 10000),
    ],
    "training": [
        ("troop_type_index", "Тип войск (индекс 1-10)", int, 1, 10),
        ("target_count",     "Цель, шт",                int, 0, 1000000),
        ("min_queue_size",   "Не заказывать, если в очереди >=", int, 0, 100000),
        ("spend_pct",        "Тратить ресурсов, %",     int, 1, 100),
        ("max_batch",        "Потолок заказа (0 = без)", int, 0, 1000000),
    ],
    "trade": [
        ("npc_threshold_pct",     "Порог NPC-обмена, %",      int, 0, 100),
        ("transfer_interval_min", "Интервал переброски, мин", int, 1, 10080),
    ],
    "night": [
        ("start", "Начало ночи (час)", int, 0, 23),
        ("end",   "Конец ночи (час)",  int, 0, 23),
    ],
}

TRIBES = ["roman", "teuton", "gaul", "egyptian", "hun", "spartan"]
BUILDINGS = ["barracks", "stable", "workshop"]

TASK_LABELS = {
    "farm": "Фарм",
    "build": "Стройка",
    "train": "Тренировка",
    "tasks": "Задания",
    "adventure": "Приключения",
    "celebration": "Праздники",
    "smithy": "Кузница",
    "npc_trade": "NPC-торговля",
    "transfer": "Переброска",
    "stats": "Статистика",
    "reports": "Отчёты",
}


# ============================================================================
# Утилиты
# ============================================================================

def err_text(exc: BaseException) -> str:
    """HTTPException несёт текст в .detail, обычное исключение — в str()."""
    return str(getattr(exc, "detail", None) or exc)


def fmt_num(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(v):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def fmt_dur(sec) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    if sec < 0:
        return ""
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return (f"{h}ч " if h else "") + f"{m:02d}:{s:02d}"


class Worker:
    """Блокирующая работа в фоне, результат — обратно в Tk-поток."""

    def __init__(self, root):
        self.root = root

    def run(self, fn, on_done=None, on_error=None):
        def target():
            try:
                res = fn()
            except Exception as exc:  # noqa: BLE001 — показываем пользователю
                # exc биндим аргументом: после выхода из except имя удаляется
                self.root.after(0, lambda e=exc: (on_error or self._show)(e))
                return
            if on_done is not None:
                self.root.after(0, lambda r=res: on_done(r))

        threading.Thread(target=target, daemon=True).start()

    @staticmethod
    def _show(exc):
        messagebox.showerror("Ошибка", err_text(exc))


def collect_snapshot() -> list[dict]:
    """Полный срез состояния всех аккаунтов. Выполняется в фоновом потоке."""
    rows = []
    for acc in load_accounts():
        name = acc.get("name") or ""
        if not is_valid_account_name(name):
            continue
        status = load_status(name)
        rows.append({
            "name": name,
            "server": acc.get("server", "") or "",
            "email": acc.get("email", "") or "",
            "has_password": bool(acc.get("password")),
            "rate": acc.get("rate", 3),
            "headless": acc.get("headless", True),
            "proxy": acc.get("proxy", "") or "",
            "build_template": acc.get("build_template", "x3"),
            "from_yaml": is_yaml_account(name),
            "running": proc_running(name) or is_alive(status),
            "status": status,
            "stats": load_stats(name),
        })
    return rows


# ============================================================================
# Мелкие виджеты
# ============================================================================

class AccountCard(ctk.CTkFrame):
    """Карточка аккаунта в боковой панели."""

    def __init__(self, master, name: str, on_click):
        super().__init__(master, fg_color=CLR["panel2"], corner_radius=12)
        self.name = name
        self._selected = False

        self.grid_columnconfigure(1, weight=1)
        self.lamp = ctk.CTkLabel(self, text="●", width=14, text_color=CLR["neg"],
                                 font=ctk.CTkFont(size=15))
        self.lamp.grid(row=0, column=0, padx=(12, 6), pady=(10, 0), sticky="w")
        self.title = ctk.CTkLabel(self, text=name, anchor="w",
                                  font=ctk.CTkFont(size=14, weight="bold"))
        self.title.grid(row=0, column=1, padx=(0, 10), pady=(10, 0), sticky="ew")
        self.sub = ctk.CTkLabel(self, text="—", anchor="w", text_color=CLR["hint"],
                                font=ctk.CTkFont(size=11))
        self.sub.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="ew")

        for w in (self, self.lamp, self.title, self.sub):
            w.bind("<Button-1>", lambda _e, n=name: on_click(n))

    def update_state(self, running: bool, subtitle: str):
        self.lamp.configure(text_color=CLR["pos"] if running else CLR["neg"])
        text = subtitle if len(subtitle) <= 34 else subtitle[:33] + "…"
        self.sub.configure(text=text)

    def set_selected(self, flag: bool):
        if flag == self._selected:
            return
        self._selected = flag
        self.configure(fg_color=CLR["accent"] if flag else CLR["panel2"])
        self.title.configure(text_color="#0b1420" if flag else CLR["text"])
        self.sub.configure(text_color="#123" if flag else CLR["hint"])


def section_title(master, text: str, row: int, pady=(16, 6)):
    lbl = ctk.CTkLabel(master, text=text.upper(), anchor="w", text_color=CLR["accent"],
                       font=ctk.CTkFont(size=12, weight="bold"))
    lbl.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=pady)
    return lbl


def switch_row(master, row: int, label: str, hint: str, variable):
    box = ctk.CTkFrame(master, fg_color="transparent")
    box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=2)
    box.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(box, text=label, anchor="w",
                 font=ctk.CTkFont(size=13)).grid(row=0, column=0, sticky="w")
    ctk.CTkLabel(box, text=hint, anchor="w", text_color=CLR["hint"],
                 font=ctk.CTkFont(size=11)).grid(row=1, column=0, sticky="w")
    sw = ctk.CTkSwitch(box, text="", variable=variable, onvalue=True, offvalue=False,
                       progress_color=CLR["accent"], width=44)
    sw.grid(row=0, column=1, rowspan=2, padx=(10, 4))
    return sw


def entry_row(master, row: int, label: str, variable, hint: str = ""):
    box = ctk.CTkFrame(master, fg_color="transparent")
    box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=3)
    box.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(box, text=label, anchor="w", text_color=CLR["hint"],
                 font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
    ent = ctk.CTkEntry(box, textvariable=variable, height=32, border_width=1,
                       fg_color=CLR["panel2"], border_color=CLR["line"])
    ent.grid(row=1, column=0, sticky="ew")
    if hint:
        ctk.CTkLabel(box, text=hint, anchor="w", text_color=CLR["hint"],
                     font=ctk.CTkFont(size=10)).grid(row=2, column=0, sticky="w")
    return ent


def option_row(master, row: int, label: str, variable, values: list[str]):
    box = ctk.CTkFrame(master, fg_color="transparent")
    box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=3)
    box.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(box, text=label, anchor="w", text_color=CLR["hint"],
                 font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
    opt = ctk.CTkOptionMenu(box, variable=variable, values=values, height=32,
                            fg_color=CLR["panel2"], button_color=CLR["line"],
                            button_hover_color=CLR["accent"])
    opt.grid(row=1, column=0, sticky="ew")
    return opt


# ============================================================================
# Диалог аккаунта
# ============================================================================

class AccountDialog(ctk.CTkToplevel):
    """Создание нового аккаунта. Редактирование живёт во вкладке «Подключение»."""

    def __init__(self, master, on_saved):
        super().__init__(master, fg_color=CLR["bg"])
        self.title("Новый аккаунт")
        self.geometry("420x560")
        self.resizable(False, False)
        self.on_saved = on_saved
        self.transient(master)

        self.v_name = ctk.StringVar()
        self.v_server = ctk.StringVar()
        self.v_email = ctk.StringVar()
        self.v_pass = ctk.StringVar()
        self.v_rate = ctk.StringVar(value="3")
        self.v_proxy = ctk.StringVar()
        self.v_headless = ctk.BooleanVar(value=True)
        self.v_tpl = ctk.StringVar(value="x3")

        wrap = ctk.CTkScrollableFrame(self, fg_color=CLR["panel"], corner_radius=14)
        wrap.pack(fill="both", expand=True, padx=14, pady=14)
        wrap.grid_columnconfigure(0, weight=1)

        r = 0
        entry_row(wrap, r, "Имя аккаунта", self.v_name,
                  "только A-Z a-z 0-9 _ -, до 64 символов"); r += 1
        entry_row(wrap, r, "Сервер", self.v_server,
                  "например ts30.x3.international.travian.com"); r += 1
        entry_row(wrap, r, "Email / логин", self.v_email); r += 1
        ent = entry_row(wrap, r, "Пароль", self.v_pass,
                        "можно оставить пустым и задать в .env"); r += 1
        ent.configure(show="•")
        entry_row(wrap, r, "Скорость сервера (rate)", self.v_rate); r += 1
        entry_row(wrap, r, "Прокси", self.v_proxy,
                  "http://user:pass@host:port или socks5://..."); r += 1
        option_row(wrap, r, "Шаблон застройки", self.v_tpl,
                   sorted(BUILD_TEMPLATES.keys())); r += 1
        switch_row(wrap, r, "Скрытый браузер", "headless", self.v_headless); r += 1

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(bar, text="Отмена", fg_color=CLR["panel2"], hover_color=CLR["line"],
                      command=self.destroy).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(bar, text="Создать", fg_color=CLR["accent"],
                      hover_color=CLR["accent2"], text_color="#0b1420",
                      command=self._save).pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.after(200, self.grab_set)

    def _save(self):
        name = self.v_name.get().strip()
        server = self.v_server.get().strip()
        if not is_valid_account_name(name):
            messagebox.showwarning("Проверь имя", "Разрешены A-Z a-z 0-9 _ - , до 64 символов.",
                                   parent=self)
            return
        if not server:
            messagebox.showwarning("Проверь сервер", "Укажи адрес игрового мира.", parent=self)
            return
        try:
            rate = int(self.v_rate.get())
        except ValueError:
            messagebox.showwarning("Проверь rate", "Скорость сервера — целое число.", parent=self)
            return

        data = {
            "name": name,
            "server": server.replace("https://", "").replace("http://", "").strip("/"),
            "rate": rate,
            "headless": bool(self.v_headless.get()),
            "proxy": self.v_proxy.get().strip(),
            "build_template": self.v_tpl.get(),
        }
        # Пустой логин/пароль означает «взять из .env», а не «записать пустоту».
        if self.v_email.get().strip():
            data["email"] = self.v_email.get().strip()
        if self.v_pass.get().strip():
            data["password"] = self.v_pass.get().strip()

        try:
            upsert_gui_account(data)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Не удалось сохранить", err_text(exc), parent=self)
            return
        self.destroy()
        self.on_saved(name)


# ============================================================================
# Главное окно
# ============================================================================

class TravianGUI(ctk.CTk):

    def __init__(self):
        super().__init__(fg_color=CLR["bg"])
        self.title("Travian Bot — панель управления")
        self.geometry("1180x780")
        self.minsize(1000, 640)

        self.worker = Worker(self)
        self.rows: list[dict] = []
        self.current: str | None = None
        self.cards: dict[str, AccountCard] = {}
        self._stores: dict[str, object] = {}
        self._settings_built_for: str | None = None
        self._task_order: list[str] = []
        self._busy = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick()
        self._log_tick()

    # ---------------------------------------------------------------- каркас

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, fg_color=CLR["panel"], corner_radius=0, width=270)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)
        bar.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(bar, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 10))
        ctk.CTkLabel(head, text="TRAVIAN BOT", text_color=CLR["accent"],
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w")
        self.lbl_refreshed = ctk.CTkLabel(head, text="обновление…", text_color=CLR["hint"],
                                          font=ctk.CTkFont(size=10))
        self.lbl_refreshed.pack(anchor="w")

        self.list_frame = ctk.CTkScrollableFrame(bar, fg_color="transparent")
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=10)
        self.list_frame.grid_columnconfigure(0, weight=1)

        foot = ctk.CTkFrame(bar, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=14, pady=14)
        ctk.CTkButton(foot, text="+  Добавить аккаунт", height=36,
                      fg_color=CLR["accent"], hover_color=CLR["accent2"],
                      text_color="#0b1420", font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._add_account).pack(fill="x")
        ctk.CTkButton(foot, text="Открыть веб-панель", height=32,
                      fg_color=CLR["panel2"], hover_color=CLR["line"],
                      command=lambda: webbrowser.open("http://127.0.0.1:8000")
                      ).pack(fill="x", pady=(8, 0))

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(14, 14), pady=14)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        # --- шапка выбранного аккаунта
        head = ctk.CTkFrame(main, fg_color=CLR["panel"], corner_radius=16)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        self.h_lamp = ctk.CTkLabel(head, text="●", width=18, text_color=CLR["hint"],
                                   font=ctk.CTkFont(size=18))
        self.h_lamp.grid(row=0, column=0, rowspan=2, padx=(18, 8), pady=16)
        self.h_name = ctk.CTkLabel(head, text="Выбери аккаунт", anchor="w",
                                   font=ctk.CTkFont(size=19, weight="bold"))
        self.h_name.grid(row=0, column=1, sticky="ew", pady=(16, 0))
        self.h_sub = ctk.CTkLabel(head, text="—", anchor="w", text_color=CLR["hint"],
                                  font=ctk.CTkFont(size=12))
        self.h_sub.grid(row=1, column=1, sticky="ew", pady=(0, 16))

        # --- кнопки действий
        acts = ctk.CTkFrame(main, fg_color="transparent")
        acts.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        self.btn_start = self._action(acts, "▶  Старт", CLR["pos"], self._start)
        self.btn_stop = self._action(acts, "■  Стоп", CLR["neg"], self._stop)
        self.btn_scan = self._action(acts, "Полный скан", CLR["panel2"],
                                     lambda: self._command("scan"))
        self.btn_rescan = self._action(acts, "Перескан", CLR["panel2"],
                                       lambda: self._command("rescan"))
        self.btn_farm = self._action(acts, "Фарм сейчас", CLR["panel2"],
                                     lambda: self._command("force_farm"))
        self.btn_reset = self._action(acts, "Сброс стройки", CLR["panel2"], self._reset_build)

        # --- вкладки
        self.tabs = ctk.CTkTabview(main, fg_color=CLR["panel"], corner_radius=16,
                                   segmented_button_selected_color=CLR["accent"],
                                   segmented_button_selected_hover_color=CLR["accent2"],
                                   text_color=CLR["text"])
        self.tabs.grid(row=2, column=0, sticky="nsew")
        for tab in ("Обзор", "Настройки", "Порядок задач", "Логи", "Подключение"):
            self.tabs.add(tab)

        self._build_tab_overview(self.tabs.tab("Обзор"))
        self._build_tab_settings(self.tabs.tab("Настройки"))
        self._build_tab_order(self.tabs.tab("Порядок задач"))
        self._build_tab_logs(self.tabs.tab("Логи"))
        self._build_tab_conn(self.tabs.tab("Подключение"))

        # --- статус-строка
        self.status = ctk.CTkLabel(main, text="", anchor="w", text_color=CLR["hint"],
                                   font=ctk.CTkFont(size=12))
        self.status.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _action(self, master, text, color, command):
        btn = ctk.CTkButton(
            master, text=text, command=command, height=38, width=140,
            fg_color=color, hover_color=CLR["accent2"] if color == CLR["panel2"] else color,
            text_color="#0b1420" if color in (CLR["pos"], CLR["neg"]) else CLR["text"],
            font=ctk.CTkFont(size=13, weight="bold"), state="disabled",
        )
        btn.pack(side="left", padx=(0, 8))
        return btn

    # ------------------------------------------------------------- вкладки

    def _build_tab_overview(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self.ov = ctk.CTkTextbox(tab, fg_color=CLR["bg"], border_width=0, wrap="none",
                                 font=ctk.CTkFont(family="Consolas", size=13))
        self.ov.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        for tag, color in (("h", CLR["accent"]), ("ok", CLR["pos"]),
                           ("err", CLR["neg"]), ("warn", CLR["warn"]),
                           ("dim", CLR["hint"])):
            self._tag(self.ov, tag, color)
        self.ov.configure(state="disabled")

    def _build_tab_settings(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self.set_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.set_scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        self.set_scroll.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        self.set_msg = ctk.CTkLabel(bar, text="", anchor="w", text_color=CLR["hint"])
        self.set_msg.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(bar, text="Сохранить настройки", height=38, width=200,
                      fg_color=CLR["accent"], hover_color=CLR["accent2"],
                      text_color="#0b1420", font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._save_settings).pack(side="right")

    def _build_tab_order(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(tab, text="Чем выше задача — тем раньше она выполнится, "
                               "когда несколько готовы одновременно.",
                     text_color=CLR["hint"], anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="ew",
                                                     padx=14, pady=(12, 4))
        self.order_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.order_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        self.order_frame.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        self.order_msg = ctk.CTkLabel(bar, text="", anchor="w", text_color=CLR["hint"])
        self.order_msg.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(bar, text="Сохранить порядок", height=38, width=200,
                      fg_color=CLR["accent"], hover_color=CLR["accent2"],
                      text_color="#0b1420", font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._save_order).pack(side="right")

    def _build_tab_logs(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self.v_autolog = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(bar, text="Автообновление", variable=self.v_autolog,
                      progress_color=CLR["accent"]).pack(side="left")
        self.v_lines = ctk.StringVar(value="200")
        ctk.CTkOptionMenu(bar, variable=self.v_lines, values=["100", "200", "500", "1000"],
                          width=90, fg_color=CLR["panel2"], button_color=CLR["line"],
                          button_hover_color=CLR["accent"]).pack(side="left", padx=10)
        ctk.CTkButton(bar, text="Обновить", width=110, fg_color=CLR["panel2"],
                      hover_color=CLR["line"],
                      command=self._refresh_logs).pack(side="left")
        ctk.CTkButton(bar, text="Открыть файл", width=130, fg_color=CLR["panel2"],
                      hover_color=CLR["line"],
                      command=self._open_log_file).pack(side="left", padx=10)

        self.logbox = ctk.CTkTextbox(tab, fg_color=CLR["bg"], border_width=0, wrap="word",
                                     font=ctk.CTkFont(family="Consolas", size=12))
        self.logbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        for tag, color in (("err", CLR["neg"]), ("warn", CLR["warn"]), ("ok", CLR["pos"])):
            self._tag(self.logbox, tag, color)
        self.logbox.configure(state="disabled")

    def _build_tab_conn(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        wrap = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        wrap.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        wrap.grid_columnconfigure(0, weight=1)

        self.c_server = ctk.StringVar()
        self.c_email = ctk.StringVar()
        self.c_pass = ctk.StringVar()
        self.c_rate = ctk.StringVar()
        self.c_proxy = ctk.StringVar()
        self.c_headless = ctk.BooleanVar(value=True)
        self.c_tpl = ctk.StringVar(value="x3")

        r = 0
        section_title(wrap, "Подключение", r, pady=(4, 6)); r += 1
        entry_row(wrap, r, "Сервер", self.c_server); r += 1
        entry_row(wrap, r, "Email / логин", self.c_email); r += 1
        p = entry_row(wrap, r, "Пароль", self.c_pass,
                      "пусто = не менять (или берётся из .env)"); r += 1
        p.configure(show="•")
        entry_row(wrap, r, "Скорость сервера (rate)", self.c_rate); r += 1
        entry_row(wrap, r, "Прокси", self.c_proxy,
                  "http://user:pass@host:port или socks5://user:pass@host:port"); r += 1
        option_row(wrap, r, "Шаблон застройки", self.c_tpl,
                   sorted(BUILD_TEMPLATES.keys())); r += 1
        switch_row(wrap, r, "Скрытый браузер", "headless", self.c_headless); r += 1

        self.c_note = ctk.CTkLabel(wrap, text="", anchor="w", text_color=CLR["warn"],
                                   font=ctk.CTkFont(size=11), wraplength=620, justify="left")
        self.c_note.grid(row=r, column=0, sticky="ew", padx=4, pady=(10, 0)); r += 1

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.c_msg = ctk.CTkLabel(bar, text="", anchor="w", text_color=CLR["hint"])
        self.c_msg.pack(side="left", fill="x", expand=True)
        self.btn_del = ctk.CTkButton(bar, text="Удалить аккаунт", width=160, height=38,
                                     fg_color=CLR["panel2"], hover_color=CLR["neg"],
                                     command=self._delete_account)
        self.btn_del.pack(side="right", padx=(8, 0))
        ctk.CTkButton(bar, text="Сохранить подключение", width=210, height=38,
                      fg_color=CLR["accent"], hover_color=CLR["accent2"],
                      text_color="#0b1420", font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._save_conn).pack(side="right")

    @staticmethod
    def _tag(box, name, color):
        """CTkTextbox прокидывает tag_config не во всех версиях — подстраховка."""
        fn = getattr(box, "tag_config", None) or box._textbox.tag_config  # noqa: SLF001
        fn(name, foreground=color)

    # ------------------------------------------------------------ обновление

    def _tick(self):
        self.worker.run(collect_snapshot, on_done=self._apply_snapshot,
                        on_error=lambda e: self._set_status(f"Ошибка чтения: {err_text(e)}"))
        self.after(REFRESH_MS, self._tick)

    def _apply_snapshot(self, rows: list[dict]):
        self.rows = rows
        names = [r["name"] for r in rows]

        # карточки пересоздаём только когда изменился состав списка
        if set(names) != set(self.cards):
            for card in self.cards.values():
                card.destroy()
            self.cards = {}
            for i, name in enumerate(names):
                card = AccountCard(self.list_frame, name, self._select)
                card.grid(row=i, column=0, sticky="ew", pady=4)
                self.cards[name] = card

        for row in rows:
            card = self.cards.get(row["name"])
            if card is None:
                continue
            card.update_state(row["running"],
                              row["status"].get("last_action") or "Не запущен")
            card.set_selected(row["name"] == self.current)

        if self.current not in names:
            self.current = names[0] if names else None
            self._settings_built_for = None

        self.lbl_refreshed.configure(
            text="обновлено " + datetime.now().strftime("%H:%M:%S"))
        self._render_current()

    def _row(self, name: str | None = None) -> dict | None:
        target = name or self.current
        return next((r for r in self.rows if r["name"] == target), None)

    def _select(self, name: str):
        if name == self.current:
            return
        self.current = name
        self._settings_built_for = None
        for n, card in self.cards.items():
            card.set_selected(n == name)
        self._render_current()
        self._refresh_logs()

    def _render_current(self):
        row = self._row()
        if row is None:
            self.h_name.configure(text="Нет аккаунтов")
            self.h_sub.configure(text="Добавь аккаунт кнопкой слева")
            self.h_lamp.configure(text_color=CLR["hint"])
            for b in (self.btn_start, self.btn_stop, self.btn_scan, self.btn_rescan,
                      self.btn_farm, self.btn_reset):
                b.configure(state="disabled")
            return

        running = row["running"]
        self.h_name.configure(text=row["name"])
        self.h_sub.configure(
            text=f"{row['server'] or '—'}   ·   {row['status'].get('last_action') or 'Не запущен'}")
        self.h_lamp.configure(text_color=CLR["pos"] if running else CLR["neg"])

        self.btn_start.configure(state="disabled" if running or self._busy else "normal")
        self.btn_stop.configure(state="normal" if running and not self._busy else "disabled")
        for b in (self.btn_scan, self.btn_rescan, self.btn_farm):
            b.configure(state="normal" if running and not self._busy else "disabled")
        self.btn_reset.configure(state="disabled" if self._busy else "normal")
        self.btn_del.configure(state="disabled" if row["from_yaml"] else "normal")

        self._render_overview(row)
        if self._settings_built_for != row["name"]:
            self._build_settings_widgets(row)
            self._build_order_widgets(row)
            self._fill_conn(row)
            self._settings_built_for = row["name"]

    # -------------------------------------------------------------- обзор

    def _render_overview(self, row: dict):
        stats = row.get("stats") or {}
        status = row.get("status") or {}
        lines: list[tuple[str, str]] = []

        def add(text="", tag=""):
            lines.append((text, tag))

        add("СОСТОЯНИЕ", "h")
        add(f"  Действие      {status.get('last_action') or 'Не запущен'}")
        add(f"  Деревня       {status.get('current_village') or '—'}")
        hb = status.get("last_heartbeat")
        add(f"  Heartbeat     {hb or '—'}", "dim")
        add()

        villages = stats.get("villages") or []
        if not villages and (stats.get("resources") or stats.get("build_queue")):
            villages = [{"name": row["name"],
                         "resources": stats.get("resources") or {},
                         "build_queue": stats.get("build_queue") or []}]

        for v in villages:
            add(f"ДЕРЕВНЯ: {v.get('name') or '—'}", "h")
            res = v.get("resources") or {}
            store = res.get("storage") or res
            add("  Дерево {:>10}   Глина {:>10}".format(
                fmt_num(store.get("wood") or store.get("lumber")), fmt_num(store.get("clay"))))
            add("  Железо {:>10}   Зерно {:>10}".format(
                fmt_num(store.get("iron")), fmt_num(store.get("crop"))))
            free = res.get("free_crop")
            if free is not None:
                tag = "neg" if _num_or(free, 0) <= 0 else ("warn" if _num_or(free, 0) < 10 else "ok")
                add(f"  Свободное зерно  {fmt_num(free)}", "err" if tag == "neg" else tag)
            queue = v.get("build_queue") or []
            if queue:
                add("  Стройка:", "dim")
                for b in queue:
                    lvl = f" до ур.{b.get('target_level')}" if b.get("target_level") else ""
                    left = fmt_dur(b.get("seconds")) or (b.get("timer") or "")
                    add(f"    · {b.get('name') or '?'}{lvl}  {left}")
            else:
                add("  Стройка: очередь пуста", "dim")
            add()

        acc = stats.get("account") or {}
        if acc:
            add("АККАУНТ", "h")
            if acc.get("gold") is not None:
                add(f"  Золото        {fmt_num(acc.get('gold'))}")
            if acc.get("silver") is not None:
                add(f"  Серебро       {fmt_num(acc.get('silver'))}")
            add(f"  Travian Plus  {'активен' if acc.get('premium') else 'нет'}",
                "ok" if acc.get("premium") else "dim")
            if acc.get("beginner_protection"):
                left = fmt_dur(acc.get("beginner_protection_seconds")) or "активна"
                add(f"  Защита новичка {left}", "ok")
            add()

        attacks = stats.get("attacks") or []
        add("ВХОДЯЩИЕ АТАКИ", "h")
        if attacks:
            for a in attacks:
                left = fmt_dur(a.get("seconds")) or (a.get("timer") or a.get("time") or "")
                add(f"  ⚔ {a.get('type') or a.get('name') or 'Атака'}   {left}", "err")
        else:
            add("  атак нет", "dim")
        add()

        farm = stats.get("farm") or {}
        totals = farm.get("totals") or {}
        if totals:
            add("ФАРМ", "h")
            add(f"  Набегов       {fmt_num(totals.get('raids'))}")
            add(f"  Добыча        {fmt_num(totals.get('loot'))}")
            add(f"  Потери войск  {fmt_num(totals.get('lost_value'))}", "warn")
            net = totals.get("net")
            add(f"  Чистый профит {fmt_num(net)}",
                "ok" if _num_or(net, 0) >= 0 else "err")

        self._write_lines(self.ov, lines)

    def _write_lines(self, box, lines: list[tuple[str, str]]):
        """Перерисовка с сохранением позиции скролла (иначе прыгает каждые 4 с)."""
        try:
            pos = box.yview()[0]
        except Exception:
            pos = 0.0
        box.configure(state="normal")
        box.delete("1.0", "end")
        for text, tag in lines:
            box.insert("end", text + "\n", tag or ())
        box.configure(state="disabled")
        try:
            box.yview_moveto(pos)
        except Exception:
            pass

    # ----------------------------------------------------------- настройки

    def _store(self, name: str):
        if name not in self._stores:
            self._stores[name] = get_store(name)
        return self._stores[name]

    def _build_settings_widgets(self, row: dict):
        for w in self.set_scroll.winfo_children():
            w.destroy()

        settings = (row.get("stats") and None) or self._store(row["name"]).get_all()
        feats = settings.get("features", {})
        self.v_feat: dict[str, ctk.BooleanVar] = {}
        self.v_num: dict[tuple[str, str], ctk.StringVar] = {}

        r = 0
        section_title(self.set_scroll, "Режим фарма", r, pady=(4, 6)); r += 1
        active = next((k for k, _l, _h in FARM_MODES if feats.get(k)), "farm_enabled")
        self.v_mode = ctk.StringVar(value=active)
        for key, label, hint in FARM_MODES:
            box = ctk.CTkFrame(self.set_scroll, fg_color="transparent")
            box.grid(row=r, column=0, sticky="ew", padx=4, pady=2)
            box.grid_columnconfigure(1, weight=1)
            ctk.CTkRadioButton(box, text="", value=key, variable=self.v_mode,
                               width=22, fg_color=CLR["accent"]).grid(row=0, column=0, rowspan=2)
            ctk.CTkLabel(box, text=label, anchor="w",
                         font=ctk.CTkFont(size=13)).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(box, text=hint, anchor="w", text_color=CLR["hint"],
                         font=ctk.CTkFont(size=11)).grid(row=1, column=1, sticky="w")
            r += 1

        section_title(self.set_scroll, "Модули", r); r += 1
        for key, label, hint in FEATURES:
            var = ctk.BooleanVar(value=bool(feats.get(key)))
            self.v_feat[key] = var
            switch_row(self.set_scroll, r, label, hint, var)
            r += 1

        section_title(self.set_scroll, "Ночной режим", r); r += 1
        night = settings.get("night", {})
        self.v_night_on = ctk.BooleanVar(value=night.get("enabled", True) is not False)
        switch_row(self.set_scroll, r, "Ночной режим включён",
                   "бот спит в этом окне", self.v_night_on); r += 1
        r = self._numeric_block("night", night, r)

        section_title(self.set_scroll, "Фарм", r); r += 1
        farm = settings.get("farm", {})
        self.v_tribe = ctk.StringVar(value=farm.get("tribe", "roman"))
        option_row(self.set_scroll, r, "Племя", self.v_tribe, TRIBES); r += 1
        r = self._numeric_block("farm", farm, r)

        section_title(self.set_scroll, "Тренировка войск", r); r += 1
        training = settings.get("training", {})
        self.v_building = ctk.StringVar(value=training.get("building", "barracks"))
        option_row(self.set_scroll, r, "Здание", self.v_building, BUILDINGS); r += 1
        r = self._numeric_block("training", training, r)

        section_title(self.set_scroll, "Торговля", r); r += 1
        self._numeric_block("trade", settings.get("trade", {}), r)

        self.set_msg.configure(text="")

    def _numeric_block(self, section: str, values: dict, row: int) -> int:
        for key, label, caster, lo, hi in NUM_SPEC[section]:
            raw = values.get(key)
            if raw is None:
                raw = 0 if caster is int else 0.0
            var = ctk.StringVar(value=str(raw))
            self.v_num[(section, key)] = var
            entry_row(self.set_scroll, row, f"{label}   ({lo}–{hi})", var)
            row += 1
        return row

    def _collect_settings(self) -> dict:
        feats = {k: bool(v.get()) for k, v in self.v_feat.items()}
        mode = self.v_mode.get()
        for key, _l, _h in FARM_MODES:
            feats[key] = (key == mode)

        payload: dict = {
            "features": feats,
            "night": {"enabled": bool(self.v_night_on.get())},
            "farm": {"tribe": self.v_tribe.get()},
            "training": {"building": self.v_building.get()},
            "trade": {},
        }
        for (section, key), var in self.v_num.items():
            caster = next(c for k, _l, c, _lo, _hi in NUM_SPEC[section] if k == key)
            text = var.get().strip().replace(",", ".")
            if text == "":
                continue
            try:
                payload.setdefault(section, {})[key] = caster(text)
            except ValueError:
                raise ValueError(f"{section}.{key}: «{var.get()}» — это не число")
        return payload

    def _save_settings(self):
        row = self._row()
        if row is None:
            return
        try:
            payload = validate_settings(self._collect_settings())
        except Exception as exc:  # noqa: BLE001
            self.set_msg.configure(text=err_text(exc), text_color=CLR["neg"])
            return
        name = row["name"]
        self.set_msg.configure(text="Сохранение…", text_color=CLR["hint"])
        self.worker.run(
            lambda: self._store(name).save(payload),
            on_done=lambda _r: self.set_msg.configure(text="Сохранено", text_color=CLR["pos"]),
            on_error=lambda e: self.set_msg.configure(text=err_text(e), text_color=CLR["neg"]),
        )

    # ------------------------------------------------------- порядок задач

    def _build_order_widgets(self, row: dict):
        settings = self._store(row["name"]).get_all()
        order = list((settings.get("task_order") or {}).get("order") or [])
        for key in TASK_LABELS:
            if key not in order:
                order.append(key)
        self._task_order = [k for k in order if k in TASK_LABELS]
        self._redraw_order()

    def _redraw_order(self):
        for w in self.order_frame.winfo_children():
            w.destroy()
        for i, key in enumerate(self._task_order):
            box = ctk.CTkFrame(self.order_frame, fg_color=CLR["panel2"], corner_radius=10)
            box.grid(row=i, column=0, sticky="ew", pady=3)
            box.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(box, text=f"{i + 1}", width=28, text_color=CLR["hint"],
                         font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(12, 4), pady=8)
            ctk.CTkLabel(box, text=TASK_LABELS[key], anchor="w",
                         font=ctk.CTkFont(size=13)).grid(row=0, column=1, sticky="ew")
            ctk.CTkButton(box, text="▲", width=38, fg_color=CLR["panel"],
                          hover_color=CLR["accent"],
                          command=lambda k=key: self._move_task(k, -1)
                          ).grid(row=0, column=2, padx=2, pady=6)
            ctk.CTkButton(box, text="▼", width=38, fg_color=CLR["panel"],
                          hover_color=CLR["accent"],
                          command=lambda k=key: self._move_task(k, 1)
                          ).grid(row=0, column=3, padx=(2, 10), pady=6)

    def _move_task(self, key: str, delta: int):
        i = self._task_order.index(key)
        j = i + delta
        if not 0 <= j < len(self._task_order):
            return
        self._task_order[i], self._task_order[j] = self._task_order[j], self._task_order[i]
        self._redraw_order()

    def _save_order(self):
        row = self._row()
        if row is None:
            return
        name = row["name"]
        payload = {"task_order": {"order": list(self._task_order)}}
        self.order_msg.configure(text="Сохранение…", text_color=CLR["hint"])
        self.worker.run(
            lambda: self._store(name).save(payload),
            on_done=lambda _r: self.order_msg.configure(text="Сохранено", text_color=CLR["pos"]),
            on_error=lambda e: self.order_msg.configure(text=err_text(e), text_color=CLR["neg"]),
        )

    # -------------------------------------------------------- подключение

    def _fill_conn(self, row: dict):
        self.c_server.set(row["server"])
        self.c_email.set(row["email"])
        self.c_pass.set("")
        self.c_rate.set(str(row["rate"]))
        self.c_proxy.set(row["proxy"])
        self.c_headless.set(bool(row["headless"]))
        self.c_tpl.set(row["build_template"] if row["build_template"] in BUILD_TEMPLATES else "x3")
        self.c_note.configure(
            text=("Аккаунт объявлен в config.yaml. Правки из окна сохранятся в "
                  "accounts_gui.json и перекроют YAML, сам файл не изменится.")
            if row["from_yaml"] else "")
        self.c_msg.configure(text="")

    def _save_conn(self):
        row = self._row()
        if row is None:
            return
        try:
            rate = int(self.c_rate.get().strip())
        except ValueError:
            self.c_msg.configure(text="rate: ожидается целое число", text_color=CLR["neg"])
            return

        data = {
            "name": row["name"],
            "server": self.c_server.get().strip().replace("https://", "")
                        .replace("http://", "").strip("/"),
            "rate": rate,
            "headless": bool(self.c_headless.get()),
            "proxy": self.c_proxy.get().strip(),
            "build_template": self.c_tpl.get(),
        }
        # Пустой email/пароль = «не менять». Прокси, наоборот, очищаем осознанно.
        if self.c_email.get().strip():
            data["email"] = self.c_email.get().strip()
        if self.c_pass.get().strip():
            data["password"] = self.c_pass.get().strip()

        self.c_msg.configure(text="Сохранение…", text_color=CLR["hint"])
        self.worker.run(
            lambda: upsert_gui_account(data),
            on_done=lambda _r: (self.c_msg.configure(text="Сохранено", text_color=CLR["pos"]),
                                self.c_pass.set("")),
            on_error=lambda e: self.c_msg.configure(text=err_text(e), text_color=CLR["neg"]),
        )

    def _add_account(self):
        AccountDialog(self, on_saved=self._after_add)

    def _after_add(self, name: str):
        self._set_status(f"Аккаунт «{name}» создан")
        self.current = name
        self._settings_built_for = None
        self._tick_once()

    def _delete_account(self):
        row = self._row()
        if row is None or row["from_yaml"]:
            return
        if not messagebox.askyesno(
                "Удалить аккаунт",
                f"Удалить «{row['name']}» из accounts_gui.json?\n"
                f"Файлы в data/{row['name']}/ останутся на диске."):
            return
        name = row["name"]

        def job():
            if proc_running(name):
                stop_account(name)
            return delete_gui_account(name)

        self.worker.run(job, on_done=lambda _r: (self._stores.pop(name, None),
                                                 self._set_status(f"Аккаунт «{name}» удалён"),
                                                 self._tick_once()))

    # ------------------------------------------------------------ действия

    def _guard(self):
        """Блокирует кнопки на время операции — двойной клик ломал стоп/старт."""
        self._busy = True
        self._render_current()

    def _release(self, message: str = ""):
        self._busy = False
        if message:
            self._set_status(message)
        self._tick_once()

    def _tick_once(self):
        self.worker.run(collect_snapshot, on_done=self._apply_snapshot)

    def _start(self):
        row = self._row()
        if row is None:
            return
        name = row["name"]
        self._guard()
        self._set_status(f"Запускаю «{name}»…")
        self.worker.run(lambda: start_account(name),
                        on_done=lambda _r: self._release(f"«{name}» запущен"),
                        on_error=lambda e: (self._release(), Worker._show(e)))

    def _stop(self):
        row = self._row()
        if row is None:
            return
        name = row["name"]
        self._guard()
        self._set_status(f"Останавливаю «{name}»…")
        self.worker.run(lambda: stop_account(name),
                        on_done=lambda _r: self._release(f"«{name}» остановлен"),
                        on_error=lambda e: (self._release(), Worker._show(e)))

    def _command(self, action: str):
        row = self._row()
        if row is None:
            return
        name = row["name"]
        titles = {"scan": "Полный скан", "rescan": "Перескан", "force_farm": "Фарм"}

        def job():
            if not push_command(name, action):
                raise RuntimeError("Не удалось поставить команду в очередь")
            return True

        self.worker.run(job,
                        on_done=lambda _r: self._set_status(
                            f"{titles.get(action, action)}: команда поставлена в очередь"))

    def _reset_build(self):
        row = self._row()
        if row is None:
            return
        name = row["name"]
        if not messagebox.askyesno("Сброс стройки",
                                   f"Сбросить прогресс застройки «{name}» на шаг 1 "
                                   f"для всех деревень?"):
            return
        # Прогресс — это просто {village_key: step}. Пустой объект = начать заново.
        self.worker.run(
            lambda: write_json(account_file(name, "build_progress"), {}),
            on_done=lambda _r: self._set_status("Прогресс застройки сброшен"))

    # ---------------------------------------------------------------- логи

    def _log_tick(self):
        if self.v_autolog.get() and self.tabs.get() == "Логи":
            self._refresh_logs()
        self.after(LOG_REFRESH_MS, self._log_tick)

    def _refresh_logs(self):
        row = self._row()
        if row is None:
            return
        name = row["name"]
        try:
            lines = int(self.v_lines.get())
        except ValueError:
            lines = 200
        self.worker.run(lambda: get_last_logs(name, lines), on_done=self._render_logs)

    def _render_logs(self, log_lines: list[str]):
        rendered = []
        for line in log_lines:
            low = line.lower()
            if "error" in low or "ошибк" in low or "❌" in line:
                tag = "err"
            elif "warning" in low or "предупр" in low or "⚠" in line:
                tag = "warn"
            elif "✅" in line or "успеш" in low:
                tag = "ok"
            else:
                tag = ""
            rendered.append((line, tag))
        if not rendered:
            rendered = [("Лог пуст", "")]

        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        for text, tag in rendered:
            self.logbox.insert("end", text + "\n", tag or ())
        self.logbox.configure(state="disabled")
        self.logbox.see("end")

    def _open_log_file(self):
        row = self._row()
        if row is None:
            return
        path = log_file(row["name"], datetime.now().strftime("%Y-%m-%d"))
        if not path.exists():
            self._set_status("Файл лога за сегодня ещё не создан")
            return
        webbrowser.open(path.as_uri())

    # -------------------------------------------------------------- прочее

    def _set_status(self, text: str):
        self.status.configure(text=text)

    def _on_close(self):
        import app  # локальный импорт: нужен только здесь
        managed = [n for n, p in app._processes.items() if p.poll() is None]  # noqa: SLF001
        if managed:
            answer = messagebox.askyesnocancel(
                "Выход",
                "Запущены боты: " + ", ".join(managed) + "\n\n"
                "Остановить их перед выходом?\n"
                "«Нет» — оставить работать в фоне.")
            if answer is None:
                return
            if answer:
                for name in managed:
                    try:
                        stop_account(name)
                    except Exception:  # noqa: BLE001
                        pass
        self.destroy()


def _num_or(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    TravianGUI().mainloop()


if __name__ == "__main__":
    main()
