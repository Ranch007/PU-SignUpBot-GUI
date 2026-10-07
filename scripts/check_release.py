"""拒绝把本地账号、任务和日志混进发布目录或 ZIP。只检查文件名。"""

import argparse
from pathlib import Path
from zipfile import ZipFile, is_zipfile


PRIVATE_FILES = {
    "user_data.json", "user_data.json.bak",
    "settings.json", "settings.json.bak",
    "signup_tasks.json", "signup_tasks.json.bak",
}


def is_private(name: str) -> bool:
    parts = [part.lower() for part in Path(name).parts]
    basename = parts[-1]
    return (basename in PRIVATE_FILES or basename == ".env" or
            basename.startswith(".env.") or basename.endswith(".log") or
            "logs" in parts[:-1])


def check(path: Path) -> list[str]:
    if path.is_dir():
        return [str(file.relative_to(path)) for file in path.rglob("*")
                if file.is_file() and is_private(str(file.relative_to(path)))]
    if path.is_file() and is_zipfile(path):
        with ZipFile(path) as archive:
            return [name for name in archive.namelist()
                    if not name.endswith("/") and is_private(name)]
    raise ValueError("请传入发布目录或 ZIP 文件")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="PyInstaller 发布目录或 ZIP 包")
    args = parser.parse_args()
    try:
        private = check(args.path)
    except ValueError as exc:
        parser.error(str(exc))
    if private:
        print("发布包包含本地私有文件，请移出后重建 ZIP：")
        for name in private:
            print(f"  {name}")
        return 1
    print("发布包文件名检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
