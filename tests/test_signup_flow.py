"""不连接 PU 的任务调度与响应回归测试。"""

import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from core.activity_bot import ActivityBot
from core.activity_plan import activity_is_full, visible_activities
from core.pu_api import PuApiError, response_data
from core.signup_tasks import SignupTasks
from core.tools import (get_allowed_activity_list, get_school_candidates,
                        get_school_name, get_single_activity, get_token_or_raise,
                        login)


class Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body
        self.text = ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("非预期的 HTTP 错误")


class FakeBot:
    first_started = threading.Event()

    def __init__(self, user, cancel_event=None, request_semaphore=None, token_state=None):
        self.cancel_event = cancel_event

    def sync_server_time(self, activity_id):
        pass

    def signup(self, activity_id, callback=None):
        if activity_id == "1":
            self.first_started.set()
            self.cancel_event.wait(2)
            callback("cancelled", "已取消")
        else:
            callback("success", "报名成功")


def wait_for_state(tasks, task_id, state, timeout=2):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        match = next((event for event in tasks.snapshot() if event.task_id == task_id), None)
        if match and match.state == state:
            return match
        time.sleep(0.01)
    raise AssertionError(f"任务 {task_id} 未进入 {state} 状态")


class SignupFlowTests(unittest.TestCase):
    def test_later_task_runs_while_earlier_task_waits_and_cancel_wakes_it(self):
        FakeBot.first_started.clear()
        tasks = SignupTasks()
        users = [{"sid": 1, "userName": "student", "activity_ids": ["1", "12"]}]
        with patch("core.signup_tasks.ActivityBot", FakeBot):
            self.assertEqual(tasks.start(users), 2)
            self.assertTrue(FakeBot.first_started.wait(1))
            first = tasks.task_id(users[0], "1")
            second = tasks.task_id(users[0], "12")
            self.assertEqual(wait_for_state(tasks, second, "success").activity_id, "12")
            self.assertTrue(tasks.cancel(first))
            self.assertEqual(wait_for_state(tasks, first, "cancelled").activity_id, "1")
            self.assertEqual(wait_for_state(tasks, second, "success").state, "success")

    def test_same_activity_for_two_accounts_has_distinct_tasks(self):
        tasks = SignupTasks()
        users = [
            {"sid": 1, "userName": "a", "activity_ids": ["12"]},
            {"sid": 1, "userName": "b", "activity_ids": ["12"]},
        ]
        with patch("core.signup_tasks.ActivityBot", FakeBot):
            self.assertEqual(tasks.start(users), 2)
            self.assertEqual(len({event.task_id for event in tasks.snapshot()}), 2)

    def test_successful_activity_is_not_started_again(self):
        tasks = SignupTasks()
        user = {"sid": 1, "userName": "student", "activity_ids": ["12"]}
        with patch("core.signup_tasks.ActivityBot", FakeBot):
            self.assertEqual(tasks.start([user]), 1)
            wait_for_state(tasks, tasks.task_id(user, "12"), "success")
            self.assertEqual(tasks.start([user]), 0)

    def test_removing_one_account_cancels_only_its_tasks(self):
        tasks = SignupTasks()
        users = [
            {"sid": 1, "userName": "a", "activity_ids": ["1"]},
            {"sid": 1, "userName": "b", "activity_ids": ["1"]},
        ]
        with patch("core.signup_tasks.ActivityBot", FakeBot):
            tasks.start(users)
            tasks.cancel_account(1, "a")
            wait_for_state(tasks, tasks.task_id(users[0], "1"), "cancelled")
            self.assertNotEqual(
                next(event.state for event in tasks.snapshot()
                     if event.task_id == tasks.task_id(users[1], "1")), "cancelled")
            tasks.cancel_all()
            wait_for_state(tasks, tasks.task_id(users[1], "1"), "cancelled")

    def test_business_auth_error_is_not_empty_data(self):
        with self.assertRaises(PuApiError) as caught:
            response_data(Response(body={"code": 401, "message": "expired"}))
        self.assertEqual(caught.exception.kind, "auth")
        self.assertEqual(response_data(Response(body={"code": 0, "data": {"list": []}})),
                         {"list": []})
        with self.assertRaises(PuApiError) as limited:
            response_data(Response(body={"code": 110110, "message": "Too Many Requests"}))
        self.assertEqual(limited.exception.kind, "rate_limit")

    def test_login_error_and_activity_error_are_visible(self):
        auth_failure = Response(body={"code": 401, "message": "expired"})
        with patch("core.tools._post_with_retry", return_value=auth_failure):
            with self.assertRaises(PuApiError) as login:
                get_token_or_raise({"userName": "student", "password": "secret", "sid": 1})
            with self.assertRaises(PuApiError) as activities:
                get_allowed_activity_list({"token": "old", "sid": 1}, strict=True)
        self.assertEqual(login.exception.kind, "auth")
        self.assertEqual(activities.exception.kind, "auth")

    def test_login_returns_token_and_realname(self):
        ok = Response(body={"code": 0, "data": {
            "token": "tok", "baseUserInfo": {"realname": "张三", "year": 25}}})
        with patch("core.tools._post_with_retry", return_value=ok):
            self.assertEqual(login({"userName": "student", "password": "secret", "sid": 1}),
                             {"token": "tok", "realname": "张三", "year": 25})
        no_base = Response(body={"code": 0, "data": {"token": "tok"}})
        with patch("core.tools._post_with_retry", return_value=no_base):
            self.assertEqual(login({"userName": "student", "password": "secret", "sid": 1}),
                             {"token": "tok", "realname": "", "year": ""})

    def test_single_activity_includes_join_end_time(self):
        info = get_single_activity("42", {"credit": 1, "joinEndTime": "2026-10-11 09:00:00"})
        self.assertEqual(info["报名截止时间"], "2026-10-11 09:00:00")
        self.assertIsNone(get_single_activity("42", {})["报名截止时间"])

    def test_expired_signup_never_submits_request(self):
        bot = ActivityBot({"userName": "student", "token": "token", "sid": 1})
        reports = []
        response = Response(body={"code": 0, "data": {"baseInfo": {
            "joinStartTime": "2020-01-01 09:00:00",
            "joinEndTime": "2020-01-01 10:00:00",
        }}})
        with patch("core.activity_bot.requests.post", return_value=response) as post:
            bot.signup("42", callback=lambda state, message: reports.append((state, message)))
        self.assertEqual(reports, [("failed", "报名已截止")])
        self.assertEqual(post.call_count, 1)

    def test_school_search_uses_current_school_ids(self):
        schools = Response(body={"code": 0, "data": {"list": [
            {"id": 11, "name": "甲大学"}, {"id": 12, "name": "甲大学新校区"},
            {"id": 13, "name": "乙大学"},
        ]}})
        with patch("core.tools._get_with_retry", return_value=schools) as get:
            result = get_school_candidates("甲大学")
        self.assertEqual([item["id"] for item in result], [11, 12])
        self.assertIn("/uc/school/list", get.call_args.args[0])

    def test_school_name_lookup_by_sid(self):
        schools = Response(body={"code": 0, "data": {"list": [
            {"id": 11, "name": "甲大学"}, {"id": 12, "name": "乙大学"},
        ]}})
        with patch("core.tools._get_with_retry", return_value=schools):
            self.assertEqual(get_school_name(12), "乙大学")
            self.assertIsNone(get_school_name(99))

    def test_activity_pages_accept_count_when_total_is_missing(self):
        pages = [
            {"pageInfo": {"count": 41}, "list": [{"id": 1}]},
            {"pageInfo": {"count": 41}, "list": [{"id": 2}]},
            {"pageInfo": {"count": 41}, "list": [{"id": 3}]},
        ]
        with patch("core.tools._post_api", side_effect=pages) as post, \
             patch("core.tools.get_info", return_value={"name": "test"}), \
             patch("core.tools._is_valid", return_value=True), \
             patch("core.tools.get_single_activity", side_effect=lambda aid, _: {"id": aid}), \
             patch("core.tools.time.sleep"):
            result = get_allowed_activity_list({"token": "token", "sid": 1}, strict=True)
        self.assertEqual([item["id"] for item in result], [1, 2, 3])
        self.assertEqual(post.call_count, 3)

    def test_full_eligible_activities_are_returned_but_mismatches_are_hidden(self):
        base = {"name": "模拟活动", "statusName": "未开始", "allowUserCount": 10,
                "joinUserCount": 10, "allowCollege": [{"name": "法学院"}],
                "allowYears": [{"id": 25}]}
        details = {1: dict(base), 2: dict(base, joinUserCount=12),
                   3: dict(base, joinUserCount=2), 4: dict(base, statusName="已结束"),
                   5: dict(base, allowCollege=[{"name": "设计学院"}]),
                   6: dict(base, allowUserCount=None)}
        user = {"token": "mock", "sid": 1, "college": "法学院", "year": 25}
        with patch("core.tools._post_api", return_value={
                "pageInfo": {"total": 1}, "list": [{"id": aid} for aid in details]}), \
             patch("core.tools.get_info", side_effect=lambda aid, *args, **kw: details[aid]), \
             patch("core.tools.time.sleep"):
            activities = get_allowed_activity_list(user, strict=True)
        shown = visible_activities(activities, user=user)
        self.assertEqual({a["activity_id"] for a in shown}, {1, 2, 3, 6})
        by_id = {a["activity_id"]: a for a in shown}
        self.assertTrue(activity_is_full(by_id[1]))
        self.assertTrue(activity_is_full(by_id[2]))
        self.assertEqual(by_id[2]["可报名人数"], 0)
        self.assertFalse(activity_is_full(by_id[3]))
        self.assertFalse(activity_is_full(by_id[6]))
        self.assertIsNone(by_id[6]["可报名人数"])

    def test_waiting_for_distant_activity_can_be_cancelled(self):
        cancel = threading.Event()
        bot = ActivityBot({"userName": "student", "token": "token", "sid": 1},
                          cancel_event=cancel)
        result = []
        worker = threading.Thread(target=lambda: result.append(bot._monitor_start_time(
            "1", datetime.now() + timedelta(hours=3))))
        worker.start()
        cancel.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [None])

    def test_rate_limit_stops_signup_burst(self):
        bot = ActivityBot({"userName": "student", "token": "token", "sid": 1})
        reports = []
        bot._callback = lambda state, message: reports.append((state, message))
        response = Response(body={"code": 429, "message": "Too Many Requests"})
        response.text = '{"code":429,"message":"Too Many Requests"}'
        with patch("core.activity_bot.requests.post", return_value=response) as post:
            bot._start_signup_threads("1")
        self.assertLessEqual(post.call_count, 5)
        self.assertEqual(reports[-1][0], "failed")
        self.assertIn("频繁", reports[-1][1])

    def test_cancelled_task_does_not_send_after_waiting_for_request_slot(self):
        slot = threading.Semaphore(1)
        slot.acquire()
        cancel = threading.Event()
        bot = ActivityBot({"userName": "student", "token": "token", "sid": 1},
                          cancel_event=cancel, request_semaphore=slot)
        result = []
        with patch("core.activity_bot.requests.post") as post:
            worker = threading.Thread(target=lambda: result.append(bot._send_signup_request("1")))
            worker.start()
            time.sleep(0.02)
            cancel.set()
            worker.join(1)
            post.assert_not_called()
        slot.release()
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])

    def test_cancel_during_in_flight_requests_stops_later_rounds(self):
        cancel = threading.Event()
        entered = threading.Event()
        release = threading.Event()
        bot = ActivityBot({"userName": "student", "token": "token", "sid": 1},
                          cancel_event=cancel)
        reports = []
        bot._callback = lambda state, message: reports.append(state)

        def post(*args, **kwargs):
            entered.set()
            release.wait(1)
            return Response(status=500)

        with patch("core.activity_bot.requests.post", side_effect=post) as request:
            worker = threading.Thread(target=lambda: bot._start_signup_threads("1"))
            worker.start()
            self.assertTrue(entered.wait(1))
            cancel.set()
            release.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertLessEqual(request.call_count, 5)
        self.assertEqual(reports[-1], "cancelled")


if __name__ == "__main__":
    unittest.main()
