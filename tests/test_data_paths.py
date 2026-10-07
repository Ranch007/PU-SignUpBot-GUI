"""旧版便携数据迁移不覆盖用户目录中的现有数据。"""

import tempfile
import unittest
from pathlib import Path

from core.data_paths import migrate_legacy_data


class DataPathsTests(unittest.TestCase):
    def test_migrates_existing_data_once_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy"
            target = root / "appdata"
            legacy.mkdir()
            (legacy / "user_data.json").write_text("old", encoding="utf-8")
            (legacy / "signup_tasks.json").write_text("tasks", encoding="utf-8")
            self.assertEqual(len(migrate_legacy_data(legacy, target)), 2)
            self.assertEqual((target / "user_data.json").read_text(encoding="utf-8"), "old")
            (target / "user_data.json").write_text("new", encoding="utf-8")
            self.assertEqual(migrate_legacy_data(legacy, target), [])
            self.assertEqual((target / "user_data.json").read_text(encoding="utf-8"), "new")
            self.assertEqual((legacy / "user_data.json").read_text(encoding="utf-8"), "old")
