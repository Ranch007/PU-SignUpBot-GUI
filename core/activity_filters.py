"""活动筛选默认值：将当前账号年级映射到该校返回的选项。"""

import re


def _grade(value):
    match = re.fullmatch(r"(?:20)?(\d{2})(?:\s*[级年])?", str(value or "").strip())
    return match.group(1) if match else None


def year_matches_option(year, option):
    """兼容年级 ID 及 25／2025／2025级，并支持学校自有选项 ID。"""
    if year in (None, ""):
        return False
    option = option if isinstance(option, dict) else {"id": option}
    actual = str(year).strip()
    if option.get("id") is not None and actual == str(option["id"]):
        return True
    grade = _grade(actual)
    return grade is not None and grade == (_grade(option.get("name")) or _grade(option.get("id")))


def default_year_filter_ids(user, options):
    """只按当前账号的年级勾选，不合并其他账号的资料。"""
    selected = set()
    for option in options:
        if option.get("id") is None:
            continue
        option_id = str(option["id"])
        if year_matches_option(user.get("year"), option):
            selected.add(option_id)
    return selected
