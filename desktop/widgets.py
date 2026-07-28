"""Базовые компоненты интерфейса.

Всё собрано из обычных Frame/Label: они не рисуются вручную и потому
ничего не стоят при ресайзе окна. Canvas — только там, где нужна форма
(тумблер, точка статуса), и перерисовка идёт только по смене состояния.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .theme import C, F


def label(parent, text: str = "", *, font=None, fg: str | None = None,
          bg: str | None = None, **kw) -> tk.Label:
    return tk.Label(parent, text=text, font=font or F.ui, fg=fg or C.text,
                    bg=bg or parent.cget("bg"), anchor="w", justify="left", **kw)


class Card(tk.Frame):
    """Контейнер с тонкой границей.

    Граница через highlightthickness, а не relief: relief в tk рисует
    объёмную рамку из 90-х, которую нельзя сделать плоской.
    """

    def __init__(self, parent, **kw):
        kw.setdefault("bg", C.surface)
        super().__init__(parent, bd=0, highlightthickness=1,
                         highlightbackground=C.line, highlightcolor=C.line, **kw)


class Button(tk.Frame):
    """Плоская кнопка (Frame + Label).

    tk.Button на Windows игнорирует bg в активном состоянии — именно
    поэтому «обычный tkinter» выглядит серым и чужеродным в тёмной теме.
    """

    KINDS = {
        "primary": (C.accent, C.accent_hi, C.on_accent),
        "ghost": (C.surface2, C.line, C.text),
        "danger": ("#3a2529", "#4a2c31", C.err),
        "quiet": (C.surface, C.surface2, C.dim),
    }

    def __init__(self, parent, text: str, command=None, kind: str = "ghost",
                 padx: int = 13, pady: int = 6, font=None, **kw):
        # Фон кнопки всегда определяется её видом. Вызовы часто передают
        # bg родительской поверхности по привычке — молча игнорируем его,
        # иначе super() получит bg дважды и упадёт с TypeError.
        kw.pop("bg", None)
        bg, hover, fg = self.KINDS.get(kind, self.KINDS["ghost"])
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0, cursor="hand2", **kw)
        self._bg, self._hover, self._fg = bg, hover, fg
        self._command = command
        self._enabled = True
        self.label = tk.Label(self, text=text, bg=bg, fg=fg,
                              font=font or F.ui, padx=padx, pady=pady)
        self.label.pack()
        for w in (self, self.label):
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
            w.bind("<Button-1>", self._click)

    def _paint(self, bg: str, fg: str | None = None) -> None:
        self.configure(bg=bg)
        self.label.configure(bg=bg, fg=fg or self.label.cget("fg"))

    def _enter(self, _=None):
        if self._enabled:
            self._paint(self._hover)

    def _leave(self, _=None):
        if self._enabled:
            self._paint(self._bg)

    def _click(self, _=None):
        if self._enabled and self._command:
            self._command()

    def set_text(self, text: str) -> None:
        self.label.configure(text=text)

    def set_command(self, command) -> None:
        self._command = command

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        if self._enabled:
            self.configure(cursor="hand2")
            self._paint(self._bg, self._fg)
        else:
            self.configure(cursor="")
            self._paint(C.surface, C.faint)


class Switch(tk.Canvas):
    """Тумблер-пилюля."""

    W, H = 38, 20

    def __init__(self, parent, value: bool = False, command=None, bg: str | None = None):
        super().__init__(parent, width=self.W, height=self.H, bd=0,
                         highlightthickness=0, cursor="hand2",
                         bg=bg or parent.cget("bg"))
        self._value = bool(value)
        self._command = command
        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        track = C.accent if self._value else C.line
        r = self.H // 2
        # Пилюля = два круга + прямоугольник: у Canvas нет скруглённых углов.
        self.create_oval(0, 0, self.H, self.H, fill=track, outline="")
        self.create_oval(self.W - self.H, 0, self.W, self.H, fill=track, outline="")
        self.create_rectangle(r, 0, self.W - r, self.H, fill=track, outline="")
        knob = C.on_accent if self._value else C.dim
        x = self.W - self.H + 3 if self._value else 3
        self.create_oval(x, 3, x + self.H - 6, self.H - 3, fill=knob, outline="")

    def _toggle(self, _=None) -> None:
        self._value = not self._value
        self._draw()
        if self._command:
            self._command(self._value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        value = bool(value)
        if value != self._value:
            self._value = value
            self._draw()


class Dot(tk.Canvas):
    """Точка-индикатор состояния."""

    def __init__(self, parent, size: int = 8, bg: str | None = None):
        super().__init__(parent, width=size, height=size, bd=0,
                         highlightthickness=0, bg=bg or parent.cget("bg"))
        self._size = size
        self._color = C.faint
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        self.create_oval(0, 0, self._size, self._size, fill=self._color, outline="")

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self._draw()


class ScrollArea(tk.Frame):
    """Прокручиваемая область. Содержимое кладётся в .body.

    Колесо мыши привязывается по Enter/Leave, а не навсегда: иначе две
    такие области на разных вкладках перехватывают прокрутку друг у друга.
    """

    def __init__(self, parent, bg: str | None = None):
        bg = bg or C.bg
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                       style="Dark.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.bind("<Enter>", lambda _e: self._wheel(True))
        self.bind("<Leave>", lambda _e: self._wheel(False))

    def _on_body(self, _=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _wheel(self, active: bool) -> None:
        events = ("<MouseWheel>", "<Button-4>", "<Button-5>")
        for ev in events:
            if active:
                self.canvas.bind_all(ev, self._scroll)
            else:
                self.canvas.unbind_all(ev)

    def _scroll(self, event) -> None:
        num = getattr(event, "num", None)
        if num == 4:
            step = -1
        elif num == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")

    def to_top(self) -> None:
        self.canvas.yview_moveto(0.0)
