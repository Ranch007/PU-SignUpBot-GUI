"""PU 接口响应检查与用户可读的错误分类。"""

import requests


class PuApiError(Exception):
    def __init__(self, message: str, kind: str = "server", code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.code = code


def response_data(response: requests.Response) -> dict:
    """成功时返回 data；HTTP 成功但业务失败时也抛出异常。"""
    if response.status_code == 401:
        raise PuApiError("登录信息已过期，请重新登录", "auth", 401)
    if response.status_code == 429:
        raise PuApiError("操作过于频繁，请稍后再试", "rate_limit", 429)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise PuApiError(f"PU 服务暂时不可用（HTTP {response.status_code}）", "http",
                         response.status_code) from exc
    try:
        body = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise PuApiError("PU 返回了无法识别的数据，请稍后重试", "format") from exc
    if not isinstance(body, dict):
        raise PuApiError("PU 返回的数据格式已变化", "format")
    code = body.get("code")
    if code != 0:
        if code == 401:
            raise PuApiError("登录信息已过期，请重新登录", "auth", code)
        if code in (429, 110110):
            raise PuApiError("操作过于频繁，请稍后再试", "rate_limit", code)
        message = body.get("msg") or body.get("message") or f"服务返回错误码 {code}"
        raise PuApiError(str(message), "server", code)
    data = body.get("data")
    if not isinstance(data, dict):
        raise PuApiError("PU 返回的数据格式已变化", "format")
    return data
