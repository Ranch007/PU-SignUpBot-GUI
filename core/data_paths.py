"""运行数据放在用户可写目录，并从旧版 EXE 旁迁移一次。"""

import os
from pathlib import Path
import shutil
import tempfile


DATA_FILES = (
    "user_data.json", "user_data.json.bak",
    "settings.json", "settings.json.bak",
    "signup_tasks.json", "signup_tasks.json.bak",
)


def data_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or
                    (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or
                    (Path.home() / ".local" / "share"))
    return base / "PU-SignUpBot-GUI"


def migrate_legacy_data(legacy_directory: Path, destination: Path) -> list[Path]:
    """只补齐目标目录不存在的文件；原文件留给用户核对后处理。"""
    destination.mkdir(parents=True, exist_ok=True)
    if legacy_directory.resolve() == destination.resolve():
        return []
    copied = []
    for name in DATA_FILES:
        source = legacy_directory / name
        target = destination / name
        if not source.is_file() or target.exists():
            continue
        handle, temporary = tempfile.mkstemp(prefix=".pu-", suffix=".tmp", dir=destination)
        try:
            with os.fdopen(handle, "wb") as output, source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        copied.append(source)
    return copied
