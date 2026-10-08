"""只保存任务状态，不保存密码或 Token。"""

from dataclasses import asdict
import math

from core.atomic_json import read_json, write_json


class TaskStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> list[dict]:
        document, backup = read_json(self.path, {"version": 1, "tasks": []}, dict)
        if document.get("version") != 1 or not isinstance(document.get("tasks"), list):
            raise ValueError("任务数据格式不正确")
        required = {"task_id", "username", "activity_id", "state", "message"}
        result = []
        for item in document["tasks"]:
            if (not isinstance(item, dict) or not required.issubset(item) or
                    any(not isinstance(item[key], str) for key in required) or
                    not isinstance(item.get("updated_at", ""), str)):
                raise ValueError("任务记录格式不正确")
            result.append({key: item[key] for key in required} |
                          {"updated_at": item.get("updated_at", "")})
            for key, default in (("error_kind", ""), ("error_code", None),
                                 ("retryable", False), ("join_start_time", None),
                                 ("join_end_time", None), ("server_offset", 0.0)):
                value = item.get(key, default)
                if key == "retryable" and not isinstance(value, bool):
                    raise ValueError("任务重试标记格式不正确")
                if key == "server_offset" and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                    raise ValueError("任务对时偏差格式不正确")
                if key == "error_code" and value is not None and not isinstance(value, int):
                    raise ValueError("任务错误码格式不正确")
                if key in {"error_kind", "join_start_time", "join_end_time"} and value is not None and not isinstance(value, str):
                    raise ValueError("任务时间或错误分类格式不正确")
                result[-1][key] = value
        if backup:
            write_json(self.path, document)
        return result

    def save(self, events) -> None:
        write_json(self.path, {"version": 1, "tasks": [asdict(event) for event in events]})
