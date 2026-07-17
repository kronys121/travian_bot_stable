import json
import logging
from pathlib import Path


class CookieManager:
    def __init__(self, context, filename="cookies.json"):
        self.context = context
        self.filepath = Path.cwd() / filename

    def save_cookie(self):
        try:
            cookies = self.context.cookies()
            self.filepath.parent.mkdir(parents=True, exist_ok=True)

            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(cookies, f)
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