import random
import time
from math import ceil
import requests
from loguru import logger
from typing import Dict, List

from core.headers import HEADERS_GET_SCHOOL, HEADERS_ACTIVITY
from core.pu_api import PuApiError, PuClient, response_data, retry_delay
from core.config import MAX_RETRIES
from core.participation import participation_checks

API = PuClient()


def _post_with_retry(url: str, headers: Dict, json_data: Dict,
                     timeout: int = 10, label: str = "") -> requests.Response:
    return API.request("POST", url, headers=headers, json=json_data, timeout=timeout)


def _post_api(url: str, headers: Dict, json_data: Dict, label: str,
              client: PuClient | None = None) -> Dict:
    if client is not None:
        return client.request("POST", url, headers=headers, json=json_data, parse=response_data)
    for attempt in range(MAX_RETRIES):
        response = _post_with_retry(url, headers, json_data, label=label)
        try:
            return response_data(response)
        except PuApiError as exc:
            if not exc.retryable or attempt + 1 >= MAX_RETRIES:
                raise
            API.wait(retry_delay(response, attempt))


def _get_with_retry(url: str, headers: Dict, timeout: int = 10,
                    label: str = "") -> requests.Response:
    return API.request("GET", url, headers=headers, timeout=timeout)


def _get_api(url: str, headers: Dict) -> Dict:
    for attempt in range(MAX_RETRIES):
        response = _get_with_retry(url, headers)
        try:
            return response_data(response)
        except PuApiError as exc:
            if not exc.retryable or attempt + 1 >= MAX_RETRIES:
                raise
            API.wait(retry_delay(response, attempt))


def login(userData: Dict, client: PuClient | None = None) -> Dict:
    """登录并返回 Token 与真实姓名，保留可供界面显示的失败原因。"""
    if not userData.get("userName") or not userData.get("password"):
        raise PuApiError("本地登录凭据不完整，请重新登录", "auth")
    try:
        sid = int(userData.get("sid"))
    except (TypeError, ValueError) as exc:
        raise PuApiError("学校编号无法确认，请重新选择学校", "format") from exc
    try:
        logger.info(f"用户 {userData['userName']} 开始登录")
        from core.headers import HEADERS_LOGIN

        login_url = PuClient.url("login")
        payload = {
            "userName": userData["userName"],
            "password": userData["password"],
            "sid": sid,
            "device": "pc",
        }
        data = _post_api(login_url, HEADERS_LOGIN, payload,
                         label=f"登录({userData['userName']})", client=client)
        token = data.get("token")
        if token:
            base_info = data.get("baseUserInfo")
            realname = base_info.get("realname") if isinstance(base_info, dict) else None
            year = base_info.get("year") if isinstance(base_info, dict) else None
            logger.info(f"用户 {userData['userName']} 登录成功")
            result = {"token": token, "realname": realname or "", "year": year or ""}
            if isinstance(base_info, dict):
                for field, source in (("college", "collegeName"), ("sex", "sex")):
                    if base_info.get(source) not in (None, ""):
                        result[field] = base_info[source]
            return result
        raise PuApiError("登录成功，但 PU 没有返回 Token", "format")
    except requests.RequestException as exc:
        raise PuApiError("连接 PU 失败，请检查网络后重试", "network") from exc


def get_token_or_raise(userData: Dict, client: PuClient | None = None) -> str:
    """兼容旧调用方；需要姓名的界面请用 login。"""
    return login(userData, client=client)["token"]


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
        schools = _get_api(PuClient.url("schools"), HEADERS_GET_SCHOOL).get("list")
    except requests.RequestException as exc:
        raise PuApiError("获取学校列表失败，请检查网络后重试", "network") from exc
    if not isinstance(schools, list):
        raise PuApiError("学校列表格式已变化", "format")
    try:
        return [{"id": int(item["id"]), "name": item["name"]} for item in schools
                if isinstance(item, dict) and isinstance(item.get("name"), str)
                and school_name in item["name"] and item.get("id") is not None]
    except (ValueError, TypeError) as exc:
        raise PuApiError("学校编号格式已变化", "format") from exc


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
        schools = _get_api(PuClient.url("schools"), HEADERS_GET_SCHOOL).get("list")
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
    type_url = PuClient.url("filters")
    payload = {"key": "eventFilter", "puType": 0}
    headers = PuClient.headers(HEADERS_ACTIVITY, token, sid)
    try:
        result = _post_api(type_url, headers, payload, label="获取活动类型")
        res = []
        data = result.get("list")
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
    headers = PuClient.headers(HEADERS_ACTIVITY, token, sid)
    payload = {"id": int(activity_id)}
    try:
        info = _post_api(PuClient.url("detail"), headers,
                         payload, label=f"获取活动{activity_id}信息").get("baseInfo")
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
    try:
        remaining = max(0, int(info["allowUserCount"]) - int(info["joinUserCount"]))
    except (KeyError, TypeError, ValueError):
        remaining = None
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
        "可报名人数": remaining,
        "参与要求": {key: info[key] for key in ("allowCollege", "allowYears", "allowTribe") if key in info},
    }


def get_user_credit(token: str, sid: int, strict: bool = False) -> Dict:
    """获取用户学分信息"""
    info_url = PuClient.url("user")
    headers = PuClient.headers(HEADERS_ACTIVITY, token, sid)
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
    activity_url = PuClient.url("activities")
    headers = PuClient.headers(HEADERS_ACTIVITY, user.get("token"), user.get("sid"))
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
            items = data.get("list")
            if not isinstance(items, list):
                raise PuApiError("活动列表格式已变化", "format")
            for activity in items:
                if not isinstance(activity, dict) or activity.get("id") is None:
                    raise PuApiError("活动编号格式已变化", "format")
                info = get_info(activity.get("id"), user.get("token"), user.get("sid"),
                                strict=strict)
                if not _is_valid(info, user.get("college", "")):
                    continue
                parsed = get_single_activity(activity.get("id"), info)
                parsed["参与条件"] = participation_checks(info, user)
                activity_list.append(parsed)
        except Exception as e:
            logger.error(f"获取第 {page} 页活动失败: {str(e)}")
            if strict:
                raise

        time.sleep(0.5 + random.random() * 1.5)

    logger.info(f"获取候选活动成功，共 {len(activity_list)} 个；界面将继续核对当前账号的院系和年级")
    return activity_list


def _is_valid(info: Dict, college: str) -> bool:
    """保留尚未开始的活动；满员活动由界面展示并限制勾选。"""
    if not isinstance(info.get("statusName"), str):
        raise PuApiError("活动状态格式已变化，请核对接口", "format")
    if info["statusName"] != "未开始":
        return False
    return True
