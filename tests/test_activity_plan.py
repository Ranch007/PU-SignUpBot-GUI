"""活动排序、首页倒计时与已选任务调整的回归测试。"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from core.activity_plan import activity_is_full, countdown, next_signup, overlapping_activities, selectable_activity_ids, upcoming_signups, visible_activities
from core.signup_tasks import SignupTasks
from test_signup_flow import FakeBot, wait_for_state


class ActivityPlanTests(unittest.TestCase):
    def test_full_capacity_is_distinct_from_unknown_capacity(self):
        for remaining in (0, "0", -1):
            self.assertTrue(activity_is_full({"可报名人数": remaining}))
        for remaining in (None, "待确认", 1, "28"):
            self.assertFalse(activity_is_full({"可报名人数": remaining}))
        self.assertFalse(activity_is_full({}))

    def test_search_and_sort_keep_source_unchanged(self):
        activities = [
            {"activity_id": "2", "活动名称": "Python 工作坊", "开始报名时间": "2026-10-10 09:00:00",
             "活动开始时间": "2026-10-15 09:00:00", "分数": 2},
            {"activity_id": "1", "活动名称": "python 讲座", "开始报名时间": "2026-10-09 09:00:00",
             "活动开始时间": "2026-10-16 09:00:00", "分数": 3},
            {"activity_id": "3", "活动名称": "志愿活动", "开始报名时间": None, "分数": None},
        ]
        self.assertEqual([item["activity_id"] for item in visible_activities(activities, "PyThOn")],
                         ["1", "2"])
        self.assertEqual([item["activity_id"] for item in visible_activities(activities, sort_by="活动时间")],
                         ["2", "1", "3"])
        self.assertEqual([item["activity_id"] for item in visible_activities(activities, sort_by="学分")],
                         ["1", "2", "3"])
        self.assertEqual(activities[0]["activity_id"], "2")

    def test_next_signup_ignores_unknown_and_past_times(self):
        now = datetime(2026, 10, 7, 12)
        users = [{"userName": "甲", "activity_ids": ["1", "2", "3"], "activity_details": {
            "1": {"开始报名时间": "2026-10-07 11:00:00"},
            "2": {"活动名称": "近期活动", "开始报名时间": "2026-10-07 13:00:00"},
            "3": {"开始报名时间": "未知"},
        }}]
        self.assertEqual(next_signup(users, now)[2], "2")
        self.assertEqual(countdown(now + timedelta(hours=1), now), "01:00:00")
        self.assertIsNone(next_signup(users, now + timedelta(days=2)))

    def test_activity_visibility_filters_mismatch_but_keeps_unknown_and_selected(self):
        activities = [
            {"activity_id": "1", "活动名称": "英语角", "参与要求": {
                "allowCollege": [{"name": "设计学院"}]}},
            {"activity_id": "2", "活动名称": "讲座", "参与要求": {
                "allowYears": [{"id": 24}]}},
            {"activity_id": "3", "活动名称": "工作坊", "参与要求": {
                "allowCollege": [{"name": "法学院"}], "allowYears": [{"id": 25}]}},
            {"activity_id": "4", "活动名称": "待核对活动", "参与要求": {
                "allowTribe": [1]}},
        ]
        user = {"college": "法学院", "year": 25}
        shown = visible_activities(activities, user=user)
        self.assertEqual({item["activity_id"] for item in shown}, {"3", "4"})
        shown = visible_activities(activities, "英语", user=user, selected={1})
        self.assertEqual([item["activity_id"] for item in shown], ["1"])
        self.assertEqual(visible_activities(activities, "英语", user=user), [])
        self.assertEqual(len(visible_activities(activities, user={})), 4)
        self.assertEqual(len(activities), 4)

    def test_visibility_rechecks_current_profile_and_supports_cached_conditions(self):
        activity = {"activity_id": "1", "参与要求": {
            "allowCollege": [{"name": "设计学院"}]},
            "参与条件": [{"condition": "院系", "status": "matched", "message": "旧结果"}]}
        self.assertEqual(visible_activities([activity], user={"college": "法学院"}), [])
        self.assertEqual(visible_activities([activity], user={"college": "设计学院"}), [activity])
        cached = {"activity_id": "2", "参与条件": [{"status": "mismatch"}]}
        self.assertEqual(visible_activities([cached], user={}), [])
        self.assertEqual(visible_activities([cached], user={}, selected={"2"}), [cached])

    def test_bulk_selection_respects_search_capacity_and_known_qualification(self):
        requirements = {"allowCollege": [{"name": "法学院"}], "allowYears": [{"id": 25}]}
        activities = [
            {"activity_id": "1", "活动名称": "讲座一", "可报名人数": 2, "参与要求": requirements},
            {"activity_id": "2", "活动名称": "讲座二", "可报名人数": 0, "参与要求": requirements},
            {"activity_id": "3", "活动名称": "讲座三", "可报名人数": 2,
             "参与要求": {"allowCollege": [{"name": "设计学院"}]}},
            {"activity_id": "4", "活动名称": "工作坊", "可报名人数": 1, "参与要求": requirements},
            {"activity_id": "5", "活动名称": "部落讲座", "可报名人数": 1,
             "参与要求": dict(requirements, allowTribe=[1])},
        ]
        user = {"college": "法学院", "year": 25}
        self.assertEqual(selectable_activity_ids(activities, user, "讲座"), {"1"})
        self.assertEqual(selectable_activity_ids(activities, user), {"1", "4"})
        self.assertEqual(selectable_activity_ids(activities, {"year": 25}), set())
        self.assertNotIn("activity_ids", user)
        self.assertEqual(len(activities), 5)

    def test_upcoming_signups_sorts_across_accounts(self):
        now = datetime(2026, 10, 7, 12)
        users = [
            {"userName": "甲", "activity_ids": ["1"], "activity_details": {
                "1": {"开始报名时间": "2026-10-08 10:00:00"},
            }},
            {"userName": "乙", "activity_ids": ["2", "3", "4"], "activity_details": {
                "2": {"开始报名时间": "2026-10-08 08:00:00"},
                "3": {"开始报名时间": "2026-10-07 11:00:00"},
                "4": {"开始报名时间": "未知"},
            }},
        ]
        upcoming = upcoming_signups(users, now)
        self.assertEqual([(item[0], item[1], item[2]) for item in upcoming], [
            (datetime(2026, 10, 8, 8), "乙", "2"),
            (datetime(2026, 10, 8, 10), "甲", "1"),
        ])
        self.assertEqual(next_signup(users, now), upcoming[0])

    def test_overlap_requires_known_intervals(self):
        details = {
            "1": {"活动名称": "讲座", "活动开始时间": "2026-10-10 09:00:00",
                  "活动结束时间": "2026-10-10 11:00:00"},
            "2": {"活动名称": "义工", "活动开始时间": "2026-10-10 10:00:00",
                  "活动结束时间": "2026-10-10 12:00:00"},
            "3": {"活动名称": "未知时间"},
        }
        self.assertEqual(overlapping_activities(details, {"1", "2", "3"}), [("讲座", "义工")])
        self.assertEqual(overlapping_activities(details, {"1", "3"}), [])

    def test_unselect_cancels_only_removed_activity(self):
        FakeBot.first_started.clear()
        tasks = SignupTasks()
        user = {"sid": 1, "userName": "student", "activity_ids": ["1", "12"]}
        with patch("core.signup_tasks.ActivityBot", FakeBot):
            tasks.start([user])
            self.assertTrue(FakeBot.first_started.wait(1))
            tasks.cancel_unselected(1, "student", {"12"})
            wait_for_state(tasks, tasks.task_id(user, "1"), "cancelled")
            self.assertEqual(wait_for_state(tasks, tasks.task_id(user, "12"), "success").state,
                             "success")


if __name__ == "__main__":
    unittest.main()
