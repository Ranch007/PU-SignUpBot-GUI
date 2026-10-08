"""活动选择和首页计划使用的纯数据处理。"""

from datetime import datetime, timedelta
from core.participation import activity_participation_checks


def parse_activity_time(value):
    if not value:
        return None
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def activity_is_full(activity):
    """只把明确的零或负数剩余名额判定为满员。"""
    try:
        return int(activity.get("可报名人数")) <= 0
    except (TypeError, ValueError):
        return False


def visible_activities(activities, query="", sort_by="报名时间", *, user=None, selected=()):
    query = query.strip().casefold()
    visible = [a for a in activities if query in str(a.get("活动名称") or "").casefold()]
    if user is not None:
        selected = {str(aid) for aid in selected}
        visible = [a for a in visible if str(a.get("activity_id")) in selected or
                   not any(check["status"] == "mismatch"
                           for check in activity_participation_checks(a, user))]
    if sort_by == "活动时间":
        return sorted(visible, key=lambda a: (parse_activity_time(a.get("活动开始时间")) or datetime.max,
                                               str(a.get("activity_id"))))
    if sort_by == "学分":
        return sorted(visible, key=lambda a: (-_score(a.get("分数")), str(a.get("activity_id"))))
    return sorted(visible, key=lambda a: (parse_activity_time(a.get("开始报名时间")) or datetime.max,
                                           str(a.get("activity_id"))))


def _score(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def selectable_activity_ids(activities, user, query=""):
    """全选当前搜索结果；满员及明确条件未通过核对的活动交由用户处理。"""
    return {str(activity["activity_id"])
            for activity in visible_activities(activities, query, user=user)
            if not activity_is_full(activity)
            and not any(check["status"] != "matched" and check.get("condition") != "其他"
                        for check in activity_participation_checks(activity, user))}


def upcoming_signups(users, now=None, tasks=()):
    """所有未来且报名时间已知的场次（跨账号），按报名时间升序。"""
    now = now or datetime.now()
    candidates = []
    task_map = {event.task_id: event for event in tasks}
    for user in users:
        details = user.get("activity_details") or {}
        for aid in user.get("activity_ids", []):
            info = details.get(str(aid)) or {}
            task = task_map.get(f"{user.get('sid')}:{user.get('userName')}:{aid}")
            if task and task.state in {"success", "failed", "cancelled"}:
                continue
            start = parse_activity_time(task.join_start_time if task and task.join_start_time else info.get("开始报名时间"))
            clock = now + timedelta(seconds=task.server_offset if task else 0)
            if start and start >= clock:
                candidates.append((start, user.get("userName", ""), str(aid), info))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates


def next_signup(users, now=None):
    """从已经获取的详情里选出下一场；未知时间的活动不被猜测为下一场。"""
    upcoming = upcoming_signups(users, now)
    return upcoming[0] if upcoming else None


def countdown(target, now=None):
    remaining = max(0, int((target - (now or datetime.now())).total_seconds()))
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}天 {hours:02d}:{minutes:02d}:{seconds:02d}" if days else f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def overlapping_activities(details, selected):
    """仅比较有明确开始和结束时间的活动；未知时间不作冲突判断。"""
    periods = []
    for aid in selected:
        info = details.get(str(aid)) or {}
        start = parse_activity_time(info.get("活动开始时间"))
        end = parse_activity_time(info.get("活动结束时间"))
        if start and end and end > start:
            periods.append((start, end, str(aid), info.get("活动名称") or f"活动 {aid}"))
    periods.sort()
    overlaps = []
    for i, (start, end, aid, name) in enumerate(periods):
        for other_start, other_end, other_aid, other_name in periods[i + 1:]:
            if other_start >= end:
                break
            if other_end > start:
                overlaps.append((name, other_name))
    return overlaps
