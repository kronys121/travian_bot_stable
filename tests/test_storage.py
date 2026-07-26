"""
Тесты слоя хранения: атомарная запись JSON, слияние настроек, валидация
имени аккаунта, поведение SettingsStore на битом файле.

Именно эта «склейка» ломалась молча: битый bot_settings перетирался
дефолтами, пустая строка не могла очистить поле, имя аккаунта из URL
подставлялось в путь без проверки. Тесты закрывают все три случая.

Запуск:  python -m unittest tests.test_storage -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.jsonio import read_json, write_json
from utils.merge import deep_merge
from utils import paths as paths_mod


class TestDeepMerge(unittest.TestCase):
    """None = «не трогать»; пустая строка и 0/False — обычные значения."""

    def test_nested_merge(self):
        base = {"farm": {"a": 1, "b": 2}, "x": 1}
        out = deep_merge(base, {"farm": {"b": 9}})
        self.assertEqual(out["farm"], {"a": 1, "b": 9})
        self.assertEqual(out["x"], 1)

    def test_none_leaves_value_untouched(self):
        self.assertEqual(deep_merge({"proxy": "socks5://h:1"}, {"proxy": None})["proxy"],
                         "socks5://h:1")

    def test_empty_string_clears_field(self):
        # Регресс: старая копия в utils/accounts.py имела `v != ""`,
        # из-за чего прокси нельзя было стереть из дашборда.
        self.assertEqual(deep_merge({"proxy": "socks5://h:1"}, {"proxy": ""})["proxy"], "")

    def test_false_and_zero_are_written(self):
        out = deep_merge({"headless": True, "rate": 3}, {"headless": False, "rate": 0})
        self.assertIs(out["headless"], False)
        self.assertEqual(out["rate"], 0)

    def test_does_not_mutate_arguments(self):
        base = {"a": {"b": 1}}
        deep_merge(base, {"a": {"b": 2}})
        self.assertEqual(base, {"a": {"b": 1}})


class TestAccountNameValidation(unittest.TestCase):
    """Имя аккаунта приходит из URL и становится путём — оно обязано быть проверено."""

    def test_normal_names_ok(self):
        for name in ("Start", "Start1", "acc_2", "my-acc"):
            self.assertTrue(paths_mod.is_valid_account_name(name), name)

    def test_traversal_and_absolute_rejected(self):
        bad = ["..", "../evil", "a/b", "a\\b", "C:/Windows/Temp/x", "", "x" * 65,
               "acc.json", "acc name", "акк"]
        for name in bad:
            self.assertFalse(paths_mod.is_valid_account_name(name), name)
            with self.assertRaises(paths_mod.InvalidAccountName):
                paths_mod.safe_account_name(name)

    def test_account_file_rejects_traversal(self):
        with self.assertRaises(paths_mod.InvalidAccountName):
            paths_mod.account_file("../../evil", "status")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(KeyError):
            paths_mod.account_file("Start", "no_such_kind")


class TestAtomicJson(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_roundtrip(self):
        p = self.dir / "a.json"
        self.assertTrue(write_json(p, {"привет": [1, 2, 3]}))
        self.assertEqual(read_json(p), {"привет": [1, 2, 3]})

    def test_no_tmp_file_left_behind(self):
        p = self.dir / "a.json"
        write_json(p, {"x": 1})
        self.assertEqual([f.name for f in self.dir.iterdir()], ["a.json"])

    def test_missing_file_returns_default(self):
        self.assertEqual(read_json(self.dir / "nope.json", default={"d": 1}), {"d": 1})

    def test_corrupt_file_is_quarantined_not_lost(self):
        p = self.dir / "a.json"
        p.write_text('{"броше', encoding="utf-8")
        self.assertIsNone(read_json(p))
        # Исходные байты обязаны сохраниться рядом — данные не выкидываем.
        saved = [f for f in self.dir.iterdir() if ".corrupt-" in f.name]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(encoding="utf-8"), '{"броше')

    def test_creates_parent_directory(self):
        p = self.dir / "deep" / "nested" / "a.json"
        self.assertTrue(write_json(p, {"x": 1}))
        self.assertEqual(read_json(p), {"x": 1})


class TestSettingsStore(unittest.TestCase):
    """SettingsStore пишет в data/<acc>/settings.json — подменяем корень проекта."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig_root, self._orig_data = paths_mod.PROJECT_ROOT, paths_mod.DATA_DIR
        paths_mod.PROJECT_ROOT = self.dir
        paths_mod.DATA_DIR = self.dir / "data"

    def tearDown(self):
        paths_mod.PROJECT_ROOT, paths_mod.DATA_DIR = self._orig_root, self._orig_data
        shutil.rmtree(self.dir, ignore_errors=True)

    def _store(self, name="Acc", yaml_cfg=None):
        from utils.settings_store import SettingsStore
        return SettingsStore(name, yaml_cfg or {})

    def test_creates_file_with_defaults(self):
        from utils.settings_store import DEFAULT_SETTINGS
        s = self._store()
        self.assertTrue(s.path.exists())
        self.assertEqual(s.section("farm")["troops_per_raid"],
                         DEFAULT_SETTINGS["farm"]["troops_per_raid"])

    def test_corrupt_file_is_preserved_not_wiped(self):
        # Регресс: раньше битый файл молча заменялся дефолтами и вместе с
        # ним исчезали пользовательские шаблоны застройки и очереди.
        s = self._store()
        s.save({"build": {"custom_plans": {"mine": {"name": "Мой план", "steps": []}}}})
        s.path.write_text("{это не json", encoding="utf-8")

        self._store()  # повторное открытие (дашборд создаёт store на каждый запрос)

        saved = list(s.path.parent.glob("settings.json.corrupt-*"))
        self.assertEqual(len(saved), 1, "битый файл должен уехать в карантин")
        self.assertEqual(saved[0].read_text(encoding="utf-8"), "{это не json")

    def test_existing_values_win_over_defaults(self):
        s = self._store()
        s.save({"farm": {"troops_per_raid": 77}})
        self.assertEqual(self._store().section("farm")["troops_per_raid"], 77)

    def test_save_reloads_before_merge(self):
        """Два процесса пишут по очереди — правка первого не должна пропасть."""
        a = self._store()
        b = self._store()
        a.save({"farm": {"troops_per_raid": 11}})
        b.save({"farm": {"cooldown_minutes": 22}})
        fresh = json.loads(a.path.read_text(encoding="utf-8"))
        self.assertEqual(fresh["farm"]["troops_per_raid"], 11)
        self.assertEqual(fresh["farm"]["cooldown_minutes"], 22)

    def test_replace_paths_allows_deletion(self):
        s = self._store()
        s.save({"build": {"village_plans": {"v1": "x3", "v2": "x1"}}})
        s.save({"build": {"village_plans": {"v1": "x3"}}},
               replace_paths=[("build", "village_plans")])
        self.assertEqual(s.section("build")["village_plans"], {"v1": "x3"})

    def test_defaults_cover_every_section_the_ui_writes(self):
        # app.py и мини-апп принимают ровно эти секции — у каждой должен быть дефолт.
        from utils.settings_store import DEFAULT_SETTINGS
        ui_sections = {"features", "farm", "training", "trade", "build",
                       "smithy", "task_order", "night"}
        self.assertTrue(ui_sections.issubset(DEFAULT_SETTINGS.keys()),
                        ui_sections - set(DEFAULT_SETTINGS))


