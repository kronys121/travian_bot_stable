"""Главное окно десктопной панели."""
from __future__ import annotations

import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

from app import get_last_logs, start_account, stop_account
from utils.accounts import (
    delete_gui_account,
    is_yaml_account,
    upsert_gui_account,
)
from utils.commands import push_command
from utils.jsonio import write_json
from utils.paths import account_file, is_valid_account_name

from .model import (
    DEFAULT_PORT,
    LOG_REFRESH_MS,
    REFRESH_MS,
    TASK_LABELS,
    WebServer,
    Worker,
    collect_snapshot,
    err_text,
    fmt_num,
    fmt_time,
    num_or,
)
from .pages import OrderPage, SettingsPage
from .theme import C, F, init_fonts, init_ttk
from .widgets import Button, Card, Dot, ScrollArea, Switch, label

TABS = [
    ("overview", "Сводка"),
    ("settings", "Настройки"),
    ("order", "Порядок задач"),
    ("logs", "Логи"),
    ("conn", "Подключение"),
    ("web", "Веб-панель"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        init_fonts()
        init_ttk(self)

        self.title("Travian Bot")
        self.geometry("1180x760")
        self.minsize(940, 620)
        self.configure(bg=C.bg)

        self.snapshot: list[dict] = []
        self.selected: str | None = None
        self.web = WebServer(DEFAULT_PORT)
        self._toast_after: str | None = None
        self._busy = False

        self._build_sidebar()
        self._build_main()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh()
        self.after(REFRESH_MS, self._tick)
        self.after(LOG_REFRESH_MS, self._tick_logs)

    # ------------------------------------------------------------------ сервис
    @property
    def current(self) -> dict | None:
        for entry in self.snapshot:
            if entry["name"] == self.selected:
                return entry
        return None

    def run_bg(self, fn, on_done=None, on_error=None) -> None:
        Worker(self, fn, on_done, on_error).start()

    def toast(self, text: str, kind: str = "ok") -> None:
        colors = {"ok": C.ok, "err": C.err, "warn": C.warn, "info": C.dim}
        self.toast_label.configure(text=text, fg=colors.get(kind, C.dim))
        if self._toast_after:
            self.after_cancel(self._toast_after)
        self._toast_after = self.after(6000, lambda: self.toast_label.configure(text=""))

    def after_save(self, text: str) -> None:
        self.toast(text, "ok")
        self.refresh()

    # ----------------------------------------------------------------- боковая
    def _build_sidebar(self) -> None:
        side = tk.Frame(self, bg=C.sidebar, width=232)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        head = tk.Frame(side, bg=C.sidebar)
        head.pack(fill="x", padx=18, pady=(18, 10))
        label(head, "Travian Bot", font=F.h1, bg=C.sidebar).pack(anchor="w")
        label(head, "локальная панель", font=F.small, fg=C.faint,
              bg=C.sidebar).pack(anchor="w")

        self.accounts_area = ScrollArea(side, bg=C.sidebar)
        self.accounts_area.pack(fill="both", expand=True, padx=8)

        foot = tk.Frame(side, bg=C.sidebar)
        foot.pack(fill="x", padx=14, pady=14)
        Button(foot, "+  Добавить аккаунт", self._add_account,
               kind="ghost", bg=C.sidebar).pack(fill="x")
        Button(foot, "Открыть веб-панель", lambda: self._show_tab("web"),
               kind="quiet", bg=C.sidebar).pack(fill="x", pady=(6, 0))

    def _render_accounts(self) -> None:
        body = self.accounts_area.body
        for child in body.winfo_children():
            child.destroy()

        if not self.snapshot:
            label(body, "Аккаунтов пока нет", font=F.small, fg=C.faint,
                  bg=C.sidebar).pack(anchor="w", padx=10, pady=10)
            return

        for entry in self.snapshot:
            name = entry["name"]
            active = name == self.selected
            bg = C.surface2 if active else C.sidebar
            row = tk.Frame(body, bg=bg, cursor="hand2")
            row.pack(fill="x", pady=1)

            dot = Dot(row, bg=bg)
            dot.pack(side="left", padx=(10, 8), pady=11)
            dot.set_color(C.ok if entry["alive"]
                          else (C.warn if entry["running"] else C.faint))

            text = label(row, name, bg=bg,
                         fg=C.text if active else C.dim,
                         font=F.bold if active else F.ui)
            text.pack(side="left", fill="x", expand=True, pady=9)

            for w in (row, text, dot):
                w.bind("<Button-1>", lambda _e, n=name: self._select(n))

    def _select(self, name: str) -> None:
        if name == self.selected:
            return
        self.selected = name
        self.settings_page._loaded_for = None
        self.order_page._loaded_for = None
        self.logs_text.configure(state="normal")
        self.logs_text.delete("1.0", "end")
        self.logs_text.configure(state="disabled")
        self._conn_loaded_for = None
        self._render_accounts()
        self._render_current()

    # ------------------------------------------------------------------- шапка
    def _build_main(self) -> None:
        main = tk.Frame(self, bg=C.bg)
        main.pack(side="left", fill="both", expand=True)

        header = tk.Frame(main, bg=C.bg)
        header.pack(fill="x", padx=18, pady=(16, 6))

        title_row = tk.Frame(header, bg=C.bg)
        title_row.pack(fill="x")
        self.header_dot = Dot(title_row, size=10, bg=C.bg)
        self.header_dot.pack(side="left", pady=6)
        self.header_title = label(title_row, "Аккаунт не выбран", font=F.h1, bg=C.bg)
        self.header_title.pack(side="left", padx=10)
        self.header_state = label(title_row, "", font=F.small, fg=C.faint, bg=C.bg)
        self.header_state.pack(side="left")

        actions = tk.Frame(header, bg=C.bg)
        actions.pack(fill="x", pady=(10, 0))
        self.btn_start = Button(actions, "▶  Старт", self._start, kind="primary")
        self.btn_start.pack(side="left")
        self.btn_stop = Button(actions, "■  Стоп", self._stop, kind="danger")
        self.btn_stop.pack(side="left", padx=6)
        for text, action in (("Полный скан", "scan"),
                             ("Перескан", "rescan"),
                             ("Фарм сейчас", "force_farm")):
            Button(actions, text, lambda a=action: self._command(a),
                   kind="ghost").pack(side="left", padx=(0, 6))
        Button(actions, "Сброс стройки", self._reset_build,
               kind="quiet").pack(side="left")
        self.toast_label = label(actions, "", font=F.small, bg=C.bg)
        self.toast_label.pack(side="right")

        tabbar = tk.Frame(main, bg=C.bg)
        tabbar.pack(fill="x", padx=18, pady=(14, 0))
        self.tab_buttons: dict[str, tk.Label] = {}
        for key, text in TABS:
            holder = tk.Frame(tabbar, bg=C.bg)
            holder.pack(side="left", padx=(0, 4))
            lbl = tk.Label(holder, text=text, font=F.ui, bg=C.bg, fg=C.dim,
                           padx=14, pady=7, cursor="hand2")
            lbl.pack()
            # Подчёркивание — отдельный Frame в 2px: менять ему цвет дешевле,
            # чем пересобирать вкладки.
            underline = tk.Frame(holder, bg=C.bg, height=2)
            underline.pack(fill="x")
            lbl.bind("<Button-1>", lambda _e, k=key: self._show_tab(k))
            self.tab_buttons[key] = (lbl, underline)

        tk.Frame(main, bg=C.line, height=1).pack(fill="x", padx=18)

        self.pages_holder = tk.Frame(main, bg=C.bg)
        self.pages_holder.pack(fill="both", expand=True)

        self.pages = {
            "overview": self._build_overview(),
            "settings": SettingsPage(self.pages_holder, self),
            "order": OrderPage(self.pages_holder, self),
            "logs": self._build_logs(),
            "conn": self._build_conn(),
            "web": self._build_web(),
        }
        self.settings_page = self.pages["settings"]
        self.order_page = self.pages["order"]
        self.tab = "overview"
        self._show_tab("overview")

    def _show_tab(self, key: str) -> None:
        self.tab = key
        for k, (lbl, underline) in self.tab_buttons.items():
            on = k == key
            lbl.configure(fg=C.text if on else C.dim, font=F.bold if on else F.ui)
            underline.configure(bg=C.accent if on else C.bg)
        for k, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        self._render_current()

    # ----------------------------------------------------------------- СВОДКА
    def _build_overview(self) -> tk.Frame:
        page = tk.Frame(self.pages_holder, bg=C.bg)
        card = Card(page)
        card.pack(fill="both", expand=True, padx=18, pady=16)
        self.overview_text = tk.Text(
            card, bg=C.surface, fg=C.text, font=F.ui, bd=0, highlightthickness=0,
            padx=18, pady=16, wrap="word", spacing1=2, spacing3=2, cursor="arrow")
        self.overview_text.pack(fill="both", expand=True)
        self.overview_text.configure(state="disabled")
        for tag, cfg in {
            "h": {"font": F.h2, "foreground": C.text, "spacing1": 14, "spacing3": 6},
            "k": {"foreground": C.dim},
            "v": {"font": F.bold, "foreground": C.text},
            "ok": {"font": F.bold, "foreground": C.ok},
            "warn": {"font": F.bold, "foreground": C.warn},
            "err": {"font": F.bold, "foreground": C.err},
            "dim": {"font": F.small, "foreground": C.faint},
        }.items():
            self.overview_text.tag_configure(tag, **cfg)
        return page

    def _render_overview(self, entry: dict | None) -> None:
        t = self.overview_text
        t.configure(state="normal")
        t.delete("1.0", "end")

        if not entry:
            t.insert("end", "Выберите аккаунт слева или добавьте новый.\n", "dim")
            t.configure(state="disabled")
            return

        status = entry.get("status") or {}
        stats = entry.get("stats") or {}
        acc = entry.get("account") or {}

        def row(key: str, value: str, tag: str = "v") -> None:
            t.insert("end", f"{key}\n", "k")
            t.insert("end", f"{value}\n", tag)

        t.insert("end", "Состояние\n", "h")
        if entry["alive"]:
            row("Бот", "Работает", "ok")
        elif entry["running"]:
            # Процесс жив, но heartbeat старше 5 минут — обычно зависший браузер.
            row("Бот", "Процесс жив, но не отчитывается", "warn")
        else:
            row("Бот", "Остановлен", "dim")

        row("Текущая задача",
            TASK_LABELS.get(str(status.get("task", "")), str(status.get("task") or "—")))
        row("Последний сигнал", fmt_time(status.get("heartbeat")))
        if status.get("error"):
            row("Ошибка", str(status["error"]), "err")

        t.insert("end", "Ресурсы\n", "h")
        res = status.get("resources") or stats.get("resources") or {}
        if isinstance(res, dict) and res:
            parts = [f"{name}: {fmt_num(value)}" for name, value in res.items()]
            t.insert("end", "    ".join(parts) + "\n", "v")
        else:
            t.insert("end", "Нет данных — бот ещё не собирал статистику\n", "dim")

        t.insert("end", "Фарм\n", "h")
        farm = stats.get("farm") or {}
        row("Набегов всего", fmt_num(farm.get("raids", stats.get("raids"))))
        row("Добыча", fmt_num(farm.get("loot", stats.get("loot"))))

        t.insert("end", "Аккаунт\n", "h")
        row("Источник", "config.yaml" if is_yaml_account(entry["name"])
            else "accounts_gui.json")
        row("Скорость сервера", f"x{acc.get('rate', '?')}")
        row("Фоновый режим", "вкл" if acc.get("headless") else "выкл (окно браузера)")
        row("Прокси", str(acc.get("proxy") or "не используется"))

        t.configure(state="disabled")

    # ------------------------------------------------------------------- ЛОГИ
    def _build_logs(self) -> tk.Frame:
        page = tk.Frame(self.pages_holder, bg=C.bg)
        bar = tk.Frame(page, bg=C.bg)
        bar.pack(fill="x", padx=18, pady=(14, 6))
        self.logs_auto = Switch(bar, value=True, bg=C.bg)
        self.logs_auto.pack(side="left")
        label(bar, "Автообновление", font=F.small, fg=C.dim,
              bg=C.bg).pack(side="left", padx=8)
        Button(bar, "Обновить", self._load_logs, kind="ghost").pack(side="right")

        card = Card(page)
        card.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        wrap = tk.Frame(card, bg=C.surface)
        wrap.pack(fill="both", expand=True)
        self.logs_text = tk.Text(wrap, bg=C.surface, fg=C.dim, font=F.mono, bd=0,
                                 highlightthickness=0, padx=14, pady=12, wrap="none")
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.logs_text.yview,
                               style="Dark.Vertical.TScrollbar")
        self.logs_text.configure(yscrollcommand=scroll.set, state="disabled")
        self.logs_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return page

    def _load_logs(self) -> None:
        entry = self.current
        if not entry:
            return
        name = entry["name"]
        self.run_bg(
            lambda: get_last_logs(name),
            on_done=self._show_logs,
            on_error=lambda e: self.toast(err_text(e), "err"),
        )

    def _show_logs(self, lines) -> None:
        if isinstance(lines, (list, tuple)):
            text = "\n".join(str(x) for x in lines)
        else:
            text = str(lines or "")
        widget = self.logs_text
        # Автоскролл только если пользователь и так внизу: иначе чтение
        # старых строк будет обрываться каждые три секунды.
        at_bottom = widget.yview()[1] > 0.999
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text or "Логов пока нет")
        widget.configure(state="disabled")
        if at_bottom:
            widget.see("end")

    # ------------------------------------------------------------- ПОДКЛЮЧЕНИЕ
    def _build_conn(self) -> tk.Frame:
        page = tk.Frame(self.pages_holder, bg=C.bg)
        self._conn_loaded_for: str | None = None
        self.conn_vars = {k: tk.StringVar() for k in
                          ("login", "password", "proxy", "rate", "sleep_from", "sleep_to")}

        area = ScrollArea(page)
        area.pack(fill="both", expand=True, padx=12, pady=12)
        card = Card(area.body)
        card.pack(fill="x", padx=6, pady=6)
        inner = tk.Frame(card, bg=C.surface)
        inner.pack(fill="x", padx=16, pady=16)

        self.conn_note = label(inner, "", font=F.small, fg=C.warn, bg=C.surface)
        self.conn_note.pack(anchor="w", pady=(0, 10))

        def field(text: str, key: str, hint: str = "", show: str | None = None):
            label(inner, text, font=F.small, fg=C.dim, bg=C.surface).pack(
                anchor="w", pady=(8, 3))
            ttk.Entry(inner, textvariable=self.conn_vars[key], style="Dark.TEntry",
                      font=F.ui, show=show or "").pack(fill="x")
            if hint:
                label(inner, hint, font=F.small, fg=C.faint, bg=C.surface).pack(anchor="w")

        field("Логин", "login")
        field("Пароль", "password", "Пустое поле — оставить текущий", show="\u2022")
        field("Прокси", "proxy", "socks5://user:pass@host:port или пусто")
        field("Скорость сервера", "rate", "1, 2, 3, 5, 10…")

        night = tk.Frame(inner, bg=C.surface)
        night.pack(fill="x", pady=(10, 0))
        night.columnconfigure(0, weight=1)
        night.columnconfigure(1, weight=1)
        for col, (text, key) in enumerate((("Сон с (час)", "sleep_from"),
                                           ("Сон до (час)", "sleep_to"))):
            box = tk.Frame(night, bg=C.surface)
            box.grid(row=0, column=col, sticky="ew", padx=(0, 8) if col == 0 else 0)
            label(box, text, font=F.small, fg=C.dim, bg=C.surface).pack(anchor="w")
            ttk.Entry(box, textvariable=self.conn_vars[key], style="Dark.TEntry",
                      font=F.ui).pack(fill="x", pady=(3, 0))

        row = tk.Frame(inner, bg=C.surface)
        row.pack(fill="x", pady=(14, 0))
        label(row, "Фоновый режим (без окна браузера)", bg=C.surface).pack(side="left")
        self.conn_headless = Switch(row, bg=C.surface)
        self.conn_headless.pack(side="right")

        buttons = tk.Frame(inner, bg=C.surface)
        buttons.pack(fill="x", pady=(18, 0))
        Button(buttons, "Сохранить", self._save_conn, kind="primary",
               bg=C.surface).pack(side="left")
        Button(buttons, "Удалить аккаунт", self._delete_account, kind="danger",
               bg=C.surface).pack(side="right")
        return page

    def _load_conn(self, entry: dict) -> None:
        if self._conn_loaded_for == entry["name"]:
            return
        self._conn_loaded_for = entry["name"]
        acc = entry.get("account") or {}
        sleep = acc.get("sleep_hours") or [2, 8]
        self.conn_vars["login"].set(str(acc.get("login", "")))
        self.conn_vars["password"].set("")
        self.conn_vars["proxy"].set(str(acc.get("proxy") or ""))
        self.conn_vars["rate"].set(str(acc.get("rate", 3)))
        self.conn_vars["sleep_from"].set(str(sleep[0] if len(sleep) > 0 else 2))
        self.conn_vars["sleep_to"].set(str(sleep[1] if len(sleep) > 1 else 8))
        self.conn_headless.set(bool(acc.get("headless", True)))

        yaml_based = is_yaml_account(entry["name"])
        self.conn_note.configure(
            text=("Аккаунт описан в config.yaml — правьте его там, отсюда не сохранится"
                  if yaml_based else ""))

    def _save_conn(self) -> None:
        entry = self.current
        if not entry:
            return
        name = entry["name"]
        if is_yaml_account(name):
            self.toast("Этот аккаунт живёт в config.yaml", "warn")
            return

        acc = dict(entry.get("account") or {})
        acc["name"] = name
        acc["login"] = self.conn_vars["login"].get().strip()
        password = self.conn_vars["password"].get()
        if password:
            acc["password"] = password
        acc["proxy"] = self.conn_vars["proxy"].get().strip()
        acc["rate"] = num_or(self.conn_vars["rate"].get(), 3)
        acc["headless"] = self.conn_headless.get()
        acc["sleep_hours"] = [num_or(self.conn_vars["sleep_from"].get(), 2),
                              num_or(self.conn_vars["sleep_to"].get(), 8)]

        self.run_bg(
            lambda: upsert_gui_account(acc),
            on_done=lambda _r: self.after_save("Аккаунт сохранён"),
            on_error=lambda e: self.toast(err_text(e), "err"),
        )

    def _delete_account(self) -> None:
        entry = self.current
        if not entry:
            return
        name = entry["name"]
        if not messagebox.askyesno(
                "Удаление", f"Удалить аккаунт «{name}» из списка?", parent=self):
            return

        def work():
            stop_account(name)
            delete_gui_account(name)

        def done(_r):
            self.selected = None
            self.after_save("Аккаунт удалён")

        self.run_bg(work, on_done=done,
                    on_error=lambda e: self.toast(err_text(e), "err"))

    # -------------------------------------------------------------- ВЕБ-ПАНЕЛЬ
    def _build_web(self) -> tk.Frame:
        page = tk.Frame(self.pages_holder, bg=C.bg)
        card = Card(page)
        card.pack(fill="x", padx=18, pady=16)
        inner = tk.Frame(card, bg=C.surface)
        inner.pack(fill="x", padx=18, pady=18)

        label(inner, "Веб-панель", font=F.h2, bg=C.surface).pack(anchor="w")
        label(inner, "Тот же бот в браузере. Сервер слушает только 127.0.0.1, "
                     "то есть доступен только с этого компьютера.",
              font=F.small, fg=C.faint, bg=C.surface).pack(anchor="w", pady=(4, 14))

        row = tk.Frame(inner, bg=C.surface)
        row.pack(fill="x")
        label(row, "Порт", font=F.small, fg=C.dim, bg=C.surface).pack(side="left")
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(row, textvariable=self.port_var, style="Dark.TEntry", font=F.ui,
                  width=8).pack(side="left", padx=10)

        state = tk.Frame(inner, bg=C.surface)
        state.pack(fill="x", pady=(16, 0))
        self.web_dot = Dot(state, size=9, bg=C.surface)
        self.web_dot.pack(side="left")
        self.web_state = label(state, "Остановлен", fg=C.dim, bg=C.surface)
        self.web_state.pack(side="left", padx=8)

        buttons = tk.Frame(inner, bg=C.surface)
        buttons.pack(fill="x", pady=(16, 0))
        self.btn_web_start = Button(buttons, "Запустить сервер", self._web_start,
                                    kind="primary", bg=C.surface)
        self.btn_web_start.pack(side="left")
        self.btn_web_stop = Button(buttons, "Остановить", self._web_stop,
                                   kind="danger", bg=C.surface)
        self.btn_web_stop.pack(side="left", padx=6)
        Button(buttons, "Открыть в браузере", self._web_open, kind="ghost",
               bg=C.surface).pack(side="left")

        label(inner, "Команда, которая запускается", font=F.small, fg=C.dim,
              bg=C.surface).pack(anchor="w", pady=(20, 4))
        self.web_cmd = label(inner, "", font=F.mono, fg=C.dim, bg=C.surface2)
        self.web_cmd.pack(anchor="w", fill="x", ipadx=10, ipady=8)
        return page

    def _render_web(self) -> None:
        port = num_or(self.port_var.get(), DEFAULT_PORT)
        self.web_cmd.configure(text="  " + self.web.command_text(port))
        running = self.web.running()
        self.web_dot.set_color(C.ok if running else C.faint)
        self.web_state.configure(
            text=f"Работает — {self.web.url}" if running else "Остановлен",
            fg=C.ok if running else C.dim)
        self.btn_web_start.set_enabled(not running)
        self.btn_web_stop.set_enabled(running)

    def _web_start(self) -> None:
        port = num_or(self.port_var.get(), 0)
        if not (1 <= port <= 65535):
            self.toast("Порт должен быть числом от 1 до 65535", "err")
            return

        def done(_r):
            self.toast(f"Сервер запущен на {self.web.url}", "ok")
            self._render_web()
            # uvicorn поднимается не мгновенно; без паузы браузер покажет
            # «не удалось подключиться» на ровном месте.
            self.after(1500, self._web_open)

        self.run_bg(lambda: self.web.start(port), on_done=done,
                    on_error=lambda e: self.toast(err_text(e), "err"))

    def _web_stop(self) -> None:
        self.run_bg(self.web.stop,
                    on_done=lambda _r: (self.toast("Сервер остановлен", "info"),
                                        self._render_web()),
                    on_error=lambda e: self.toast(err_text(e), "err"))

    def _web_open(self) -> None:
        if not self.web.running():
            self.toast("Сначала запустите сервер", "warn")
            return
        webbrowser.open(self.web.url)

    # ---------------------------------------------------------------- ДЕЙСТВИЯ
    def _start(self) -> None:
        entry = self.current
        if not entry:
            return
        name = entry["name"]
        self.run_bg(lambda: start_account(name),
                    on_done=lambda _r: self.after_save(f"Бот «{name}» запущен"),
                    on_error=lambda e: self.toast(err_text(e), "err"))

    def _stop(self) -> None:
        entry = self.current
        if not entry:
            return
        name = entry["name"]
        self.run_bg(lambda: stop_account(name),
                    on_done=lambda _r: self.after_save(f"Бот «{name}» остановлен"),
                    on_error=lambda e: self.toast(err_text(e), "err"))

    def _command(self, action: str) -> None:
        entry = self.current
        if not entry:
            return
        if not entry["running"]:
            self.toast("Бот остановлен — команду некому выполнять", "warn")
            return
        name = entry["name"]
        labels = {"scan": "Полный скан", "rescan": "Перескан", "force_farm": "Фарм"}

        def done(ok):
            if ok:
                self.toast(f"{labels.get(action, action)}: команда поставлена в очередь", "ok")
            else:
                self.toast("Команда отклонена", "err")

        self.run_bg(lambda: push_command(name, action), on_done=done,
                    on_error=lambda e: self.toast(err_text(e), "err"))

    def _reset_build(self) -> None:
        entry = self.current
        if not entry:
            return
        name = entry["name"]
        if not messagebox.askyesno(
                "Сброс стройки",
                "Очистить прогресс строительства?\n"
                "Бот начнёт выполнять план с начала.", parent=self):
            return
        self.run_bg(
            lambda: write_json(account_file(name, "build_progress"), {}),
            on_done=lambda _r: self.after_save("Прогресс стройки сброшен"),
            on_error=lambda e: self.toast(err_text(e), "err"))

    def _add_account(self) -> None:
        AccountDialog(self)

    # ------------------------------------------------------------------ ОБНОВЛЕНИЕ
    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True

        def done(snapshot):
            self._busy = False
            self.snapshot = snapshot
            if self.selected not in {e["name"] for e in snapshot}:
                self.selected = snapshot[0]["name"] if snapshot else None
            self._render_accounts()
            self._render_current()

        def failed(exc):
            self._busy = False
            self.toast(err_text(exc), "err")

        self.run_bg(collect_snapshot, on_done=done, on_error=failed)

    def _render_current(self) -> None:
        entry = self.current

        if entry:
            self.header_title.configure(text=entry["name"])
            if entry["alive"]:
                self.header_dot.set_color(C.ok)
                self.header_state.configure(text="работает", fg=C.ok)
            elif entry["running"]:
                self.header_dot.set_color(C.warn)
                self.header_state.configure(text="нет сигнала", fg=C.warn)
            else:
                self.header_dot.set_color(C.faint)
                self.header_state.configure(text="остановлен", fg=C.faint)
            self.btn_start.set_enabled(not entry["running"])
            self.btn_stop.set_enabled(entry["running"])
        else:
            self.header_title.configure(text="Аккаунт не выбран")
            self.header_state.configure(text="")
            self.header_dot.set_color(C.faint)
            self.btn_start.set_enabled(False)
            self.btn_stop.set_enabled(False)

        if self.tab == "overview":
            self._render_overview(entry)
        elif self.tab == "settings" and entry:
            self.settings_page.load()
        elif self.tab == "order" and entry:
            self.order_page.load()
        elif self.tab == "conn" and entry:
            self._load_conn(entry)
        elif self.tab == "web":
            self._render_web()

    def _tick(self) -> None:
        self.refresh()
        self.after(REFRESH_MS, self._tick)

    def _tick_logs(self) -> None:
        if self.tab == "logs" and self.current and self.logs_auto.get():
            self._load_logs()
        self.after(LOG_REFRESH_MS, self._tick_logs)

    def _on_close(self) -> None:
        if self.web.running() and not messagebox.askyesno(
                "Выход", "Веб-панель ещё работает. Остановить её и выйти?",
                parent=self):
            return
        # Сами боты не трогаем: это отдельные процессы с pid-файлами,
            # и закрытие окна не должно их убивать.
        self.web.stop()
        self.destroy()


