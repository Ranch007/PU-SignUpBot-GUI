"""仅按返回的明确参与条件匹配，不把未知条件当作满足。"""

from core.activity_filters import year_matches_option

def participation_checks(info: dict, user: dict) -> list[dict]:
    checks = []
    for field, profile, label in (("allowCollege", "college", "院系"),
                                  ("allowYears", "year", "年级")):
        values = info.get(field)
        if not values:
            continue
        if not isinstance(values, list):
            checks.append({"condition": label, "status": "unknown", "message": f"{label}条件格式需核对"})
            continue
        choices = [str(value.get("name") or (value.get("id", "") if field == "allowYears" else ""))
                   if isinstance(value, dict) else str(value) for value in values]
        choices = [choice for choice in choices if choice]
        actual = user.get(profile)
        if not actual or not choices:
            state, result = "unknown", "资料不足，请在 PU 核对"
        else:
            matched = (any(year_matches_option(actual, value) for value in values)
                       if field == "allowYears" else str(actual) in choices)
            state = "matched" if matched else "mismatch"
            result = "匹配" if state == "matched" else "不匹配"
        checks.append({"condition": label, "status": state,
                       "message": f"{label}：{'、'.join(choices) or '待确认'} · {result}"})
    if info.get("allowTribe"):
        checks.append({"condition": "部落", "status": "unknown", "message": "有部落限制，请在 PU 核对成员资格"})
    checks.append({"condition": "其他", "status": "unknown", "message": "其他参与条件请在 PU 活动详情中核对"})
    return checks


def activity_participation_checks(activity: dict, user: dict) -> list[dict]:
    """有原始条件时按当前账号重新核对，兼容只有匹配结果的旧数据。"""
    if "参与要求" in activity:
        return participation_checks(activity.get("参与要求") or {}, user)
    return activity.get("参与条件") or participation_checks({}, user)


def participation_text(checks: list[dict]) -> str:
    return "\n".join(item["message"] for item in checks)
