"""独立报名任务：可取消等待、共享请求限制和有界错误恢复。"""
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor

import requests  # 模拟测试的 patch 入口；请求统一经 PuClient。
from loguru import logger

from core.config import MAX_RETRIES
from core.participation import participation_checks
from core.headers import HEADERS_ACTIVITY
from core.activity_plan import parse_activity_time
from core.pu_api import PuApiError, PuClient, response_body, response_data, retry_delay
from core.pu_sign import generate_random_echo, current_timestamp_str, generate_x_sign


class AccountToken:
    def __init__(self, token):
        self.value = token
        self.lock = threading.Lock()
        self.refreshed_at = 0.0


class ActivityBot:
    def __init__(self, userData, cancel_event=None, request_semaphore=None, token_state=None):
        self.user_data = userData
        self._token_state = token_state or AccountToken(userData.get("token", ""))
        self.cur_token = self._token_state.value
        self.activity_url = PuClient.url("join")
        self.info_url = PuClient.url("detail")
        self.signup_flags = {}
        self.server_time_offset = 0.0
        self._lock = threading.Lock()
        self._cancel = cancel_event or threading.Event()
        self._client = PuClient(self._cancel, request_semaphore)
        self._callback = None
        self._fatal_error = None
        self.failure = None
        self._join_end_time = None
        self.join_start_time = None
        self._cooldown_until = 0.0
        self._transient_failures = 0
        self._auth_failures = 0
        self._refresh_lock = threading.Lock()

    def abort(self):
        self._cancel.set()

    @property
    def _abort(self):
        return self._cancel.is_set()

    def _wait(self, seconds):
        return self._cancel.wait(max(0.0, seconds))

    def _report(self, state, message):
        if self._callback:
            self._callback(state, message)

    def _fail(self, error):
        with self._lock:
            if not self._fatal_error:
                self.failure = error
                self._fatal_error = str(error)

    def sync_server_time(self, activity_id):
        try:
            start = time.time()
            response = self._client.request("POST", self.info_url, timeout=5,
                headers=self._get_headers(), json={"id": int(activity_id)})
            end = time.time()
            value = getattr(response, "headers", {}).get("Date")
            if value:
                server = parsedate_to_datetime(value)
                if server.tzinfo is None:
                    server = server.replace(tzinfo=timezone.utc)
                local = datetime.fromtimestamp((start + end) / 2, timezone.utc)
                self.server_time_offset = (server - local).total_seconds()
        except (PuApiError, ValueError, TypeError) as exc:
            logger.warning("服务器对时未完成：{}", exc)
            self.server_time_offset = 0.0

    def _get_corrected_now(self):
        return datetime.now() + timedelta(seconds=self.server_time_offset)

    def _refresh_token(self, proactive=False, rejected=None):
        with self._token_state.lock:
            if self._abort:
                return False
            previous = self.cur_token if rejected is None else rejected
            if (self._token_state.value and self._token_state.value != previous or
                    proactive and time.monotonic() - self._token_state.refreshed_at < 60):
                self.cur_token = self._token_state.value
                return bool(self.cur_token)
            return self._login_and_refresh()

    def _login_and_refresh(self):
        from core.tools import get_token_or_raise
        try:
            self.cur_token = get_token_or_raise(self.user_data, client=self._client)
            self._token_state.value = self.cur_token
            self._token_state.refreshed_at = time.monotonic()
            return True
        except PuApiError as exc:
            self._fail(exc)
            return False

    def _get_headers(self):
        self.cur_token = self._token_state.value
        return PuClient.headers(HEADERS_ACTIVITY, self.cur_token, self.user_data.get("sid"))

    def get_join_start_time(self, activity_id):
        for attempt in range(2):
            try:
                headers = self._get_headers()
                data = self._client.request("POST", self.info_url, headers=headers,
                    json={"id": int(activity_id)}, timeout=8, parse=response_data)
                info = data.get("baseInfo")
                if not isinstance(info, dict):
                    raise PuApiError("活动详情格式已变化", "format")
                start = parse_activity_time(info.get("joinStartTime"))
                if not start:
                    raise PuApiError("无法确认报名开始时间，请查看活动详情", "format")
                self.join_start_time = start
                self._join_end_time = parse_activity_time(info.get("joinEndTime"))
                if info.get("joinEndTime") and not self._join_end_time:
                    raise PuApiError("无法确认报名截止时间，请查看活动详情", "format")
                if self._join_end_time and self._get_corrected_now() >= self._join_end_time:
                    raise PuApiError("报名已截止", "closed")
                if info.get("isJoin") is True:
                    self.signup_flags[activity_id] = True
                    return start
                if info.get("statusName") in {"已结束", "已取消"}:
                    raise PuApiError(f"活动{info['statusName']}", "closed")
                mismatches = [check["message"] for check in participation_checks(info, self.user_data)
                              if check["status"] == "mismatch"]
                if mismatches:
                    raise PuApiError("；".join(mismatches), "eligibility")
                if info.get("allowUserCount") is not None and info.get("joinUserCount") is not None:
                    if int(info["allowUserCount"]) <= int(info["joinUserCount"]):
                        raise PuApiError("活动名额已满，请查看详情", "eligibility")
                self._report("waiting", f"已确认报名时间：{start:%m-%d %H:%M:%S}")
                return start
            except PuApiError as exc:
                if exc.kind == "auth" and attempt == 0 and self._refresh_token(
                        rejected=headers["Authorization"].rsplit(":", 1)[0].removeprefix("Bearer ")):
                    continue
                self._fail(exc)
                return None
            except (ValueError, TypeError):
                self._fail(PuApiError("活动时间或名额格式已变化，请查看详情", "format"))
                return None
        return None

    def _monitor_start_time(self, activity_id, start_time, min_minutes=60,
                            max_minutes=60, buffer_seconds=60):
        if not start_time:
            return None
        while not self._abort and not self._fatal_error:
            remaining = (start_time - self._get_corrected_now()).total_seconds()
            if remaining <= buffer_seconds:
                return start_time
            interval = min(15 if remaining <= 600 else 60, remaining - buffer_seconds)
            self._report("waiting", f"距离报名还有 {remaining:.0f} 秒")
            if self._wait(interval):
                return None
            updated = self.get_join_start_time(activity_id)
            if updated:
                start_time = updated
            if self.signup_flags.get(activity_id):
                return start_time
        return None

    def _precise_wait_until(self, target_time, advance_ms=0):
        while not self._abort and not self._fatal_error:
            remaining = (target_time - self._get_corrected_now()).total_seconds()
            if remaining <= advance_ms / 1000:
                return
            self._wait(min(1.0, remaining))

    def _parse_signup_response(self, response_text):
        try:
            data = json.loads(response_text)
            if not isinstance(data, dict) or not isinstance(data.get("code"), int):
                raise ValueError()
            if data["code"] in (0, 9405):
                return True, "已报名" if data["code"] == 9405 else "报名成功"
            return False, f"报名失败：{data.get('msg') or data.get('message') or '服务拒绝'}（code: {data['code']}）"
        except (ValueError, TypeError):
            return False, "PU 返回了无法识别的报名结果"

    def _preflight(self, activity_id):
        if self._abort:
            raise PuApiError("报名已取消", "cancelled")
        if self.signup_flags.get(activity_id):
            raise PuApiError("已报名", "done")
        if self._fatal_error:
            raise self.failure or PuApiError(self._fatal_error)
        if self._join_end_time and self._get_corrected_now() >= self._join_end_time:
            raise PuApiError("报名已截止", "closed")
        if time.monotonic() < self._cooldown_until:
            raise PuApiError("正在等待限流退避", "deferred", retryable=True)

    def _send_signup_request(self, activity_id):
        response = None
        headers = None
        try:
            delay = self._cooldown_until - time.monotonic()
            if self._join_end_time:
                delay = min(delay, max(0, (self._join_end_time - self._get_corrected_now()).total_seconds()))
            if delay > 0 and self._wait(delay):
                return False
            self._preflight(activity_id)
            headers = self._get_headers()
            headers["X-Sign"] = generate_x_sign(echo=generate_random_echo(),
                timestamp=current_timestamp_str(), client="web")
            response = self._client.once("POST", self.activity_url, headers=headers,
                json={"activityId": int(activity_id)}, timeout=5,
                before_send=lambda: self._preflight(activity_id))
            body = response_body(response)
            code = body["code"]
            if code == 401:
                raise PuApiError("登录信息已过期，请重新登录", "auth", code)
            if code in (429, 110110):
                raise PuApiError("操作过于频繁，请稍后再试", "rate_limit", code)
            if code not in (0, 9405):
                raise PuApiError(f"报名失败：{body.get('msg') or body.get('message') or '服务拒绝'}（code: {code}）",
                    "business", code)
            with self._lock:
                self.signup_flags[activity_id] = True
                self.failure = None
            self._report("success", "已报名" if code == 9405 else "报名成功")
            return True
        except PuApiError as exc:
            if exc.kind in {"cancelled", "done", "deferred"}:
                return exc.kind == "done"
            if exc.kind == "auth" and headers is not None:
                with self._lock:
                    self._auth_failures += 1
                    exhausted = self._auth_failures >= MAX_RETRIES
                if exhausted:
                    self._fail(exc)
                    return False
                with self._refresh_lock:
                    rejected = headers["Authorization"].rsplit(":", 1)[0].removeprefix("Bearer ")
                    if self._refresh_token(rejected=rejected):
                        return False
            elif exc.retryable:
                with self._lock:
                    self._transient_failures += 1
                    self.failure = exc
                    exhausted = self._transient_failures >= MAX_RETRIES
                    self._cooldown_until = max(self._cooldown_until,
                        time.monotonic() + retry_delay(response, self._transient_failures - 1))
                if not exhausted:
                    self._report("joining", f"{exc}；稍后有限重试")
                    return False
            self._fail(exc)
            return False

    def signup(self, activity_id, callback=None):
        self._callback = callback
        if not self.cur_token and not self._refresh_token():
            self._finish(activity_id)
            return
        start = self.get_join_start_time(activity_id)
        if self.signup_flags.get(activity_id):
            self._report("success", "已报名")
            return
        if not start:
            self._finish(activity_id)
            return
        start = self._monitor_start_time(activity_id, start)
        if not start or self.signup_flags.get(activity_id):
            self._finish(activity_id)
            return
        if self.user_data.get("password") and not self._refresh_token(proactive=True):
            self._finish(activity_id)
            return
        while not self._abort and not self._fatal_error:
            remaining = (start - self._get_corrected_now()).total_seconds()
            if remaining <= 2:
                self._precise_wait_until(start)
                break
            if self._wait(min(15, remaining - 2)):
                break
            start = self.get_join_start_time(activity_id)
            if not start or self.signup_flags.get(activity_id):
                break
        if self._abort or self._fatal_error or self.signup_flags.get(activity_id):
            self._finish(activity_id)
            return
        self._report("joining", "正在提交报名请求")
        self._start_signup_threads(activity_id)

    def _finish(self, activity_id):
        if self.signup_flags.get(activity_id):
            self.failure = None
            self._report("success", "报名成功")
        elif self._abort:
            self._report("cancelled", "报名已取消")
        else:
            self._report("failed", self._fatal_error or str(self.failure or "报名未完成，请查看详情"))

    def _start_signup_threads(self, activity_id):
        # 最终结果要等在途请求结束，不能用等待 future 的短超时提前认定失败。
        with ThreadPoolExecutor(max_workers=8) as executor:
            for count, interval in ((5, 0), (15, .4), (45, .8)):
                futures = []
                for _ in range(count):
                    if self._abort or self._fatal_error or self.signup_flags.get(activity_id):
                        break
                    futures.append(executor.submit(self._signup_worker, activity_id))
                    if interval and self._wait(interval):
                        break
                for future in futures:
                    try:
                        future.result()
                    except Exception:
                        self._fail(PuApiError("报名任务异常，请查看详情", "internal"))
                if self._abort or self._fatal_error or self.signup_flags.get(activity_id):
                    break
        self._finish(activity_id)

    def _signup_worker(self, activity_id):
        for _ in range(MAX_RETRIES + 1):
            if self.signup_flags.get(activity_id):
                return True
            if self._abort or self._fatal_error:
                return False
            if self._send_signup_request(activity_id):
                return True
            if self._wait(.01):
                return False
        return False
