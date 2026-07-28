"""Вкладки «Настройки» и «Порядок задач».

Обе работают с SettingsStore того же аккаунта, что и веб-панель.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app import _validate_settings as validate_settings
from app import get_store

from .model import (
    BUILD_TEMPLATES,
    FARM_MODES,
    FEATURE_GROUPS,
    NUMERIC,
    NUMERIC_TITLES,
    TASK_LABELS,
    TRIBE_BY_LABEL,
    TRIBE_LABELS,
    TRIBES,
    err_text,
    farm_mode_of,
    num_or,
)
from .theme import C, F
from .widgets import Button, Card, ScrollArea, Switch, label


class SettingsPage(tk.Frame):
    """Функции, числовые параметры, племя и шаблон стройки."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=C.bg)
        self.app = app
        self.switches: dict[str, Switch] = {}
        self.entries: dict[tuple[str, str], tk.StringVar] = {}
        self.farm_mode = tk.StringVar(value="troops")
        self.tribe = tk.StringVar(value=TRIBE_LABELS["roman"])
        self.template = tk.StringVar(value="")
        self._loaded_for: str | None = None
        self._build()

    # ------------------------------------------------------------------ вёрстка
    def _build(self) -> None:
        bar = tk.Frame(self, bg=C.bg)
        bar.pack(fill="x", padx=18, pady=(14, 0))
        Button(bar, "Сохранить настройки", self.save, kind="primary").pack(side="left")
        Button(bar, "Сбросить к сохранённому",
               lambda: self.load(force=True), kind="quiet").pack(side="left", padx=8)
        label(bar, "Изменения применяются на ходу, перезапуск не нужен",
              font=F.small, fg=C.faint, bg=C.bg).pack(side="left", padx=12)

        self.area = ScrollArea(self)
        self.area.pack(fill="both", expand=True, padx=12, pady=12)
        body = self.area.body

        self._farm_mode_card(body)
        for title, items in FEATURE_GROUPS:
            self._feature_card(body, title, items)
        self._tribe_card(body)
        for section, rows in NUMERIC.items():
            self._numeric_card(body, section, rows)

    def _card(self, parent, title: str) -> tk.Frame:
        card = Card(parent)
        card.pack(fill="x", padx=6, pady=6)
        label(card, title, font=F.h2, bg=C.surface).pack(
            anchor="w", padx=16, pady=(13, 2))
        inner = tk.Frame(card, bg=C.surface)
        inner.pack(fill="x", padx=16, pady=(4, 14))
        return inner

    def _farm_mode_card(self, parent) -> None:
        inner = self._card(parent, "Фарм")
        row = tk.Frame(inner, bg=C.surface)
        row.pack(fill="x", pady=(0, 8))
        label(row, "Фарм оазисов", bg=C.surface).pack(side="left")
        sw = Switch(row, bg=C.surface)
        sw.pack(side="right")
        self.switches["farm_enabled"] = sw

        label(inner, "Кем фармить", font=F.small, fg=C.dim, bg=C.surface).pack(
            anchor="w", pady=(6, 4))
        modes = tk.Frame(inner, bg=C.surface)
        modes.pack(anchor="w")
        for key, text, _flags in FARM_MODES:
            rb = tk.Radiobutton(
                modes, text=text, value=key, variable=self.farm_mode,
                bg=C.surface, fg=C.text, selectcolor=C.surface2,
                activebackground=C.surface, activeforeground=C.text,
                highlightthickness=0, bd=0, font=F.ui, cursor="hand2",
                anchor="w", padx=2)
            rb.pack(side="left", padx=(0, 16))

    def _feature_card(self, parent, title: str, items) -> None:
        inner = self._card(parent, title)
        for key, text, hint in items:
            row = tk.Frame(inner, bg=C.surface)
            row.pack(fill="x", pady=4)
            left = tk.Frame(row, bg=C.surface)
            left.pack(side="left", fill="x", expand=True)
            label(left, text, bg=C.surface).pack(anchor="w")
            label(left, hint, font=F.small, fg=C.faint, bg=C.surface).pack(anchor="w")
            sw = Switch(row, bg=C.surface)
            sw.pack(side="right")
            self.switches[key] = sw

    def _tribe_card(self, parent) -> None:
        inner = self._card(parent, "Племя и шаблон стройки")
        grid = tk.Frame(inner, bg=C.surface)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        label(grid, "Племя", font=F.small, fg=C.dim, bg=C.surface).grid(
            row=0, column=0, sticky="w", pady=(0, 3))
        ttk.Combobox(grid, textvariable=self.tribe, state="readonly",
                     values=[TRIBE_LABELS[t] for t in TRIBES],
                     style="Dark.TCombobox", font=F.ui).grid(
            row=1, column=0, sticky="ew", padx=(0, 8))

        label(grid, "Шаблон стройки", font=F.small, fg=C.dim, bg=C.surface).grid(
            row=0, column=1, sticky="w", pady=(0, 3))
        ttk.Combobox(grid, textvariable=self.template, state="readonly",
                     values=["— не менять —"] + sorted(BUILD_TEMPLATES.keys()),
                     style="Dark.TCombobox", font=F.ui).grid(
            row=1, column=1, sticky="ew")

        label(inner, "Шаблон применяется к деревням без собственного плана",
              font=F.small, fg=C.faint, bg=C.surface).pack(anchor="w", pady=(8, 0))

    def _numeric_card(self, parent, section: str, rows) -> None:
        inner = self._card(parent, NUMERIC_TITLES.get(section, section))
        grid = tk.Frame(inner, bg=C.surface)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        if section == "night":
            row = tk.Frame(inner, bg=C.surface)
            row.pack(fill="x", pady=(10, 0))
            label(row, "Ночной режим включён", bg=C.surface).pack(side="left")
            sw = Switch(row, bg=C.surface)
            sw.pack(side="right")
            self.switches["night.enabled"] = sw

        for i, (key, text, lo, hi, _cast) in enumerate(rows):
            col = i % 2
            box = tk.Frame(grid, bg=C.surface)
            box.grid(row=i // 2, column=col, sticky="ew",
                     padx=(0, 8) if col == 0 else 0, pady=5)
            label(box, text, font=F.small, fg=C.dim, bg=C.surface).pack(anchor="w")
            var = tk.StringVar()
            ttk.Entry(box, textvariable=var, style="Dark.TEntry",
                      font=F.ui).pack(fill="x", pady=(3, 0))
            label(box, f"от {lo} до {hi}", font=F.small, fg=C.faint,
                  bg=C.surface).pack(anchor="w")
            self.entries[(section, key)] = var

    # -------------------------------------------------------------------- данные
    def load(self, force: bool = False) -> None:
        entry = self.app.current
        if not entry:
            return
        # Не затираем поля на каждом автообновлении: иначе цифра, которую
        # пользователь набирает прямо сейчас, исчезнет через четыре секунды.
        if not force and self._loaded_for == entry["name"]:
            return
        self._loaded_for = entry["name"]
        s = entry.get("settings") or {}
        features = s.get("features") or {}

        for key, sw in self.switches.items():
            if key == "night.enabled":
                sw.set(bool((s.get("night") or {}).get("enabled", False)))
            else:
                sw.set(bool(features.get(key, False)))
        self.farm_mode.set(farm_mode_of(features))

        farm = s.get("farm") or {}
        self.tribe.set(TRIBE_LABELS.get(str(farm.get("tribe", "roman")), "Римляне"))
        self.template.set("— не менять —")

        for (section, key), var in self.entries.items():
            value = (s.get(section) or {}).get(key, "")
            var.set("" if value is None else str(value))

    def collect(self) -> dict:
        """Собрать payload в том же виде, что шлёт POST /api/accounts/{n}/settings."""
        features = {k: sw.get() for k, sw in self.switches.items()
                    if k != "night.enabled"}
        for key, _text, flags in FARM_MODES:
            if key == self.farm_mode.get():
                features.update(flags)
                break

        payload: dict = {"features": features}
        for (section, key), var in self.entries.items():
            rows = {r[0]: r for r in NUMERIC[section]}
            _k, _t, lo, hi, cast = rows[key]
            raw = var.get().strip()
            if raw == "":
                continue
            value = num_or(raw.replace(",", "."), None, cast)
            if value is None:
                raise ValueError(f"Поле «{_t}»: нужно число")
            if not (lo <= value <= hi):
                raise ValueError(f"Поле «{_t}»: допустимо от {lo} до {hi}")
            payload.setdefault(section, {})[key] = value

        payload.setdefault("farm", {})["tribe"] = TRIBE_BY_LABEL.get(
            self.tribe.get(), "roman")
        payload.setdefault("night", {})["enabled"] = self.switches["night.enabled"].get()
        return payload

    def save(self) -> None:
        entry = self.app.current
        if not entry:
            return
        try:
            payload = self.collect()
        except ValueError as exc:
            self.app.toast(str(exc), "err")
            return

        name = entry["name"]

        def work():
            cleaned = validate_settings(payload)
            if not isinstance(cleaned, dict):
                cleaned = payload
            get_store(name).save(cleaned)

        self.app.run_bg(
            work,
            on_done=lambda _r: self.app.after_save("Настройки сохранены"),
            on_error=lambda e: self.app.toast(err_text(e), "err"),
        )


