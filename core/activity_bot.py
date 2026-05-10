import random
import threading
import requests
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple, Callable

from core.headers import HEADERS_ACTIVITY, HEADERS_ACTIVITY_INFO
from core.pu_sign import generate_random_echo, current_timestamp_str, generate_x_sign
from loguru import logger


class ActivityBot:
    def __init__(self, userData: Dict):
        self.user_data = userData
        self.cur_token = userData.get("token", "")
        self.activity_url = "https://apis.pocketuni.net/apis/activity/join"
        self.info_url = "https://apis.pocketuni.net/apis/activity/info"
        self.signup_flags = {}
        self.server_time_offset = 0.0
        self._lock = threading.Lock()
        self._abort = False
        self._callback: Optional[Callable] = None

        if not self.cur_token:
            self._refresh_token()

    def abort(self) -> None:
        self._abort = True
        logger.warning(f"用户 {self.user_data['userName']} 报名已中止")

    def sync_server_time(self, activity_id: str) -> None:
        max_retries = 3
        headers = HEADERS_ACTIVITY.copy()
        headers["Authorization"] = f"Bearer {self.cur_token}:{self.user_data.get('sid')}"
        payload = {"id": int(activity_id)}

        for attempt in range(max_retries):
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
                time.sleep(1)

        logger.error(f"用户 {self.user_data['userName']} 时间同步完全失败")
        self.server_time_offset = 0.0

    def _get_corrected_now(self) -> datetime:
        return datetime.now() + timedelta(seconds=self.server_time_offset)

    def _refresh_token(self) -> bool:
        for attempt in range(5):
            try:
                from core.tools import get_token

                self.cur_token = get_token(self.user_data)
                if self.cur_token:
                    logger.info(f"用户 {self.user_data['userName']} Token 刷新成功")
                    return True
                logger.warning(
                    f"用户 {self.user_data['userName']} 第 {attempt + 1} 次 Token 获取失败"
                )
            except Exception as e:
                logger.error(f"用户 {self.user_data['userName']} Token 获取异常: {str(e)}")
            time.sleep(1)

        logger.error(f"用户 {self.user_data['userName']} Token 获取失败")
        return False

    def _get_headers(self) -> Dict:
        headers = HEADERS_ACTIVITY.copy()
        headers["Authorization"] = f"Bearer {self.cur_token}:{self.user_data.get('sid')}"
        return headers

    def get_join_start_time(self, activity_id: str) -> Optional[datetime]:
        for retry in range(3):
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

                response.raise_for_status()
                data = response.json()
                join_start_time_str = data.get("data", {}).get("baseInfo", {}).get(
                    "joinStartTime"
                )

                if join_start_time_str:
                    start_time = datetime.strptime(join_start_time_str, "%Y-%m-%d %H:%M:%S")
                    logger.info(
                        f"用户 {self.user_data['userName']} 活动 {activity_id} 开始时间: {start_time}"
                    )
                    return start_time
                else:
                    logger.warning(
                        f"用户 {self.user_data['userName']} 活动 {activity_id} "
                        f"API 响应缺少 joinStartTime 字段, data={data.get('data')}"
                    )

            except Exception as e:
                logger.warning(
                    f"用户 {self.user_data['userName']} 获取活动信息失败 (重试 {retry + 1}/3): {e}"
                )
                if retry < 2:
                    time.sleep(2**retry)

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

        while not self._abort:
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

            if self._callback:
                self._callback(
                    "monitor",
                    f"活动 {activity_id} 将于 {time_to_start / 60:.0f} 分钟后开始，"
                    f"下次检查: {sleep_minutes} 分钟后",
                )

            logger.info(
                f"用户 {self.user_data['userName']} 等待 {sleep_minutes} 分钟后再次确认开始时间"
            )

            time.sleep(sleep_minutes * 60)

            new_start = self.get_join_start_time(activity_id)
            if new_start and new_start != start_time:
                logger.warning(
                    f"用户 {self.user_data['userName']} 活动 {activity_id} 开始时间变更: "
                    f"{start_time} -> {new_start}"
                )
                start_time = new_start

        return None

    def _precise_wait_until(self, target_time: datetime, advance_ms: int = 50):
        while not self._abort:
            current_time = self._get_corrected_now()
            remaining = (target_time - current_time).total_seconds()

            if remaining <= advance_ms / 1000.0:
                break

            if remaining > 1:
                time.sleep(remaining - 0.5)
            elif remaining > 0.1:
                time.sleep(0.05)
            else:
                time.sleep(0.001)

    def _parse_signup_response(self, response_text: str) -> Tuple[bool, str]:
        try:
            data = json.loads(response_text)
            code = data.get("code")
            message = data.get("message", "")

            if code == 0 and ("成功" in message or "报名成功" in str(data)):
                return True, "报名成功"
            elif code == 9405 or "您已报名" in response_text:
                return True, "已报名"
            else:
                return False, f"报名失败: {message} (code: {code})"
        except json.JSONDecodeError:
            if "报名成功" in response_text:
                return True, "报名成功"
            elif "您已报名" in response_text:
                return True, "已报名"
            else:
                return False, f"未知响应: {response_text[:100]}"

    def _send_signup_request(self, activity_id: str) -> bool:
        if self.signup_flags.get(activity_id):
            return True

        try:
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

            if response.status_code != 200:
                logger.warning(
                    f"用户 {self.user_data['userName']} 报名请求失败: HTTP {response.status_code}"
                )
                return False

            success, status_msg = self._parse_signup_response(response.text)

            if success:
                with self._lock:
                    if not self.signup_flags.get(activity_id):
                        self.signup_flags[activity_id] = True
                        logger.success(
                            f"用户 {self.user_data['userName']} 活动 {activity_id} {status_msg}！"
                        )
                        if self._callback:
                            self._callback("success", f"活动 {activity_id} {status_msg}")
                return True
            else:
                logger.warning(f"用户 {self.user_data['userName']} 报名响应: {status_msg}")
                return False

        except requests.exceptions.Timeout:
            logger.warning(f"用户 {self.user_data['userName']} 报名请求超时")
            return False
        except Exception as e:
            logger.error(f"用户 {self.user_data['userName']} 报名请求异常: {str(e)}")
            return False

    def signup(self, activity_id: str, callback: Optional[Callable] = None):
        self._callback = callback
        logger.info(f"用户 {self.user_data['userName']} 开始报名活动 {activity_id}")

        if not self.cur_token and not self._refresh_token():
            logger.error(f"用户 {self.user_data['userName']} 无法获取有效 Token")
            if self._callback:
                self._callback("error", "无法获取有效 Token")
            return

        start_time = self.get_join_start_time(activity_id)
        if not start_time:
            logger.error(f"用户 {self.user_data['userName']} 无法获取活动 {activity_id} 开始时间")
            if self._callback:
                self._callback("error", f"无法获取活动 {activity_id} 开始时间")
            return

        monitored_start_time = self._monitor_start_time(activity_id, start_time)
        if not monitored_start_time:
            if self._callback:
                self._callback("aborted", "监视已中止")
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
            time.sleep(max(0.0, sleep_time))
            self._refresh_token()

        logger.info(f"用户 {self.user_data['userName']} 进入精确等待阶段")
        self._precise_wait_until(monitored_start_time, advance_ms=30)

        if self._abort:
            if self._callback:
                self._callback("aborted", "报名已中止")
            return

        self._start_signup_threads(activity_id)

    def _start_signup_threads(self, activity_id: str):
        from concurrent.futures import ThreadPoolExecutor

        logger.info(f"用户 {self.user_data['userName']} 开始多线程报名活动 {activity_id}")

        max_workers = 8
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []

            logger.info("启动第一轮快速报名...")
            futures.extend(
                [executor.submit(self._signup_worker, activity_id) for _ in range(5)]
            )

            logger.info("启动第二轮密集报名...")
            for _ in range(15):
                if self.signup_flags.get(activity_id) or self._abort:
                    break
                futures.append(executor.submit(self._signup_worker, activity_id))
                time.sleep(0.4)

            logger.info("启动第三轮持续报名...")
            for _ in range(45):
                if self.signup_flags.get(activity_id) or self._abort:
                    break
                futures.append(executor.submit(self._signup_worker, activity_id))
                time.sleep(0.8)

            for future in futures:
                try:
                    future.result(timeout=2)
                except Exception:
                    pass

            if self.signup_flags.get(activity_id, False):
                logger.success(
                    f"用户 {self.user_data['userName']} 活动 {activity_id} 报名成功！"
                )
                if self._callback:
                    self._callback("success", f"活动 {activity_id} 报名成功")
            else:
                logger.error(
                    f"用户 {self.user_data['userName']} 活动 {activity_id} 报名失败"
                )
                if self._callback:
                    self._callback("fail", f"活动 {activity_id} 报名失败")

    def _signup_worker(self, activity_id: str) -> bool:
        max_attempts = 5

        for _ in range(max_attempts):
            if self.signup_flags.get(activity_id) or self._abort:
                return True

            try:
                if self._send_signup_request(activity_id):
                    return True
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"用户 {self.user_data['userName']} 报名线程异常: {str(e)}")
                time.sleep(0.1)

        return False
