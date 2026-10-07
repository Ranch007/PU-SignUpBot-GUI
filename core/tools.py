import random
import time
from math import ceil
import requests
from loguru import logger
from typing import Dict, List

from core.headers import HEADERS_GET_SCHOOL, HEADERS_ACTIVITY
from core.pu_api import PuApiError, response_data

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # 指数退避基数


def _post_with_retry(url: str, headers: Dict, json_data: Dict,
                     timeout: int = 10, label: str = "") -> requests.Response:
    """带重试的 POST 请求，处理 SSL/连接临时故障"""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(url, headers=headers, json=json_data, timeout=timeout)
            return resp
        except (requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** attempt
                logger.warning(
                    f"{label} 网络异常，{wait}s 后重试 "
                    f"({attempt + 1}/{MAX_RETRIES}): {e}"
                )
                time.sleep(wait)
    raise last_error


def _post_api(url: str, headers: Dict, json_data: Dict, label: str) -> Dict:
    try:
        response = _post_with_retry(url, headers, json_data, label=label)
        return response_data(response)
    except requests.RequestException as exc:
        raise PuApiError(f"{label}网络失败，请检查连接后重试", "network") from exc


def _get_with_retry(url: str, headers: Dict, timeout: int = 10,
                    label: str = "") -> requests.Response:
    """带重试的 GET 请求"""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** attempt
                logger.warning(
                    f"{label} 网络异常，{wait}s 后重试 "
                    f"({attempt + 1}/{MAX_RETRIES}): {e}"
                )
                time.sleep(wait)
        except requests.exceptions.HTTPError:
            raise
    raise last_error


def login(userData: Dict) -> Dict:
    """登录并返回 Token 与真实姓名，保留可供界面显示的失败原因。"""
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
        data = _post_api(login_url, HEADERS_LOGIN, payload,
                         label=f"登录({userData['userName']})")
        token = data.get("token")
        if token:
            base_info = data.get("baseUserInfo")
            realname = base_info.get("realname") if isinstance(base_info, dict) else None
            year = base_info.get("year") if isinstance(base_info, dict) else None
            logger.info(f"用户 {userData['userName']} 登录成功")
            return {"token": token, "realname": realname or "", "year": year or ""}
        raise PuApiError("登录成功，但 PU 没有返回 Token", "format")
    except requests.RequestException as exc:
        raise PuApiError("连接 PU 失败，请检查网络后重试", "network") from exc


def get_token_or_raise(userData: Dict) -> str:
    """兼容旧调用方；需要姓名的界面请用 login。"""
    return login(userData)["token"]


def get_token(userData: Dict) -> str | None:
    """兼容旧调用方；需要显示错误原因的界面请用 get_token_or_raise。"""
    try:
        return get_token_or_raise(userData)
    except (PuApiError, KeyError, TypeError, ValueError) as exc:
        logger.warning(f"用户 {userData.get('userName', '未知')} 登录失败: {exc}")
        return None


def get_school_candidates(school_name: str) -> List[Dict]:
    """使用 PU 网页当前的学校列表接口返回完整候选，交给用户确认。"""
    try:
        response = _get_with_retry("https://apis.pocketuni.net/uc/school/list",
                                   HEADERS_GET_SCHOOL, label="获取学校列表")
        schools = response_data(response).get("list")
    except requests.RequestException as exc:
        raise PuApiError("获取学校列表失败，请检查网络后重试", "network") from exc
    if not isinstance(schools, list):
        raise PuApiError("学校列表格式已变化", "format")
    return [{"id": int(item["id"]), "name": item["name"]} for item in schools
            if isinstance(item, dict) and school_name in item.get("name", "")
            and item.get("id") is not None]


def get_sid(school_name: str) -> int | None:
    """兼容旧调用方；新界面使用 get_school_candidates 让用户选择。"""
    try:
        matches = get_school_candidates(school_name)
        return matches[0]["id"] if matches else None
    except (PuApiError, ValueError, KeyError, TypeError) as exc:
        logger.warning(f"获取学校失败: {exc}")
        return None


def get_school_name(sid: int) -> str | None:
    """用 SID 反查学校名称；查不到返回 None。"""
    try:
        response = _get_with_retry("https://apis.pocketuni.net/uc/school/list",
                                   HEADERS_GET_SCHOOL, label="获取学校列表")
        schools = response_data(response).get("list")
        if not isinstance(schools, list):
            return None
        for item in schools:
            if isinstance(item, dict) and int(item.get("id") or -1) == sid:
                return item.get("name")
    except (requests.RequestException, PuApiError, ValueError, TypeError):
        logger.warning(f"SID {sid} 反查学校名称失败")
    return None


def get_activity_type(token: str, sid: str, strict: bool = False) -> List | None:
    """获取本学校的活动类型（参与年级、活动分类、归属院系）"""
    logger.info("开始获取本学校的活动类型")
    type_url = "https://apis.pocketuni.net/apis/mapping/data"
    payload = {"key": "eventFilter", "puType": 0}
    headers = HEADERS_ACTIVITY.copy()
    headers["Authorization"] = f"Bearer {token}:{sid}"
    try:
        result = _post_api(type_url, headers, payload, label="获取活动类型")
        res = []
        data = result.get("list", [])
        if not isinstance(data, list):
            raise PuApiError("活动筛选条件格式已变化", "format")
        for d in data:
            if d.get("name", "未知") in ["活动分类", "参与年级", "归属院系"]:
                res.append(d)
        return res
    except Exception as e:
        logger.error(f"获取活动类型失败: {str(e)}")
        if strict:
            raise
        return None


def get_info(activity_id: str, token: str, sid: str, strict: bool = False) -> Dict:
    """获得单个活动的详细信息"""
    headers = HEADERS_ACTIVITY.copy()
    headers["Authorization"] = f"Bearer {token}:{str(sid)}"
    payload = {"id": int(activity_id)}
    try:
        info = _post_api("https://apis.pocketuni.net/apis/activity/info", headers,
                         payload, label=f"获取活动{activity_id}信息").get("baseInfo", {})
        if not isinstance(info, dict):
            raise PuApiError("活动详情格式已变化", "format")
        return info
    except Exception as e:
        logger.error(f"获取活动信息失败: {str(e)}")
        if strict:
            raise
        return {}


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
        "报名截止时间": info.get("joinEndTime"),
        "活动开始时间": info.get("startTime"),
        "活动结束时间": info.get("endTime"),
        "活动地址": info.get("address"),
        "可报名人数": info.get("allowUserCount", 0) - info.get("joinUserCount", 0),
    }