class OrderPage(tk.Frame):
    """Порядок задач в цикле бота."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=C.bg)
        self.app = app
        self._loaded_for: str | None = None
        self.order: list[str] = []

        head = tk.Frame(self, bg=C.bg)
        head.pack(fill="x", padx=18, pady=(14, 6))
        label(head, "Задачи выполняются сверху вниз", font=F.small,
              fg=C.faint, bg=C.bg).pack(side="left")

        card = Card(self)
        card.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        inner = tk.Frame(card, bg=C.surface)
        inner.pack(fill="both", expand=True, padx=14, pady=14)

        self.listbox = tk.Listbox(
            inner, bg=C.surface2, fg=C.text, font=F.ui, bd=0,
            highlightthickness=0, activestyle="none", selectmode="browse",
            selectbackground=C.accent, selectforeground=C.on_accent)
        self.listbox.pack(side="left", fill="both", expand=True)

        side = tk.Frame(inner, bg=C.surface)
        side.pack(side="right", fill="y", padx=(14, 0))
        Button(side, "↑ Вверх", lambda: self._move(-1), bg=C.surface).pack(fill="x", pady=3)
        Button(side, "↓ Вниз", lambda: self._move(1), bg=C.surface).pack(fill="x", pady=3)
        Button(side, "Сохранить", self.save, kind="primary",
               bg=C.surface).pack(fill="x", pady=(14, 3))
        Button(side, "Сбросить", lambda: self.load(force=True), kind="quiet",
               bg=C.surface).pack(fill="x", pady=3)

    def _redraw(self) -> None:
        selected = self.listbox.curselection()
        self.listbox.delete(0, "end")
        for i, key in enumerate(self.order, 1):
            self.listbox.insert("end", f"  {i}.  {TASK_LABELS.get(key, key)}")
        if selected:
            self.listbox.selection_set(selected[0])

    def load(self, force: bool = False) -> None:
        entry = self.app.current
        if not entry:
            return
        if not force and self._loaded_for == entry["name"]:
            return
        self._loaded_for = entry["name"]
        order = ((entry.get("settings") or {}).get("task_order") or {}).get("order")
        self.order = [k for k in (order or []) if k in TASK_LABELS]
        # Добавляем задачи, появившиеся в коде после сохранения файла,
        # иначе они молча пропадут из списка при первом же сохранении.
        for key in TASK_LABELS:
            if key not in self.order:
                self.order.append(key)
        self._redraw()

    def _move(self, delta: int) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if not (0 <= j < len(self.order)):
            return
        self.order[i], self.order[j] = self.order[j], self.order[i]
        self._redraw()
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(j)

    def save(self) -> None:
        entry = self.app.current
        if not entry:
            return
        name = entry["name"]
        order = list(self.order)

        def work():
            # replace_paths: без него список слился бы со старым, а не заменил его
            get_store(name).save({"task_order": {"order": order}},
                                 replace_paths=("task_order.order",))

        self.app.run_bg(
            work,
            on_done=lambda _r: self.app.after_save("Порядок задач сохранён"),
            on_error=lambda e: self.app.toast(err_text(e), "err"),
        )
