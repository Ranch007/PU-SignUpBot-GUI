"""报名任务调度。任务等待各自的开始时间，请求总并发有统一上限。"""

from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue
from threading import Event, Lock, Semaphore, Thread
from typing import Dict, Iterable

from loguru import logger

from core.activity_bot import ActivityBot, AccountToken
from core.task_store import TaskStore


TERMINAL_STATES = frozenset({"success", "failed", "cancelled"})
RESTORABLE_STATE = "needs_restore"


class TaskPersistenceError(OSError):
    """任务状态未能安全写入磁盘。"""


@dataclass(frozen=True)
class SignupEvent:
    task_id: str
    username: str
    activity_id: str
    state: str
    message: str
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class SignupTasks:
    def __init__(self, max_requests: int = 8, store: TaskStore | None = None):
        self.events: Queue[SignupEvent] = Queue()
        self.persistence_errors: Queue[str] = Queue()
        self.persistence_error: str | None = None
        self._requests = Semaphore(max_requests)
        self._lock = Lock()
        self._tasks: Dict[str, tuple[Event, SignupEvent]] = {}
        self._running_ids: set[str] = set()
        self._tokens: dict[str, AccountToken] = {}
        self._store = store
        if store:
            changed = False
            for record in store.load():
                event = SignupEvent(**record)
                if event.state not in TERMINAL_STATES and event.state != RESTORABLE_STATE:
                    event = SignupEvent(event.task_id, event.username, event.activity_id,
                                        RESTORABLE_STATE, "上次运行中断，请校验后恢复")
                    changed = True
                self._tasks[event.task_id] = (Event(), event)
            if changed:
                self._persist_locked(required=True)

    def _persist_locked(self, *, required: bool = False) -> bool:
        if self._store:
            try:
                self._store.save(entry[1] for entry in self._tasks.values())
            except (OSError, ValueError, TypeError) as exc:
                message = f"保存报名任务失败：{exc}"
                logger.error(message)
                if message != self.persistence_error:
                    self.persistence_errors.put(message)
                self.persistence_error = message
                if required:
                    raise TaskPersistenceError(message) from exc
                return False
        self.persistence_error = None
        return True

    def import_legacy_monitors(self, monitors: Iterable[dict], users: Iterable[dict]) -> int:
        """旧设置中的待监控项只导入为待恢复，不自动报名。"""
        users = list(users)
        imported = 0
        imported_ids = []
        with self._lock:
            for monitor in monitors:
                username = monitor.get("userName")
                aid = str(monitor.get("activityId", ""))
                matches = [user for user in users if user.get("userName") == username and
                           aid in {str(item) for item in user.get("activity_ids", [])}]
                if len(matches) != 1:
                    continue
                user = matches[0]
                task_id = self.task_id(user, aid)
                if task_id in self._tasks:
                    continue
                event = SignupEvent(task_id, username, aid, RESTORABLE_STATE,
                                    "旧版待执行记录，请校验后恢复")
                self._tasks[task_id] = (Event(), event)
                imported += 1
                imported_ids.append(task_id)
            if imported:
                try:
                    self._persist_locked(required=True)
                except TaskPersistenceError:
                    for task_id in imported_ids:
                        self._tasks.pop(task_id, None)
                    raise
        return imported

    @staticmethod
    def task_id(user: dict, activity_id: str) -> str:
        return f"{user.get('sid')}:{user.get('userName')}:{activity_id}"

    def snapshot(self) -> list[SignupEvent]:
        with self._lock:
            return [entry[1] for entry in self._tasks.values()]

    def has_active(self) -> bool:
        with self._lock:
            return bool(self._running_ids) or any(
                entry[1].state not in TERMINAL_STATES | {RESTORABLE_STATE}
                for entry in self._tasks.values()
            )

    def _publish(self, task_id: str, state: str, message: str,
                 expected_cancel: Event | None = None) -> None:
        with self._lock:
            cancel, previous = self._tasks[task_id]
            if expected_cancel is not None and cancel is not expected_cancel:
                return
            if previous.state in TERMINAL_STATES:
                return
            if cancel.is_set() and state not in TERMINAL_STATES:
                state, message = "cancelling", "正在停止，请等待在途请求结束"
            event = SignupEvent(task_id, previous.username, previous.activity_id, state, message)
            self._tasks[task_id] = (cancel, event)
            self.events.put(event)
            self._persist_locked()

    def start(self, users: Iterable[dict], *, retry: bool = False,
              restore: bool = False) -> int:
        to_start = []
        previous_entries = {}
        with self._lock:
            for user in users:
                for activity_id in user.get("activity_ids", []):
                    aid = str(activity_id)
                    task_id = self.task_id(user, aid)
                    existing = self._tasks.get(task_id)
                    state = existing[1].state if existing else None
                    if task_id in self._running_ids or state == "success":
                        continue
                    if state in ("failed", "cancelled") and not retry:
                        continue
                    if state == RESTORABLE_STATE and not restore:
                        continue
                    if state not in TERMINAL_STATES | {RESTORABLE_STATE, None}:
                        continue
                    if user.get("credential_error"):
                        continue
                    previous_entries[task_id] = existing
                    cancel = Event()
                    event = SignupEvent(task_id, str(user["userName"]), aid,
                                        "preparing", "正在准备报名")
                    self._tasks[task_id] = (cancel, event)
                    self._running_ids.add(task_id)
                    account_id = f"{user.get('sid')}:{user.get('userName')}"
                    token_state = self._tokens.setdefault(
                        account_id, AccountToken(user.get("token", "")))
                    to_start.append((task_id, dict(user), aid, cancel, token_state))
            if to_start:
                try:
                    self._persist_locked(required=True)
                except TaskPersistenceError:
                    for task_id, *_ in to_start:
                        previous = previous_entries[task_id]
                        if previous is None:
                            self._tasks.pop(task_id, None)
                        else:
                            self._tasks[task_id] = previous
                        self._running_ids.discard(task_id)
                    raise
                for task_id, *_ in to_start:
                    self.events.put(self._tasks[task_id][1])
        for task_id, user, aid, cancel, token_state in to_start:
            Thread(target=self._run, args=(task_id, user, aid, cancel, token_state),
                   daemon=True).start()
        return len(to_start)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            entry = self._tasks.get(task_id)
            if not entry or entry[1].state in TERMINAL_STATES:
                return False
            entry[0].set()
            restorable = entry[1].state == RESTORABLE_STATE
        self._publish(task_id, "cancelled" if restorable else "cancelling",
                      "已放弃恢复" if restorable else "正在停止，请等待在途请求结束", entry[0])
        return True

    def cancel_all(self) -> None:
        for event in self.snapshot():
            if event.state != RESTORABLE_STATE:
                self.cancel(event.task_id)

    def cancel_account(self, sid: int | str, username: str) -> None:
        prefix = f"{sid}:{username}:"
        for event in self.snapshot():
            if event.task_id.startswith(prefix):
                self.cancel(event.task_id)

    def cancel_unselected(self, sid: int | str, username: str,
                          selected: set[str]) -> None:
        prefix = f"{sid}:{username}:"
        for event in self.snapshot():
            if event.task_id.startswith(prefix) and event.activity_id not in selected:
                self.cancel(event.task_id)

    def reset_account_token(self, sid: int | str, username: str, token: str) -> None:
        """重新登录后，新任务使用新凭证；旧任务的共享状态留给其自行结束。"""
        with self._lock:
            self._tokens[f"{sid}:{username}"] = AccountToken(token)

    def _run(self, task_id: str, user: dict, activity_id: str, cancel: Event,
             token_state: AccountToken) -> None:
        try:
            bot = ActivityBot(user, cancel_event=cancel, request_semaphore=self._requests,
                              token_state=token_state)
            if cancel.is_set():
                self._publish(task_id, "cancelled", "报名已取消", cancel)
                return
            bot.sync_server_time(activity_id)

            def report(state: str, message: str) -> None:
                self._publish(task_id, state, message, cancel)

            bot.signup(activity_id, callback=report)
            current = next((item for item in self.snapshot() if item.task_id == task_id), None)
            if current and current.state not in TERMINAL_STATES:
                if cancel.is_set():
                    self._publish(task_id, "cancelled", "报名已取消", cancel)
                else:
                    self._publish(task_id, "failed", "报名未完成，请查看日志", cancel)
        except Exception as exc:
            logger.exception("报名任务 {} 失败", task_id)
            self._publish(task_id, "cancelled" if cancel.is_set() else "failed",
                          "报名已取消" if cancel.is_set() else f"任务异常：{exc}", cancel)
        finally:
            with self._lock:
                if self._tasks.get(task_id, (None,))[0] is cancel:
                    self._running_ids.discard(task_id)
