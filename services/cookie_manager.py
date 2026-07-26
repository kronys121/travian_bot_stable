import json
import logging
from pathlib import Path

from utils.jsonio import write_json


class CookieManager:
    def __init__(self, context, filename="cookies.json"):
        self.context = context
        self.filepath = Path.cwd() / filename

    def save_cookie(self):
        try:
            cookies = self.context.cookies()
            # FIX: раньше писали open(..., "w") прямо в целевой файл. Если
            # процесс умирал посреди json.dump, куки оставались обрезанными и
            # следующий старт логинился заново (а лог уже рапортовал успех —
            # он стоял ВНУТРИ with, до закрытия файла).
            if write_json(self.filepath, cookies):
                logging.info(f"🍪 Сохранены куки: {len(cookies)} шт. в {self.filepath.name}")
        except Exception as e:
            logging.error(f"❌ Ошибка при сохранении куки: {e}")

    def load_cookies(self):
        try:
            if self.filepath.exists() and self.filepath.stat().st_size > 0:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                    self.context.add_cookies(cookies)
                    logging.info("🍪 Куки успешно загружены.")
                    return True
            else:
                logging.warning("⚠️ Файл с куки пуст или не существует.")
                return False
        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке куки: {e}")
            return False