def get_user_credit(token: str, sid: int, strict: bool = False) -> Dict:
    """获取用户学分信息"""
    info_url = "https://apis.pocketuni.net/apis/user/pc-info"
    headers = HEADERS_ACTIVITY.copy()
    headers["Authorization"] = f"Bearer {token}:{str(sid)}"
    try:
        return _post_api(info_url, headers, {}, label="获取用户学分")
    except Exception as e:
        logger.error(f"获取学分失败: {str(e)}")
        if strict:
            raise
        return {}


def get_allowed_activity_list(user: Dict, strict: bool = False) -> List:
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
        first_data = _post_api(activity_url, headers, payload, label="获取活动列表首页")
    except Exception as e:
        logger.error(f"获取活动列表失败: {str(e)}")
        if strict:
            raise
        return []

    try:
        page_info = first_data.get("pageInfo", {})
        if not isinstance(page_info, dict):
            raise ValueError("pageInfo 不是对象")
        pages = int(page_info.get("total") or 0)
        if pages <= 0 and page_info.get("count") is not None:
            pages = ceil(int(page_info["count"]) / payload["limit"])
        if pages <= 0 and first_data.get("list"):
            pages = 1
    except Exception as e:
        logger.error(f"获取活动列表失败，返回的数据格式错误: {str(e)}")
        if strict:
            raise PuApiError("活动列表分页格式已变化", "format") from e
        return []

    activity_list = []
    for page in range(1, pages + 1):
        payload["page"] = page
        try:
            if page == 1:
                data = first_data
            else:
                data = _post_api(activity_url, headers, payload,
                                 label=f"获取活动列表第{page}页")
            items = data.get("list", [])
            if not isinstance(items, list):
                raise PuApiError("活动列表格式已变化", "format")
            for activity in items:
                info = get_info(activity.get("id"), user.get("token"), user.get("sid"),
                                strict=strict)
                if not _is_valid(info, user.get("college", "")):
                    continue
                activity_list.append(
                    get_single_activity(activity.get("id"), info)
                )
        except Exception as e:
            logger.error(f"获取第 {page} 页活动失败: {str(e)}")
            if strict:
                raise

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
