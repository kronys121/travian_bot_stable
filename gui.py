"""Запуск десктопной панели: python gui.py

Сам интерфейс лежит в пакете desktop/. Здесь только то, что обязано
выполниться ДО создания первого окна Tk.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.theme import enable_dpi_awareness

# Строго до импорта окна и до Tk(): после создания окна режим DPI
# у процесса уже зафиксирован, и шрифты останутся с «лесенками».
enable_dpi_awareness()

from desktop.window import App  # noqa: E402


def main() -> int:
    try:
        app = App()
    except Exception as exc:
        # Графического окна ещё нет, так что единственный способ сообщить
        # об ошибке — консоль. Батник держит окно открытым после выхода.
        print(f"Не удалось запустить панель: {exc}", file=sys.stderr)
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
