"""学校与学号共同标识账号，兼容原有单学号调用。"""


def account_key(user: dict) -> tuple[str, str]:
    return str(user.get("sid", "")), str(user.get("userName", ""))


def account_from_task(task_id: str) -> tuple[str, str]:
    sid, username, _activity = task_id.split(":", 2)
    return sid, username


def credential_snapshot(user: dict) -> tuple:
    # 对象身份防止删除后重新添加的同名账号消费旧响应。
    return id(user), account_key(user), user.get("token", "")


def credentials_match(user: dict | None, snapshot: tuple) -> bool:
    return user is not None and credential_snapshot(user) == snapshot
