import json
import logging
from pathlib import Path

from utils.jsonio import write_json
from utils.paths import PROJECT_ROOT


class CookieManager:
    """Чтение/запись кук браузерного контекста.

    ФИКС (путь): раньше путь считался как `Path.cwd() / filename`. Абсолютный
    путь из utils.paths это переживало, а вот дефолтный относительный
    "cookies.json" привязывался к текущему каталогу процесса. Дашборд
    запускается как `uvicorn app:app` из произвольного места, бот — с
    cwd=репозиторий, и два процесса работали с РАЗНЫМИ файлами кук.
    Теперь относительные пути якорятся к корню проекта, как и всё остальное
    состояние (см. utils/paths.py).
    """

    def __init__(self, context, filename="cookies.json"):
        self.context = context
        path = Path(filename)
        self.filepath = path if path.is_absolute() else PROJECT_ROOT / path

    def save_cookie(self):
        try:
            cookies = self.context.cookies()
            # ФИКС: пустой список кук (контекст умер / логаут) раньше
            # затирал рабочий файл, и следующий старт логинился заново.
            if not cookies:
                logging.warning("⚠️ Контекст вернул 0 кук — файл не перезаписываю.")
                return
            # FIX: раньше писали open(..., "w") прямо в целевой файл. Если
            # процесс умирал посреди json.dump, куки оставались обрезанными и
            # следующий старт логинился заново (а лог уже рапортовал успех —
            # он стоял ВНУТРИ with, до закрытия файла).
            if write_json(self.filepath, cookies):
                logging.info(f"🍪 Сохранены куки: {len(cookies)} шт. в {self.filepath.name}")
        except Exception as e:
            logging.error(f"❌ Ошибка при сохранении куки: {e}")

    def load_cookies(self) -> bool:
        try:
            if not (self.filepath.exists() and self.filepath.stat().st_size > 0):
                logging.warning("⚠️ Файл с куки пуст или не существует.")
                return False
            with open(self.filepath, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            # ФИКС: битый/чужой формат уходил прямо в add_cookies и валил
            # playwright невнятной ошибкой ещё до попытки логина.
            if not isinstance(cookies, list) or not all(isinstance(c, dict) for c in cookies):
                logging.error("❌ Формат файла кук не распознан — вход по логину/паролю.")
                return False
            self.context.add_cookies(cookies)
            logging.info(f"🍪 Куки успешно загружены ({len(cookies)} шт.).")
            return True
        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке куки: {e}")
            return False
