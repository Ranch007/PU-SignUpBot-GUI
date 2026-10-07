import random
import threading
import requests
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple, Callable

from core.headers import HEADERS_ACTIVITY
from core.activity_plan import parse_activity_time
from core.pu_api import PuApiError, response_data
from core.pu_sign import generate_random_echo, current_timestamp_str, generate_x_sign
from loguru import logger


class AccountToken:
    """同一账号的多个活动共享 Token 和刷新锁。"""

    def __init__(self, token: str):
        self.value = token
        self.lock = threading.Lock()


class ActivityBot:
    def __init__(self, userData: Dict, cancel_event: Optional[threading.Event] = None,
                 request_semaphore: Optional[threading.Semaphore] = None,
                 token_state: Optional[AccountToken] = None):
        self.user_data = userData
        self._token_state = token_state or AccountToken(userData.get("token", ""))
        self.cur_token = self._token_state.value
        self.activity_url = "https://apis.pocketuni.net/apis/activity/join"
        self.info_url = "https://apis.pocketuni.net/apis/activity/info"
        self.signup_flags = {}
        self.server_time_offset = 0.0
        self._lock = threading.Lock()
        self._cancel = cancel_event or threading.Event()
        self._request_semaphore = request_semaphore
        self._callback: Optional[Callable] = None
        self._logged_errors: set = set()
        self._refresh_lock = threading.Lock()
        self._fatal_error: Optional[str] = None
        self._join_end_time: Optional[datetime] = None

        if not self.cur_token and not self._cancel.is_set():
            self._refresh_token()

    def abort(self) -> None:
        self._cancel.set()
        logger.warning(f"用户 {self.user_data['userName']} 报名已中止")

    @property
    def _abort(self) -> bool:
        return self._cancel.is_set()

    def _wait(self, seconds: float) -> bool:
        """等待指定时间；取消时立即返回 True。"""
        return self._cancel.wait(max(0.0, seconds))

    def _report(self, state: str, message: str) -> None:
        if self._callback:
            self._callback(state, message)

    def sync_server_time(self, activity_id: str) -> None:
        max_retries = 3
        headers = self._get_headers()
        payload = {"id": int(activity_id)}

        for attempt in range(max_retries):
            if self._abort:
                return
            try:
                start_time = time.time()
                response = requests.post(
                    url=self.info_url, timeout=5, headers=headers, json=payload
                )
                end_time = time.time()
                response.raise_for_status()

                server_time_str = response.headers.get("Date")
                if not server_time_str:
                    raise ValueError("服务器未返回Date头")

                from email.utils import parsedate_to_datetime

                server_time = parsedate_to_datetime(server_time_str)
                if server_time.tzinfo is None:
                    server_time = server_time.replace(tzinfo=timezone.utc)

                network_delay = end_time - start_time
                local_utc_time = datetime.fromtimestamp(
                    start_time + network_delay / 2, tz=timezone.utc
                )
                self.server_time_offset = (server_time - local_utc_time).total_seconds()

                logger.info(
                    f"用户 {self.user_data['userName']} 时间同步成功 "
                    f"(尝试 {attempt + 1}/{max_retries}): "
                    f"偏差={self.server_time_offset:.3f}秒"
                )
                return

            except Exception as e:
                logger.warning(
                    f"用户 {self.user_data['userName']} 时间同步失败 "
                    f"(尝试 {attempt + 1}/{max_retries}): {e}"
                )

            if attempt < max_retries - 1:
                if self._wait(1):
                    return

        logger.error(f"用户 {self.user_data['userName']} 时间同步完全失败")
        self.server_time_offset = 0.0

    def _get_corrected_now(self) -> datetime:
        return datetime.now() + timedelta(seconds=self.server_time_offset)

    def _refresh_token(self) -> bool:
        with self._token_state.lock:
            if self._token_state.value and self._token_state.value != self.cur_token:
                self.cur_token = self._token_state.value
                return True
            return self._login_and_refresh()

    def _login_and_refresh(self) -> bool:
        for attempt in range(5):
            if self._abort:
                return False
            try:
                from core.tools import get_token

                self.cur_token = get_token(self.user_data)
                if self.cur_token:
                    self._token_state.value = self.cur_token
                    logger.info(f"用户 {self.user_data['userName']} Token 刷新成功")
                    return True
                logger.warning(
                    f"用户 {self.user_data['userName']} 第 {attempt + 1} 次 Token 获取失败"
                )
            except Exception as e:
                logger.error(f"用户 {self.user_data['userName']} Token 获取异常: {str(e)}")
            if self._wait(1):
                return False

        logger.error(f"用户 {self.user_data['userName']} Token 获取失败")
        return False

    def _get_headers(self) -> Dict:
        self.cur_token = self._token_state.value
        headers = HEADERS_ACTIVITY.copy()
        headers["Authorization"] = f"Bearer {self.cur_token}:{self.user_data.get('sid')}"
        return headers

    def get_join_start_time(self, activity_id: str) -> Optional[datetime]:
        for retry in range(3):
            if self._abort:
                return None
            try:
                headers = self._get_headers()
                payload = {"id": int(activity_id)}

                response = requests.post(
                    self.info_url, headers=headers, json=payload, timeout=8
                )

                if response.status_code == 401:
                    logger.warning(
                        f"用户 {self.user_data['userName']} Token 失效，尝试刷新"
                    )
                    if self._refresh_token():
                        continue
                    else:
                        break

                try:
                    data = response_data(response)
                except PuApiError as exc:
                    if exc.kind == "auth" and self._refresh_token():
                        continue
                    self._fatal_error = str(exc)
                    break
                base_info = data.get("baseInfo") or {}
                join_start_time_str = base_info.get("joinStartTime")
                self._join_end_time = parse_activity_time(base_info.get("joinEndTime"))
                if self._join_end_time and self._get_corrected_now() >= self._join_end_time:
                    self._fatal_error = "报名已截止"
                    logger.warning("用户 {} 活动 {} 报名已截止", self.user_data['userName'], activity_id)
                    return None

                if join_start_time_str:
                    start_time = datetime.strptime(join_start_time_str, "%Y-%m-%d %H:%M:%S")
                    logger.info(
                        f"用户 {self.user_data['userName']} 活动 {activity_id} 开始时间: {start_time}"
                    )
                    return start_time
                else:
                    logger.warning(
                        f"用户 {self.user_data['userName']} 活动 {activity_id} "
                        "API 响应缺少 joinStartTime 字段"
                    )

            except Exception as e:
                logger.warning(
                    f"用户 {self.user_data['userName']} 获取活动信息失败 (重试 {retry + 1}/3): {e}"
                )
                if retry < 2:
                    if self._wait(2**retry):
                        return None

        logger.error(f"用户 {self.user_data['userName']} 获取活动 {activity_id} 信息最终失败")
        return None

    def _monitor_start_time(
        self,
        activity_id: str,
        start_time: Optional[datetime],
        min_minutes: int = 60,
        max_minutes: int = 60,
        buffer_seconds: int = 600,
    ) -> Optional[datetime]:
        if not start_time:
            return None

        while not self._abort and not self._fatal_error:
            now = self._get_corrected_now()
            time_to_start = (start_time - now).total_seconds()

            if time_to_start <= float(buffer_seconds):
                logger.info(
                    f"用户 {self.user_data['userName']} 活动 {activity_id} 进入最终等待阶段"
                )
                return start_time

            max_allowed_minutes = max(1, int((time_to_start - buffer_seconds) / 60))
            lower = min(min_minutes, max_allowed_minutes)
            upper = min(max_minutes, max_allowed_minutes)

            if upper < 1:
                return start_time

            sleep_minutes = random.randint(max(1, lower), upper)

            self._report("waiting", f"活动将于 {time_to_start / 60:.0f} 分钟后开始，"
                         f"下次检查: {sleep_minutes} 分钟后")

            logger.info(
                f"用户 {self.user_data['userName']} 等待 {sleep_minutes} 分钟后再次确认开始时间"
            )

            if self._wait(sleep_minutes * 60):
                return None

            new_start = self.get_join_start_time(activity_id)
            if new_start and new_start != start_time:
                logger.warning(
                    f"用户 {self.user_data['userName']} 活动 {activity_id} 开始时间变更: "
                    f"{start_time} -> {new_start}"
                )
                start_time = new_start

        return None

    def _precise_wait_until(self, target_time: datetime, advance_ms: int = 50):
        logger.info(
            f"用户 {self.user_data['userName']} 精确等待开始，"
            f"目标: {target_time.strftime('%H:%M:%S.%f')[:-3]}, "
            f"提前 {advance_ms}ms 开始"
        )
        last_log = 0.0
        while not self._abort:
            current_time = self._get_corrected_now()
            remaining = (target_time - current_time).total_seconds()

            if remaining <= advance_ms / 1000.0:
                logger.info(
                    f"用户 {self.user_data['userName']} 已到达目标时间（剩余 {remaining*1000:.0f}ms），开始报名"
                )
                break

            if remaining > 10 and remaining < last_log - 5:
                logger.info(
                    f"用户 {self.user_data['userName']} 距离开始还有 {remaining:.0f} 秒"
                )
                last_log = remaining

            if remaining > 1:
                self._wait(remaining - 0.5)
            elif remaining > 0.1:
                self._wait(0.05)
            else:
                self._wait(0.001)

    def _parse_signup_response(self, response_text: str) -> Tuple[bool, str]:
        try:
            data = json.loads(response_text)
            code = data.get("code")
            message = data.get("message", "")

            if code == 0:
                return True, "报名成功"
            elif code == 9405:
                return True, "已报名"
            else:
                return False, f"报名失败: {message} (code: {code})"
        except json.JSONDecodeError:
            return False, "PU 返回了无法识别的报名结果"

    def _send_signup_request(self, activity_id: str) -> bool:
        if self.signup_flags.get(activity_id) or self._abort:
            return bool(self.signup_flags.get(activity_id))

        acquired = False
        try:
            if self._request_semaphore:
                while not self._abort:
                    acquired = self._request_semaphore.acquire(timeout=0.1)
                    if acquired:
                        break
                if not acquired:
                    return False
            if self._abort or self.signup_flags.get(activity_id):
                return False
            data = {"activityId": int(activity_id)}
            headers = self._get_headers()
            echo = generate_random_echo()
            timestamp = current_timestamp_str()
            headers["X-Sign"] = generate_x_sign(
                echo=echo, timestamp=timestamp, client="web"
            )

            response = requests.post(
                self.activity_url, headers=headers, json=data, timeout=5
            )

            if response.status_code == 401:
                with self._refresh_lock:
                    if self.cur_token == headers["Authorization"].rsplit(":", 1)[0].removeprefix("Bearer "):
                        if not self._refresh_token():
                            self._fatal_error = "登录信息已过期，请重新登录"
                return False
            if response.status_code == 429:
                self._fatal_error = "操作过于频繁，请稍后再试"
                return False
            if response.status_code != 200:
                logger.warning(
                    f"用户 {self.user_data['userName']} 报名请求失败: HTTP {response.status_code}"
                )
                return False

            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("code") in (401, 429, 110110):
                code = body["code"]
                if code == 401:
                    with self._refresh_lock:
                        if self.cur_token == headers["Authorization"].rsplit(":", 1)[0].removeprefix("Bearer "):
                            if not self._refresh_token():
                                self._fatal_error = "登录信息已过期，请重新登录"
                else:
                    self._fatal_error = "操作过于频繁，请稍后再试"
                return False
            success, status_msg = self._parse_signup_response(response.text)

            if success:
                with self._lock:
                    if not self.signup_flags.get(activity_id):
                        self.signup_flags[activity_id] = True
                        logger.success(
                            f"用户 {self.user_data['userName']} 活动 {activity_id} {status_msg}！"
                        )
                        self._report("success", f"活动 {activity_id} {status_msg}")
                return True
            else:
                if status_msg not in self._logged_errors:
                    self._logged_errors.add(status_msg)
                    logger.warning(f"用户 {self.user_data['userName']} 报名响应: {status_msg}")
                return False

        except requests.exceptions.Timeout:
            logger.warning(f"用户 {self.user_data['userName']} 报名请求超时")
            return False
        except Exception as e:
            logger.error(f"用户 {self.user_data['userName']} 报名请求异常: {str(e)}")
            return False
        finally:
            if acquired:
                self._request_semaphore.release()

    def signup(self, activity_id: str, callback: Optional[Callable] = None):
        self._callback = callback
        logger.info(f"用户 {self.user_data['userName']} 开始报名活动 {activity_id}")

        if not self.cur_token and not self._refresh_token():
            logger.error(f"用户 {self.user_data['userName']} 无法获取有效 Token")
            self._report("cancelled" if self._abort else "failed",
                         "报名已取消" if self._abort else "无法获取有效 Token")
            return

        start_time = self.get_join_start_time(activity_id)
        if not start_time:
            logger.error(f"用户 {self.user_data['userName']} 无法获取活动 {activity_id} 开始时间")
            self._report("cancelled" if self._abort else "failed",
                         "报名已取消" if self._abort else
                         (self._fatal_error or f"无法获取活动 {activity_id} 开始时间"))
            return

        monitored_start_time = self._monitor_start_time(activity_id, start_time)
        if not monitored_start_time:
            self._report("cancelled" if self._abort else "failed",
                         "监视已中止" if self._abort else
                         (self._fatal_error or "无法继续监控活动开始时间"))
            return

        current_time = self._get_corrected_now()
        time_to_start = (monitored_start_time - current_time).total_seconds()
        logger.info(
            f"用户 {self.user_data['userName']} 活动 {activity_id} 距离开始: {time_to_start:.1f} 秒"
        )

        if time_to_start > 60:
            sleep_time = time_to_start - 60
            logger.info(
                f"用户 {self.user_data['userName']} 等待 {sleep_time:.1f} 秒到活动开始前 60 秒"
            )
            self._report("waiting", f"距离报名还有 {time_to_start:.0f} 秒")
            if self._wait(sleep_time):
                self._report("cancelled", "报名已取消")
                return
            if not self._refresh_token():
                self._report("cancelled" if self._abort else "failed",
                             "报名已取消" if self._abort else "无法刷新登录信息，请重新登录")
                return

        logger.info(f"用户 {self.user_data['userName']} 进入精确等待阶段")
        self._report("waiting", "正在等待报名开始")
        self._precise_wait_until(monitored_start_time, advance_ms=30)

        if self._abort:
            self._report("cancelled", "报名已中止")
            return

        if self._join_end_time and self._get_corrected_now() >= self._join_end_time:
            self._report("failed", "报名已截止")
            return

        self._report("joining", "正在提交报名请求")
        self._start_signup_threads(activity_id)

    def _start_signup_threads(self, activity_id: str):
        from concurrent.futures import ThreadPoolExecutor

        logger.info(f"用户 {self.user_data['userName']} 开始多线程报名活动 {activity_id}")

        max_workers = 8
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []

            logger.info("▶ 第一轮快速报名（5 线程并发）")
            futures.extend(
                [executor.submit(self._signup_worker, activity_id) for _ in range(5)]
            )
            for f in futures:
                try:
                    f.result(timeout=2)
                except Exception:
                    pass
            if self._abort or self._fatal_error:
                self._report("cancelled" if self._abort else "failed",
                             "报名已中止" if self._abort else self._fatal_error)
                return
            if self.signup_flags.get(activity_id):
                logger.success(f"用户 {self.user_data['userName']} 第一轮报名成功！")
                return
            logger.info("第一轮完成，未成功，进入第二轮...")

            logger.info("▶ 第二轮密集报名（15 线程，间隔 0.4s）")
            r2 = []
            for _ in range(15):
                if self.signup_flags.get(activity_id) or self._abort or self._fatal_error:
                    break
                r2.append(executor.submit(self._signup_worker, activity_id))
                if self._wait(0.4):
                    break
            for f in r2:
                try:
                    f.result(timeout=2)
                except Exception:
                    pass
            if self._abort or self._fatal_error:
                self._report("cancelled" if self._abort else "failed",
                             "报名已中止" if self._abort else self._fatal_error)
                return
            if self.signup_flags.get(activity_id):
                logger.success(f"用户 {self.user_data['userName']} 第二轮报名成功！")
                return
            logger.info("第二轮完成，未成功，进入第三轮...")

            logger.info("▶ 第三轮持续报名（45 线程，间隔 0.8s）")
            r3 = []
            for _ in range(45):
                if self.signup_flags.get(activity_id) or self._abort or self._fatal_error:
                    break
                r3.append(executor.submit(self._signup_worker, activity_id))
                if self._wait(0.8):
                    break
            for f in r3:
                try:
                    f.result(timeout=2)
                except Exception:
                    pass

            if self.signup_flags.get(activity_id, False):
                logger.success(
                    f"用户 {self.user_data['userName']} 活动 {activity_id} 报名成功！"
                )
                self._report("success", f"活动 {activity_id} 报名成功")
            else:
                logger.error(
                    f"用户 {self.user_data['userName']} 活动 {activity_id} 三轮报名均失败"
                )
                self._report("cancelled" if self._abort else "failed",
                             "报名已中止" if self._abort else
                             (self._fatal_error or f"活动 {activity_id} 报名失败"))

    def _signup_worker(self, activity_id: str) -> bool:
        max_attempts = 5

        for _ in range(max_attempts):
            if self.signup_flags.get(activity_id) or self._abort or self._fatal_error:
                return True

            try:
                if self._send_signup_request(activity_id):
                    return True
                if self._wait(0.01):
                    return False
            except Exception as e:
                logger.error(f"用户 {self.user_data['userName']} 报名线程异常: {str(e)}")
                if self._wait(0.1):
                    return False

        return False
