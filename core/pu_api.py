"""PU 接口响应检查与用户可读的错误分类。"""

from threading import Event, Semaphore
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import requests

from core.config import MAX_REQUESTS, MAX_RETRIES

BASE_URL = "https://apis.pocketuni.net"
ENDPOINTS = {
    "schools": "/uc/school/list",
    "login": "/uc/user/login",
    "user": "/apis/user/pc-info",
    "filters": "/apis/mapping/data",
    "activities": "/apis/activity/list",
    "detail": "/apis/activity/info",
    "join": "/apis/activity/join",
}
GLOBAL_REQUESTS = Semaphore(MAX_REQUESTS)


class PuApiError(Exception):
    def __init__(self, message: str, kind: str = "server", code: int | None = None,
                 retryable: bool | None = None):
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.retryable = (kind in {"network", "rate_limit"} or
                          kind == "http" and code is not None and code >= 500
                          if retryable is None else retryable)


def response_body(response: requests.Response) -> dict:
    """检查 HTTP 与 JSON 格式；报名的业务码由调用方解释。"""
    if response.status_code == 401:
        raise PuApiError("登录信息已过期，请重新登录", "auth", 401)
    if response.status_code == 429:
        raise PuApiError("操作过于频繁，请稍后再试", "rate_limit", 429)
    if response.status_code >= 400:
        raise PuApiError(f"PU 服务请求失败（HTTP {response.status_code}）", "http",
                         response.status_code)
    try:
        body = response.json()
    except ValueError as exc:
        raise PuApiError("PU 返回了无法识别的数据，请核对接口", "format") from exc
    if not isinstance(body, dict) or not isinstance(body.get("code"), int):
        raise PuApiError("PU 返回的数据格式已变化", "format")
    return body


def response_data(response: requests.Response) -> dict:
    """成功时返回 data；HTTP 成功但业务失败时也抛出异常。"""
    body = response_body(response)
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


def retry_delay(response, attempt: int) -> float:
    value = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
    if value:
        try:
            return min(60.0, max(0.0, float(value)))
        except ValueError:
            try:
                target = parsedate_to_datetime(value)
                return min(60.0, max(0.0, (target - datetime.now(timezone.utc)).total_seconds()))
            except (ValueError, TypeError):
                pass
    return min(8.0, float(2 ** attempt))


class PuClient:
    """统一地址、鉴权、超时、可取消排队与重试；等待不占请求名额。"""

    def __init__(self, cancel: Event | None = None, limiter=None):
        self.cancel = cancel or Event()
        self.limiter = limiter if limiter is not None else GLOBAL_REQUESTS

    @staticmethod
    def url(endpoint: str) -> str:
        return BASE_URL + ENDPOINTS[endpoint]

    @staticmethod
    def headers(base: dict, token: str, sid) -> dict:
        return dict(base, Authorization=f"Bearer {token}:{sid}")

    def wait(self, seconds: float):
        if self.cancel.wait(seconds):
            raise PuApiError("操作已取消", "cancelled")

    def once(self, method: str, url: str, *, headers: dict, json=None,
             timeout: float = 10, before_send=None):
        acquired = False
        try:
            while not self.cancel.is_set():
                acquired = self.limiter.acquire(timeout=0.1)
                if acquired:
                    break
            if not acquired or self.cancel.is_set():
                raise PuApiError("操作已取消", "cancelled")
            if before_send:
                before_send()
            if method == "GET":
                return requests.get(url, headers=headers, timeout=timeout)
            return requests.post(url, headers=headers, json=json, timeout=timeout)
        except requests.RequestException as exc:
            # 不把可能带有请求凭据的异常文本写入用户消息。
            raise PuApiError("连接 PU 失败，请检查网络后重试", "network") from exc
        finally:
            if acquired:
                self.limiter.release()

    def request(self, method: str, url: str, *, parse=None, attempts=MAX_RETRIES, **kwargs):
        for attempt in range(attempts):
            response = None
            try:
                response = self.once(method, url, **kwargs)
                if parse:
                    return parse(response)
                if response.status_code >= 400:
                    response_body(response)
                return response
            except PuApiError as exc:
                if not exc.retryable or attempt + 1 >= attempts:
                    raise
                self.wait(retry_delay(response, attempt))

    def call(self, endpoint: str, *, headers: dict, payload=None, **kwargs) -> dict:
        return self.request("GET" if endpoint == "schools" else "POST", self.url(endpoint),
                            headers=headers, json=payload, parse=response_data, **kwargs)
