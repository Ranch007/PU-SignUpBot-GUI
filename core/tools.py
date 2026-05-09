import random
import time
import requests
from loguru import logger
from typing import Dict, List

from core.headers import HEADERS_GET_SCHOOL, HEADERS_ACTIVITY


def get_token(userData: Dict) -> str | None:
    """登录获取 token"""
    try:
        logger.info(f"用户 {userData['userName']} 开始登录")
        from core.headers import HEADERS_LOGIN

        login_url = "https://apis.pocketuni.net/uc/user/login"
        payload = {
            "userName": userData["userName"],
            "password": userData["password"],
            "sid": int(userData.get("sid")),
            "device": "pc",
        }
        response = requests.post(login_url, headers=HEADERS_LOGIN, json=payload)
        response.raise_for_status()

        token = response.json().get("data", {}).get("token")

        if token:
            logger.info(f"用户 {userData['userName']} 登录成功")
            return token
        else:
            logger.error(f"用户 {userData['userName']} 获取Token失败")
            return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"用户 {userData['userName']} 登录失败，HTTP错误: {str(e)}")
        return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f"用户 {userData['userName']} 登录失败，网络错误: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"用户 {userData['userName']} 登录失败，未知错误: {str(e)}")
        return None


def get_sid(school_name: str) -> int | None:
    """根据学校名称模糊搜索获取 SID"""
    logger.info(f"开始获取学校 SID，搜索关键词: {school_name}")

    def _get_school_list() -> Dict:
        url = "https://pocketuni.net/index.php?app=api&mod=Sitelist&act=getSchools"
        response = requests.get(url, headers=HEADERS_GET_SCHOOL)
        return response.json()

    def _find_schools(school_list, name) -> List[Dict]:
        return [s for s in school_list if name in s["name"]]

    school_list = _get_school_list()
    matching = _find_schools(school_list, school_name)

    if not matching:
        logger.warning(f"未找到匹配 '{school_name}' 的学校")
        return None

    if len(matching) == 1:
        selected = matching[0]
        logger.info(f"自动选择学校: {selected['name']}")
    else:
        logger.info(f"找到 {len(matching)} 个匹配学校，默认选第一个")
        selected = matching[0]

    sid = int(selected["go_id"])
    logger.info(f"获取学校 SID 成功: {sid}")
    return sid


def get_activity_type(token: str, sid: str) -> List | None:
    """获取本学校的活动类型（参与年级、活动分类、归属院系）"""
    logger.info("开始获取本学校的活动类型")
    type_url = "https://apis.pocketuni.net/apis/mapping/data"
    payload = {"key": "eventFilter", "puType": 0}
    headers = HEADERS_ACTIVITY.copy()
    headers["Authorization"] = f"Bearer {token}:{sid}"
    try:
        response = requests.post(type_url, headers=headers, json=payload)
        response.raise_for_status()
        res = []
        data = response.json().get("data", {}).get("list", [])
        for d in data:
            if d.get("name", "未知") in ["活动分类", "参与年级", "归属院系"]:
                res.append(d)
        return res
    except requests.exceptions.HTTPError as e:
        logger.error(f"获取活动类型失败，HTTP错误: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"获取活动类型失败，未知错误: {str(e)}")
        return None


def get_info(activity_id: str, token: str, sid: str) -> Dict:
    """获得单个活动的详细信息"""
    headers = HEADERS_ACTIVITY.copy()
    headers["Authorization"] = f"Bearer {token}:{str(sid)}"
    payload = {"id": int(activity_id)}
    try:
        response = requests.post(
            "https://apis.pocketuni.net/apis/activity/info",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"获取活动信息失败，HTTP错误: {str(e)}")
        return {}
    return response.json().get("data", {}).get("baseInfo", {})


def get_single_activity(activity_id: str, info: Dict) -> Dict:
    """筛选获取单个活动的信息"""
    logger.info(f"正在解析活动 {activity_id} 的信息")
    return {
        "activity_id": activity_id,
        "分数": info.get("credit"),
        "活动分类": info.get("categoryName"),
        "举办组织": info.get("creatorName"),
        "活动名称": info.get("name"),
        "开始报名时间": info.get("joinStartTime"),
        "活动开始时间": info.get("startTime"),
        "活动结束时间": info.get("endTime"),
        "活动地址": info.get("address"),
        "可报名人数": info.get("allowUserCount", 0) - info.get("joinUserCount", 0),
    }


def get_allowed_activity_list(user: Dict) -> List:
    """获取满足用户筛选条件的活动列表"""
    logger.info("开始获取满足用户筛选条件的活动")
    activity_url = "https://apis.pocketuni.net/apis/activity/list"
    headers = HEADERS_ACTIVITY.copy()
    headers["Authorization"] = f"Bearer {user.get('token')}:{str(user.get('sid'))}"
    payload = {
        "page": 1,
        "limit": 20,
        "sort": 0,
        "puType": 0,
        "status": 1,
        "isAudit": [0],
    }

    if user.get("categorys"):
        payload["categorys"] = user["categorys"]
    if user.get("allowYears"):
        payload["allowYears"] = user["allowYears"]
    if user.get("oids"):
        payload["oids"] = user["oids"]

    try:
        response = requests.post(activity_url, headers=headers, json=payload)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"获取活动列表失败，HTTP错误: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"获取活动列表失败，未知错误: {str(e)}")
        return []

    try:
        pages = int(response.json().get("data", {}).get("pageInfo", {}).get("total", 0))
    except Exception as e:
        logger.error(f"获取活动列表失败，返回的数据格式错误: {str(e)}")
        return []

    activity_list = []
    for page in range(1, pages + 1):
        payload["page"] = page
        try:
            response = requests.post(activity_url, headers=headers, json=payload)
            response.raise_for_status()
            for activity in response.json().get("data", {}).get("list", []):
                info = get_info(activity.get("id"), user.get("token"), user.get("sid"))
                if not _is_valid(info, user.get("college", "")):
                    continue
                activity_list.append(
                    get_single_activity(activity.get("id"), info)
                )
        except Exception as e:
            logger.error(f"获取第 {page} 页活动失败: {str(e)}")

        time.sleep(0.5 + random.random() * 1.5)

    logger.info(f"获取满足用户筛选条件的活动成功，共 {len(activity_list)} 个")
    return activity_list


def _is_valid(info: Dict, college: str) -> bool:
    """判断当前活动是否满足用户筛选条件"""
    if info.get("allowUserCount", 0) - info.get("joinUserCount", 0) <= 0:
        return False
    if info.get("allowTribe"):
        return False
    if info.get("statusName") != "未开始":
        return False
    if info.get("allowCollege") and college not in [
        t.get("name") for t in info.get("allowCollege", [])
    ]:
        return False
    return True
