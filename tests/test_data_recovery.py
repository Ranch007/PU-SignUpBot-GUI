"""只使用临时文件验证账号数据迁移与备份恢复。"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta

from core.atomic_json import read_json, write_json
from core.crypto_utils import encrypt_password, protect_secret, unprotect_secret
from core.user_data_manager import UserDataManager
from core.signup_tasks import SignupEvent, SignupTasks, TaskPersistenceError
from core.task_store import TaskStore
from core.restore import RestoreError, validate_restore
from test_signup_flow import FakeBot, wait_for_state


class DataRecoveryTests(unittest.TestCase):
    def test_interrupted_replace_keeps_original_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data.json")
            write_json(path, {"old": 1})
            with patch("core.atomic_json.os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    write_json(path, {"new": 2})
            self.assertEqual(read_json(path, {}, dict)[0], {"old": 1})

    def test_corrupt_primary_uses_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data.json")
            write_json(path, [1, 2])
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{")
            self.assertEqual(read_json(path, [], list), ([1, 2], True))

    def test_account_manager_repairs_corrupt_primary_from_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "users.json")
            write_json(path, [{"userName": "a", "password": "enc:v1:" +
                               encrypt_password("secret")}])
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("[")
            manager = UserDataManager(path, os.path.join(directory, "settings.json"))
            self.assertTrue(manager.recovered_from_backup)
            self.assertEqual(manager.user_datas[0]["password"], "secret")
            self.assertEqual(read_json(path, [], list)[1], False)

    def test_plaintext_and_old_ciphertext_are_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "users.json")
            settings = os.path.join(directory, "settings.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump([{"userName": "a", "password": "plain-secret"},
                           {"userName": "b", "password": encrypt_password("old-secret")}], stream)
            manager = UserDataManager(path, settings)
            self.assertEqual([u["password"] for u in manager.user_datas],
                             ["plain-secret", "old-secret"])
            saved = read_json(path, [], list)[0]
            prefix = "dpapi:v1:" if os.name == "nt" else "enc:v1:"
            self.assertTrue(all(u["password"].startswith(prefix) for u in saved))
            with open(path, encoding="utf-8") as stream:
                self.assertNotIn("plain-secret", stream.read())

    def test_invalid_encrypted_password_requires_relogin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "users.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump([{"userName": "a", "password": "enc:v1:broken", "token": "old"}], stream)
            manager = UserDataManager(path, os.path.join(directory, "settings.json"))
            user = manager.user_datas[0]
            self.assertNotIn("password", user)
            self.assertNotIn("token", user)
            self.assertIn("重新登录", user["credential_error"])
            self.assertNotIn("credential_error", read_json(path, [], list)[0][0])

    def test_long_plaintext_password_is_migrated_without_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "users.json")
            password = "Long-password-with-symbols!" * 2
            with open(path, "w", encoding="utf-8") as stream:
                json.dump([{"userName": "a", "password": password}], stream)
            manager = UserDataManager(path, os.path.join(directory, "settings.json"))
            self.assertEqual(manager.user_datas[0]["password"], password)
            prefix = "dpapi:v1:" if os.name == "nt" else "enc:v1:"
            self.assertTrue(read_json(path, [], list)[0][0]["password"].startswith(prefix))

    def test_password_and_token_use_current_user_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "users.json")
            manager = UserDataManager(path, os.path.join(directory, "settings.json"))
            manager.add_user({"userName": "a", "password": "private-password",
                              "token": "private-token"})
            manager.write_user_data()
            stored = read_json(path, [], list)[0][0]
            prefix = "dpapi:v1:" if os.name == "nt" else "enc:v1:"
            self.assertTrue(stored["password"].startswith(prefix))
            self.assertTrue(stored["token"].startswith(prefix))
            self.assertEqual(unprotect_secret(stored["token"]), "private-token")
            self.assertEqual(UserDataManager(
                path, os.path.join(directory, "settings.json")).user_datas[0]["token"],
                "private-token")

    def test_duplicate_username_in_same_school_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = UserDataManager(os.path.join(directory, "users.json"),
                                      os.path.join(directory, "settings.json"))
            self.assertTrue(manager.add_user({"userName": "student", "sid": 1}))
            self.assertFalse(manager.add_user({"userName": "student", "sid": 1}))
            self.assertEqual(len(manager.user_datas), 1)

    def test_legacy_duplicate_username_is_not_silently_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "users.json")
            original = [{"userName": "student", "sid": 1},
                        {"userName": "student", "sid": 1}]
            write_json(path, original)
            with self.assertRaisesRegex(ValueError, "重名学号"):
                UserDataManager(path, os.path.join(directory, "settings.json"))
            self.assertEqual(read_json(path, [], list)[0], original)

    def test_running_task_becomes_restorable_and_terminal_tasks_stay_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "tasks.json")
            store = TaskStore(path)
            store.save([
                SignupEvent("1:student:42", "student", "42", "waiting", "等待报名"),
                SignupEvent("1:student:43", "student", "43", "success", "报名成功"),
                SignupEvent("1:student:44", "student", "44", "cancelled", "已取消"),
            ])
            tasks = SignupTasks(store=store)
            user = {"sid": 1, "userName": "student", "token": "token",
                    "activity_ids": ["42", "43", "44"]}
            states = {event.activity_id: event.state for event in tasks.snapshot()}
            self.assertEqual(states, {"42": "needs_restore", "43": "success", "44": "cancelled"})
            self.assertFalse(tasks.has_active())
            self.assertEqual(tasks.start([user]), 0)
            tasks.cancel_all()
            self.assertEqual(next(event.state for event in tasks.snapshot()
                                  if event.activity_id == "42"), "needs_restore")
            with patch("core.signup_tasks.ActivityBot", FakeBot):
                self.assertEqual(tasks.start([dict(user, activity_ids=["42"])], restore=True), 1)
                wait_for_state(tasks, tasks.task_id(user, "42"), "success")
                self.assertEqual(tasks.start([dict(user, activity_ids=["44"])], retry=True), 1)
                wait_for_state(tasks, tasks.task_id(user, "44"), "success")
            restarted = SignupTasks(store=store)
            self.assertTrue(all(event.state in ("success", "cancelled")
                                for event in restarted.snapshot()))
            with open(path, encoding="utf-8") as stream:
                saved = stream.read()
            self.assertNotIn("token", saved)
            self.assertNotIn("password", saved)

    def test_task_does_not_start_when_initial_state_cannot_be_saved(self):
        class FailingStore:
            def load(self):
                return []

            def save(self, _events):
                raise OSError("disk full")

        tasks = SignupTasks(store=FailingStore())
        user = {"sid": 1, "userName": "student", "activity_ids": ["42"]}
        with self.assertRaises(TaskPersistenceError):
            tasks.start([user])
        self.assertEqual(tasks.snapshot(), [])
        self.assertFalse(tasks.has_active())
        self.assertTrue(tasks.events.empty())
        self.assertIn("disk full", tasks.persistence_errors.get_nowait())

    def test_restore_validates_time_status_and_capacity_without_signup(self):
        user = {"sid": 1, "userName": "student", "token": "token"}
        info = {"name": "模拟活动", "statusName": "未开始",
                "joinStartTime": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "allowUserCount": 10, "joinUserCount": 2}
        with patch("core.restore.get_user_credit", return_value={}), \
             patch("core.restore.get_info", return_value=info):
            result = validate_restore(user, "42")
            self.assertEqual(result["activity_id"], "42")
            with self.assertRaises(RestoreError):
                validate_restore(dict(user, token=""), "42")
            info["joinStartTime"] = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            with self.assertRaises(RestoreError):
                validate_restore(user, "42")

    def test_legacy_monitor_import_never_starts_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(os.path.join(directory, "tasks.json"))
            tasks = SignupTasks(store=store)
            user = {"sid": 1, "userName": "student", "activity_ids": ["42"]}
            monitor = {"userName": "student", "activityId": "42",
                       "startTime": "2099-01-01 09:00:00"}
            self.assertEqual(tasks.import_legacy_monitors([monitor], [user]), 1)
            self.assertFalse(tasks.has_active())
            self.assertEqual(tasks.start([user]), 0)
            self.assertEqual(SignupTasks(store=store).snapshot()[0].state, "needs_restore")
            self.assertEqual(tasks.import_legacy_monitors([monitor], [user]), 0)


if __name__ == "__main__":
    unittest.main()