class AccountDialog(tk.Toplevel):
    """Модальное окно добавления аккаунта."""

    def __init__(self, app: App):
        super().__init__(app, bg=C.bg)
        self.app = app
        self.title("Новый аккаунт")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        self.vars = {k: tk.StringVar() for k in ("name", "login", "password", "proxy", "rate")}
        self.vars["rate"].set("3")

        box = tk.Frame(self, bg=C.bg)
        box.pack(fill="both", expand=True, padx=22, pady=20)
        label(box, "Новый аккаунт", font=F.h2, bg=C.bg).pack(anchor="w", pady=(0, 4))
        label(box, "Имя станет именем папки в data/ — латиница, цифры, _ и -",
              font=F.small, fg=C.faint, bg=C.bg).pack(anchor="w", pady=(0, 12))

        for text, key, show in (("Имя", "name", None), ("Логин", "login", None),
                                ("Пароль", "password", "\u2022"),
                                ("Прокси (необязательно)", "proxy", None),
                                ("Скорость сервера", "rate", None)):
            label(box, text, font=F.small, fg=C.dim, bg=C.bg).pack(anchor="w", pady=(8, 3))
            ttk.Entry(box, textvariable=self.vars[key], style="Dark.TEntry",
                      font=F.ui, width=38, show=show or "").pack(fill="x")

        row = tk.Frame(box, bg=C.bg)
        row.pack(fill="x", pady=(14, 0))
        label(row, "Фоновый режим", bg=C.bg).pack(side="left")
        self.headless = Switch(row, value=True, bg=C.bg)
        self.headless.pack(side="right")

        self.error = label(box, "", font=F.small, fg=C.err, bg=C.bg)
        self.error.pack(anchor="w", pady=(10, 0))

        buttons = tk.Frame(box, bg=C.bg)
        buttons.pack(fill="x", pady=(14, 0))
        Button(buttons, "Создать", self._save, kind="primary").pack(side="left")
        Button(buttons, "Отмена", self.destroy, kind="quiet").pack(side="left", padx=6)

    def _save(self) -> None:
        name = self.vars["name"].get().strip()
        if not is_valid_account_name(name):
            self.error.configure(text="Допустимы латинские буквы, цифры, _ и - (до 64)")
            return
        if any(e["name"] == name for e in self.app.snapshot):
            self.error.configure(text="Аккаунт с таким именем уже есть")
            return
        if not self.vars["login"].get().strip() or not self.vars["password"].get():
            self.error.configure(text="Логин и пароль обязательны")
            return

        acc = {
            "name": name,
            "login": self.vars["login"].get().strip(),
            "password": self.vars["password"].get(),
            "proxy": self.vars["proxy"].get().strip(),
            "rate": num_or(self.vars["rate"].get(), 3),
            "headless": self.headless.get(),
            "sleep_hours": [2, 8],
            "evasion_enabled": True,
            "attack_check_interval": 120,
        }

        def done(_r):
            self.app.selected = name
            self.app.after_save(f"Аккаунт «{name}» создан")
            self.destroy()

        self.app.run_bg(lambda: upsert_gui_account(acc), on_done=done,
                        on_error=lambda e: self.error.configure(text=err_text(e)))