class TestAccountDefaults(unittest.TestCase):
    """DEFAULT_ACCOUNT отвечает только за подключение: игровые дефолты — в SettingsStore."""

    def test_no_game_settings_in_default_account(self):
        from utils.accounts import DEFAULT_ACCOUNT
        for leaked in ("farm", "training", "trade"):
            self.assertNotIn(leaked, DEFAULT_ACCOUNT,
                             f"{leaked} задаётся в DEFAULT_SETTINGS, дублировать нельзя")

    def test_connection_fields_present(self):
        from utils.accounts import DEFAULT_ACCOUNT
        for key in ("rate", "headless", "proxy", "sleep_hours"):
            self.assertIn(key, DEFAULT_ACCOUNT)


class TestCommandsQueue(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig_root, self._orig_data = paths_mod.PROJECT_ROOT, paths_mod.DATA_DIR
        paths_mod.PROJECT_ROOT = self.dir
        paths_mod.DATA_DIR = self.dir / "data"

    def tearDown(self):
        paths_mod.PROJECT_ROOT, paths_mod.DATA_DIR = self._orig_root, self._orig_data
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_push_and_pop(self):
        from utils.commands import pop_commands, push_command
        self.assertTrue(push_command("Acc", "scan"))
        self.assertEqual(pop_commands("Acc"), ["scan"])
        self.assertEqual(pop_commands("Acc"), [])  # очередь очищена

    def test_duplicate_command_not_queued_twice(self):
        from utils.commands import pop_commands, push_command
        push_command("Acc", "scan")
        push_command("Acc", "scan")
        self.assertEqual(pop_commands("Acc"), ["scan"])

    def test_unknown_action_rejected(self):
        from utils.commands import push_command
        self.assertFalse(push_command("Acc", "rm -rf /"))

    def test_invalid_account_name_rejected(self):
        from utils.commands import push_command
        with self.assertRaises(paths_mod.InvalidAccountName):
            push_command("../../evil", "scan")

    def test_corrupt_queue_does_not_crash(self):
        from utils.commands import pop_commands
        p = paths_mod.account_file("Acc", "command")
        p.write_text("не json", encoding="utf-8")
        self.assertEqual(pop_commands("Acc"), [])


if __name__ == "__main__":
    unittest.main()
