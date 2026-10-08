"""恢复中断任务前的只读校验；此模块不会发送报名请求。"""

from datetime import datetime

from core.activity_plan import parse_activity_time
from core.tools import get_info, get_user_credit, get_single_activity
from core.participation import participation_checks


class RestoreError(Exception):
    pass


def validate_restore(user: dict, activity_id: str) -> dict:
    if user.get("credential_error") or not user.get("token"):
        raise RestoreError("请先重新登录，再恢复任务")
    get_user_credit(user["token"], user["sid"], strict=True)
    info = get_info(activity_id, user["token"], user["sid"], strict=True)
    mismatches = [check["message"] for check in participation_checks(info, user) if check["status"] == "mismatch"]
    if mismatches:
        raise RestoreError("；".join(mismatches))
    if info.get("statusName") != "未开始":
        raise RestoreError(f"活动状态为“{info.get('statusName') or '未知'}”，请核实后重新选择")
    start = parse_activity_time(info.get("joinStartTime"))
    if not start or start <= datetime.now():
        raise RestoreError("报名时间已过或无法确认，请核实活动详情")
    try:
        capacity = int(info["allowUserCount"])
        joined = int(info["joinUserCount"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RestoreError("无法确认活动剩余名额，请核实活动详情") from exc
    if capacity <= joined:
        raise RestoreError("活动名额已满")
    return get_single_activity(activity_id, info)
