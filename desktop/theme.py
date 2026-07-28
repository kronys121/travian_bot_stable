"""Оформление: DPI, палитра, шрифты, тёмная тема для ttk."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


def enable_dpi_awareness() -> None:
    """Сообщить Windows, что приложение умеет в DPI.

    Без этого на масштабе 125/150% ОС растягивает готовую картинку окна
    битмапом — именно оттуда берутся «лесенки» на буквах.

    Вызывать строго ДО создания Tk(): после первого окна режим процесса
    уже зафиксирован и вызов ничего не даёт.

    Уровень 1 (system-aware), а не 2 (per-monitor): при per-monitor Tk
    пересчитывает всю геометрию на каждое движение окна между экранами,
    и протаскивание начинает тормозить.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
    except ImportError:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class C:
    """Палитра: нейтральный графит и ОДИН приглушённый акцент.

    Цветными остаются только смысловые состояния (жив/мёртв, ошибка).
    Всё остальное — оттенки серого, иначе интерфейс рябит.
    """
    bg = "#15171c"
    sidebar = "#191c22"
    surface = "#1d2027"
    surface2 = "#232730"
    line = "#2b303a"
    text = "#dfe3ea"
    dim = "#98a1b0"
    faint = "#6c7686"
    accent = "#6d9eeb"
    accent_hi = "#84b0f5"
    on_accent = "#0f1319"
    ok = "#6fbf8b"
    warn = "#d8a85f"
    err = "#d97f7f"


class F:
    """Шрифты. Заполняются в init_fonts(): до Tk() шрифтов не существует."""
    ui = None
    bold = None
    small = None
    small_bold = None
    h1 = None
    h2 = None
    mono = None


def _pick(candidates: list[str], fallback: str) -> str:
    """Первый реально установленный шрифт из списка.

    Берём именно системные шрифты: их ОС рисует через ClearType/CoreText
    со сглаживанием. Шрифт, подгруженный библиотекой в рантайме (как
    Roboto у customtkinter), такого сглаживания не получает.
    """
    try:
        available = {f.lower() for f in tkfont.families()}
    except Exception:
        return fallback
    for name in candidates:
        if name.lower() in available:
            return name
    return fallback


def init_fonts() -> None:
    ui = _pick(["Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu",
                "Noto Sans", "DejaVu Sans"], "TkDefaultFont")
    mono = _pick(["Cascadia Mono", "Consolas", "SF Mono", "Menlo",
                  "JetBrains Mono", "DejaVu Sans Mono"], "TkFixedFont")
    F.ui = tkfont.Font(family=ui, size=10)
    F.bold = tkfont.Font(family=ui, size=10, weight="bold")
    F.small = tkfont.Font(family=ui, size=9)
    F.small_bold = tkfont.Font(family=ui, size=9, weight="bold")
    F.h1 = tkfont.Font(family=ui, size=15, weight="bold")
    F.h2 = tkfont.Font(family=ui, size=11, weight="bold")
    F.mono = tkfont.Font(family=mono, size=10)


def init_ttk(root: tk.Misc) -> None:
    """Тёмная тема для тех немногих ttk-виджетов, что мы берём готовыми.

    Тема 'clam' — единственная встроенная, где реально работают
    fieldbackground и bordercolor. На native-теме Windows поля ввода
    останутся белыми, какие цвета им ни задавай.
    """
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass

    st.configure("Dark.TEntry", fieldbackground=C.surface2, background=C.surface2,
                 foreground=C.text, bordercolor=C.line, lightcolor=C.line,
                 darkcolor=C.line, insertcolor=C.text, padding=6, relief="flat")
    st.map("Dark.TEntry",
           bordercolor=[("focus", C.accent)],
           lightcolor=[("focus", C.accent)],
           darkcolor=[("focus", C.accent)])

    st.configure("Dark.TCombobox", fieldbackground=C.surface2, background=C.surface2,
                 foreground=C.text, arrowcolor=C.dim, bordercolor=C.line,
                 lightcolor=C.line, darkcolor=C.line, padding=5, relief="flat")
    st.map("Dark.TCombobox",
           fieldbackground=[("readonly", C.surface2)],
           foreground=[("readonly", C.text)],
           bordercolor=[("focus", C.accent)])

    # Выпадающий список Combobox — это отдельный tk.Listbox внутри Tcl.
    # Через ttk.Style он НЕ красится, только через option database.
    root.option_add("*TCombobox*Listbox.background", C.surface2)
    root.option_add("*TCombobox*Listbox.foreground", C.text)
    root.option_add("*TCombobox*Listbox.selectBackground", C.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", C.on_accent)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    st.configure("Dark.Vertical.TScrollbar", background=C.line, troughcolor=C.bg,
                 bordercolor=C.bg, arrowcolor=C.faint, relief="flat", width=10)
    st.map("Dark.Vertical.TScrollbar", background=[("active", C.faint)])
