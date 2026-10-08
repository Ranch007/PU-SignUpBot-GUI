"""年级默认勾选的学校隔离与字段映射回归。"""

import unittest

from core.activity_filters import default_year_filter_ids
from core.participation import participation_checks


class ActivityFilterTests(unittest.TestCase):
    def test_same_school_accounts_select_their_own_year_only(self):
        users = [{"sid": 1, "year": 25}, {"sid": "1", "year": "24"}]
        options = [{"id": year, "name": f"20{year}级"} for year in (24, 25, 26)]
        self.assertEqual(default_year_filter_ids(users[0], options), {"25"})
        self.assertEqual(default_year_filter_ids(users[1], options), {"24"})

    def test_cross_school_same_grade_uses_each_schools_own_option_ids(self):
        users = [{"sid": 1, "year": 25}, {"sid": 2, "year": "2025"},
                 {"sid": 2, "year": 24}]
        options_a = [{"id": "a24", "name": "2024级"}, {"id": "a25", "name": "2025级"}]
        options_b = [{"id": "b24", "name": "24级"}, {"id": "b25", "name": "25级"}]
        self.assertEqual(default_year_filter_ids(users[0], options_a), {"a25"})
        self.assertEqual(default_year_filter_ids(users[1], options_b), {"b25"})
        self.assertEqual(default_year_filter_ids(users[2], options_b), {"b24"})

    def test_missing_or_unmapped_year_never_selects_all(self):
        options = [{"id": "24", "name": "2024级"}, {"id": "25", "name": "2025级"}]
        for user in ({}, {"sid": 1}, {"sid": 1, "year": "未知"},
                     {"sid": 1, "year": 26}):
            self.assertEqual(default_year_filter_ids(user, options), set())

    def test_only_available_options_are_used(self):
        user = {"sid": 1, "year": "2025级"}
        options = [{"id": "25", "name": "2025级"}, {"name": "2024级"}]
        self.assertEqual(default_year_filter_ids(user, options), {"25"})
        self.assertEqual(default_year_filter_ids({"year": 24}, options), set())

    def test_school_year_option_is_checked_against_individual_account(self):
        requirements = {"allowYears": [{"id": "school-a-25", "name": "2025级"}]}
        self.assertEqual(participation_checks(requirements, {"year": 25})[0]["status"], "matched")
        self.assertEqual(participation_checks(requirements, {"year": "2025"})[0]["status"], "matched")
        self.assertEqual(participation_checks(requirements, {"year": 24})[0]["status"], "mismatch")
        self.assertEqual(participation_checks(requirements, {})[0]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
