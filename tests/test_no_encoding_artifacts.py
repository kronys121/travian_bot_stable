"""
Страж кодировки: во всех текстовых файлах репозитория не должно быть
символа-замены U+FFFD ("").

Артефакты "" появляются, когда файл с кириллицей сохраняют в неверной
кодировке (например Windows cp1251 вместо UTF-8). Один раз потерянные
байты не восстановить, поэтому этот тест ловит проблему сразу: если
редактор снова испортил файл, тест падает и показывает где именно.

Запуск:  python3 -m unittest tests.test_no_encoding_artifacts -v
"""
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).parent.parent

# Расширения, которые считаем текстовыми (остальное — бинарь, пропускаем).
TEXT_EXT = {
    ".py", ".pyw", ".html", ".htm", ".css", ".js", ".json",
    ".md", ".txt", ".yaml", ".yml", ".cfg", ".ini", ".toml",
    ".editorconfig", ".gitattributes", ".gitignore",
}

REPLACEMENT = "\ufffd"


def _tracked_files():
    """Список файлов под контролем git (fallback — обход дерева)."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO), "ls-files", "-z"],
            stderr=subprocess.DEVNULL,
        )
        names = [n for n in out.decode("utf-8", "replace").split("\0") if n]
        return [REPO / n for n in names]
    except Exception:
        files = []
        for p in REPO.rglob("*"):
            if ".git" in p.parts:
                continue
            if p.is_file():
                files.append(p)
        return files


def _is_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXT:
        return True
    return path.name in TEXT_EXT


class EncodingArtifactsTest(unittest.TestCase):
    def test_no_replacement_char(self):
        offenders = []
        for path in _tracked_files():
            if not path.is_file() or not _is_text(path):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                # текстовый файл, который не читается как UTF-8 — тоже проблема
                offenders.append(f"{path.relative_to(REPO)}: не читается как UTF-8")
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if REPLACEMENT in line:
                    n = line.count(REPLACEMENT)
                    offenders.append(
                        f"{path.relative_to(REPO)}:{i}: {n}x U+FFFD -> {line.strip()[:80]}"
                    )
        self.assertEqual(
            offenders, [],
            "Найдены артефакты кодировки U+FFFD (сохрани файл в UTF-8):\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
