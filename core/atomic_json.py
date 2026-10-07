"""同目录临时文件替换，并保留一份可恢复的 JSON 副本。"""

import json
import os
import tempfile


def _replace_json(path: str, data) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".pu-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=4, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: str, data) -> None:
    _replace_json(path, data)
    _replace_json(path + ".bak", data)


def read_json(path: str, default, expected_type=None):
    """主文件损坏时读取备份；两者都损坏时抛错，避免静默清空数据。"""
    if not os.path.exists(path) and not os.path.exists(path + ".bak"):
        return default, False
    errors = []
    for candidate, backup in ((path, False), (path + ".bak", True)):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as stream:
                result = json.load(stream)
            if expected_type is not None and not isinstance(result, expected_type):
                raise ValueError("JSON 顶层类型不正确")
            return result, backup
        except (OSError, ValueError) as exc:
            errors.append(f"{os.path.basename(candidate)}: {exc}")
    raise ValueError("数据文件及备份均无法读取：" + "；".join(errors))
