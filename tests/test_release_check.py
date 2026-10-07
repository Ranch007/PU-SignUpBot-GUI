"""发布包检查必须拦住运行时生成的私有文件。"""

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.check_release import check


class ReleaseCheckTests(unittest.TestCase):
    def test_directory_detects_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.exe").write_bytes(b"")
            (root / "logs").mkdir()
            (root / "logs" / "today.log").write_text("test", encoding="utf-8")
            (root / "user_data.json").write_text("{}", encoding="utf-8")
            self.assertEqual(set(check(root)),
                             {str(Path("logs") / "today.log"), "user_data.json"})

    def test_zip_detects_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "release.zip"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("app/app.exe", b"")
                archive.writestr("app/.env", "secret")
            self.assertEqual(check(archive_path), ["app/.env"])
