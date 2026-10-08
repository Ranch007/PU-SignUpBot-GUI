"""报名任务监控面板；状态由应用级任务管理器提供。"""

from queue import Empty, Queue
import threading
from typing import Callable

import customtkinter as ctk

from core.signup_tasks import SignupEvent, SignupTasks, TaskPersistenceError, TERMINAL_STATES
from core.restore import validate_restore
from core.accounts import account_from_task, credentials_match, credential_snapshot
from ui.styles import FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, RADIUS, LIGHT_FRAME, DARK_FRAME


_STATES = {
    "pending": ("待开始", "○"),
    "needs_restore": ("待恢复", "↻"),
    "preparing": ("准备中", "⏳"),
    "waiting": ("等待报名", "⏳"),
    "joining": ("正在报名", "▶"),
    "cancelling": ("取消中", "⏹"),
    "cancelled": ("已取消", "⏹"),
    "success": ("已报名", "✅"),
    "failed": ("失败", "❌"),
}


class SignupInline(ctk.CTkFrame):
    def __init__(self, parent, user_manager, log_queue, task_manager: SignupTasks,
                 on_close: Callable, on_change: Callable | None = None,
                 on_relogin: Callable | None = None, on_details: Callable | None = None, **kw):
        super().__init__(parent, corner_radius=RADIUS,
                         fg_color=(LIGHT_FRAME, DARK_FRAME), **kw)
        self.user_manager = user_manager
        self.log_queue = log_queue
        self.task_manager = task_manager
        self._on_close = on_close
        self._on_change = on_change
        self._on_relogin = on_relogin
        self._on_details = on_details
        self._rows: dict[str, dict] = {}
        self._restore_results = Queue()
        self._restore_inflight: set[str] = set()
        self._active = True
        self._build()
        for user in user_manager.user_datas:
            for aid in user.get("activity_ids", []):
                aid = str(aid)
                self.on_task_event(SignupEvent(task_manager.task_id(user, aid),
                                               str(user.get("userName")), aid,
                                               "pending", "尚未开始"))
        for event in task_manager.snapshot():
            self.on_task_event(event)
        self._update_controls()
        self.after(100, self._poll_restore)

    def cancel_pending(self):
        self._active = False

    def _poll_restore(self):
        if not self._active:
            return
        while True:
            try:
                task_id, snapshot, result = self._restore_results.get_nowait()
            except Empty:
                break
            self._restore_inflight.discard(task_id)
            row = self._rows.get(task_id)
            if not row or row["state"] != "needs_restore":
                continue
            user = self.user_manager.get_user(row["account"])
            if not credentials_match(user, snapshot) or row["activity_id"] not in {
                    str(aid) for aid in user.get("activity_ids", [])}:
                row["status"].configure(text="账号或活动已变化，请重新检查")
                row["action"].configure(text="检查并恢复", state="normal")
                continue
            if isinstance(result, Exception):
                row["status"].configure(text=f"恢复校验失败：{result}")
                row["action"].configure(text="重试校验", state="normal")
                continue
            user.setdefault("activity_details", {})[row["activity_id"]] = result
            try:
                self.user_manager.write_user_data()
            except OSError as exc:
                row["status"].configure(text=f"保存活动详情失败：{exc}")
                row["action"].configure(text="重试校验", state="normal")
                continue
            one = dict(user, activity_ids=[row["activity_id"]])
            try:
                started = self.task_manager.start([one], restore=True)
            except TaskPersistenceError as exc:
                row["status"].configure(text=str(exc))
                row["action"].configure(text="重试校验", state="normal")
                continue
            if not started:
                row["status"].configure(text="任务状态已变化，请重新打开计划")
                row["action"].configure(text="检查并恢复", state="normal")
        self.after(100, self._poll_restore)

    def _check_restore(self, task_id: str):
        if task_id in self._restore_inflight:
            return
        row = self._rows[task_id]
        user = self.user_manager.get_user(row["account"])
        if not user:
            return
        aid = row["activity_id"]
        credentials = credential_snapshot(user)
        snapshot = dict(user)
        self._restore_inflight.add(task_id)
        row["status"].configure(text="正在核对登录、活动状态、时间和名额...")
        row["action"].configure(text="校验中", state="disabled")

        def run():
            try:
                result = validate_restore(snapshot, aid)
            except Exception as exc:
                result = exc
            self._restore_results.put((task_id, credentials, result))

        threading.Thread(target=run, daemon=True).start()

    def _build(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))
        ctk.CTkLabel(bar, text="报名计划", font=(ctk.CTkFont, FONT_LG, "bold")).pack(side="left")
        self._account_options = {"全部账号": None}
        for user in self.user_manager.user_datas:
            label = f"{user.get('userName')} · SID {user.get('sid')}"
            self._account_options[label] = (str(user.get("sid")), user.get("userName"))
        self._account_filter = ctk.CTkOptionMenu(bar, values=list(self._account_options),
                                                 width=155, height=30,
                                                 command=lambda _value: self._apply_filter())
        self._account_filter.pack(side="left", padx=PAD_MD)
        ctk.CTkButton(bar, text="历史记录", width=75, height=30, fg_color="gray",
                      font=(ctk.CTkFont, FONT_SM), command=self._toggle_history).pack(side="left")
        ctk.CTkButton(bar, text="关闭面板", fg_color="gray", width=80, height=32,
                      font=(ctk.CTkFont, FONT_SM), command=self._on_close).pack(side="right", padx=(PAD_SM, 0))
        self._abort_btn = ctk.CTkButton(
            bar, text="⏹ 全部取消", fg_color="#c0392b", hover_color="#a93226",
            height=32, font=(ctk.CTkFont, FONT_SM), command=self._abort)
        self._abort_btn.pack(side="right", padx=(0, PAD_SM))
        self._start_btn = ctk.CTkButton(
            bar, text="▶ 开始等待报名", fg_color="#2e8b57", hover_color="#1e6b3a",
            height=32, font=(ctk.CTkFont, FONT_SM), command=self._start)
        self._start_btn.pack(side="right", padx=(0, PAD_SM))

        progress = ctk.CTkFrame(self, corner_radius=8, fg_color=("gray90", "gray17"))
        progress.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))
        self._progress = ctk.CTkProgressBar(progress, height=18, corner_radius=9)
        self._progress.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))
        self._progress.set(0)
        self._prog_label = ctk.CTkLabel(progress, text="", font=(ctk.CTkFont, FONT_SM),
                                       text_color="gray")
        self._prog_label.pack(anchor="w", padx=PAD_MD, pady=(0, PAD_MD))

        self._history_frame = ctk.CTkScrollableFrame(self, height=100, corner_radius=RADIUS)

        self._table = ctk.CTkScrollableFrame(self, corner_radius=RADIUS)
        self._table.pack(fill="both", expand=True, padx=PAD_LG, pady=(0, PAD_MD))
        header = ctk.CTkFrame(self._table, fg_color="transparent")
        header.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))
        for title, width in (("用户", 90), ("活动", 220), ("状态与说明", None), ("时间", 80), ("操作", 200)):
            options = {"width": width} if width else {}
            ctk.CTkLabel(header, text=title, font=(ctk.CTkFont, FONT_SM, "bold"),
                         **options).pack(side="left", padx=PAD_SM,
                                         fill="x" if width is None else "none",
                                         expand=width is None)

    def _toggle_history(self):
        if self._history_frame.winfo_manager():
            self._history_frame.pack_forget()
            return
        self._history_frame.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD), before=self._table)
        self._render_history()

    def _render_history(self):
        for child in self._history_frame.winfo_children():
            child.destroy()
        history = sorted((event for event in self.task_manager.snapshot()
                          if event.state in TERMINAL_STATES),
                         key=lambda event: event.updated_at, reverse=True)
        if not history:
            ctk.CTkLabel(self._history_frame, text="暂无完成、失败或取消记录",
                         font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(anchor="w", padx=PAD_SM)
        for event in history:
            state = _STATES[event.state][0]
            ctk.CTkLabel(self._history_frame,
                         text=f"{event.updated_at}  ·  SID {account_from_task(event.task_id)[0]} · {event.username}  ·  活动 {event.activity_id}  ·  {state}  ·  {event.message}",
                         font=(ctk.CTkFont, FONT_SM), anchor="w").pack(fill="x", padx=PAD_SM, pady=2)

    def _start(self):
        try:
            count = self.task_manager.start(self.user_manager.user_datas)
        except TaskPersistenceError as exc:
            self._prog_label.configure(text=str(exc), text_color="#c0392b")
            return
        if not count:
            self.log_queue.put(("WARNING", "没有新的待报名活动"))
        self._update_controls()

    def _abort(self):
        self.task_manager.cancel_all()
        self.log_queue.put(("WARNING", "正在停止报名任务"))
        self._update_controls()

    def _add_row(self, event: SignupEvent):
        row = ctk.CTkFrame(self._table, corner_radius=6)
        row.pack(fill="x", padx=PAD_MD, pady=2)
        user = self.user_manager.get_user(account_from_task(event.task_id)) or {}
        detail = (user.get("activity_details") or {}).get(event.activity_id) or {}
        name = detail.get("活动名称") or f"活动 {event.activity_id}"
        signup_time = detail.get("开始报名时间") or "待确认"
        username = ctk.CTkLabel(row, text=f"{event.username}\nSID {user.get('sid')}", font=(ctk.CTkFont, FONT_SM), width=90)
        activity = ctk.CTkLabel(row, text=f"{name}\n报名 {signup_time}",
                                font=(ctk.CTkFont, FONT_SM), width=220,
                                anchor="w", justify="left", wraplength=200)
        status = ctk.CTkLabel(row, text="", font=(ctk.CTkFont, FONT_SM), anchor="w",
                             wraplength=180, justify="left")
        when = ctk.CTkLabel(row, text="", font=(ctk.CTkFont, FONT_SM), width=80)
        actions = ctk.CTkFrame(row, fg_color="transparent", width=200)
        action = ctk.CTkButton(actions, text="开始", fg_color="#2e8b57", width=52, height=24,
                               font=(ctk.CTkFont, FONT_SM),
                               command=lambda tid=event.task_id: self._act(tid))
        action.pack(side="left", padx=(0, 4))
        guide = ctk.CTkButton(actions, text="详情", fg_color="gray", width=70, height=24,
                             font=(ctk.CTkFont, FONT_SM), command=lambda tid=event.task_id: self._guide(tid))
        guide.pack(side="left", padx=(0, 4))
        ctk.CTkButton(actions, text="移除", fg_color="gray", width=52, height=24,
                      font=(ctk.CTkFont, FONT_SM),
                      command=lambda tid=event.task_id: self._remove(tid)).pack(side="left")
        for widget, stretch in ((username, False), (activity, False), (status, True),
                                (when, False), (actions, False)):
            widget.pack(side="left", padx=PAD_SM, fill="x" if stretch else "none", expand=stretch)
        self._rows[event.task_id] = {"state": event.state, "status": status,
                                     "time": when, "action": action, "frame": row,
                                     "username": event.username, "activity_id": event.activity_id,
                                     "account": account_from_task(event.task_id), "activity": activity,
                                     "name": name, "guide": guide, "error_kind": ""}
        self._apply_filter()

    def _visible_row(self, task_id: str) -> bool:
        account = self._account_options.get(self._account_filter.get())
        return account is None or task_id.startswith(f"{account[0]}:{account[1]}:")

    def _apply_filter(self):
        for row in self._rows.values():
            row["frame"].pack_forget()
        for task_id, row in self._rows.items():
            if self._visible_row(task_id):
                row["frame"].pack(fill="x", padx=PAD_MD, pady=2)
        self._refresh_progress()

    def _act(self, task_id: str):
        row = self._rows[task_id]
        if row["state"] == "needs_restore":
            self._check_restore(task_id)
        elif row["state"] in ("pending", "failed", "cancelled"):
            user = self.user_manager.get_user(row["account"])
            if user:
                if user.get("credential_error"):
                    row["status"].configure(text="密码无法解密，请先重新登录")
                    return
                one = dict(user, activity_ids=[row["activity_id"]])
                try:
                    started = self.task_manager.start(
                        [one], retry=row["state"] in ("failed", "cancelled"))
                except TaskPersistenceError as exc:
                    row["status"].configure(text=str(exc))
                    return
                if not started:
                    row["status"].configure(text="没有启动新任务，请检查登录状态")
        else:
            self.task_manager.cancel(task_id)
        self._update_controls()

    def _remove(self, task_id: str):
        row = self._rows.pop(task_id)
        self.task_manager.cancel(task_id)
        user = self.user_manager.get_user(row["account"])
        if user:
            aid = row["activity_id"]
            selected = [item for item in user.get("activity_ids", []) if str(item) != aid]
            details = {key: value for key, value in (user.get("activity_details") or {}).items()
                       if key != aid}
            self.user_manager.update_user(row["account"], {"activity_ids": selected,
                                                               "activity_details": details})
            self.user_manager.write_user_data()
        row["frame"].destroy()
        self._refresh_progress()
        self._update_controls()
        if self._on_change:
            self._on_change()

    def on_task_event(self, event: SignupEvent):
        user = self.user_manager.get_user(account_from_task(event.task_id))
        if not user or event.activity_id not in {str(aid) for aid in user.get("activity_ids", [])}:
            return
        if event.task_id not in self._rows:
            self._add_row(event)
        row = self._rows[event.task_id]
        row["state"] = event.state
        row["error_kind"] = event.error_kind
        row["guide"].configure(text="重新登录" if event.error_kind == "auth" else "详情")
        if event.join_start_time:
            row["activity"].configure(text=f"{row['name']}\n报名 {event.join_start_time}")
        label, icon = _STATES.get(event.state, (event.state, "•"))
        row["status"].configure(text=f"{icon} {label} · {event.message}")
        row["time"].configure(text="" if event.state == "pending" else event.updated_at[-8:])
        action = row["action"]
        if event.state in ("pending", "failed", "cancelled", "needs_restore"):
            action.configure(text=("开始" if event.state == "pending" else
                                   "检查并恢复" if event.state == "needs_restore" else "重试"),
                             fg_color="#2e8b57", state="normal")
        elif event.state == "success" or event.state == "cancelling":
            action.configure(text="已完成" if event.state == "success" else "取消中", state="disabled")
        else:
            action.configure(text="取消", fg_color="#c0392b", state="normal")
        self._refresh_progress()
        self._update_controls()
        if event.state in TERMINAL_STATES and self._history_frame.winfo_manager():
            self._render_history()

    def _guide(self, task_id):
        row = self._rows[task_id]
        action = self._on_relogin if row["error_kind"] == "auth" else self._on_details
        if action:
            action(row["account"])

    def _refresh_progress(self):
        states = [row["state"] for task_id, row in self._rows.items() if self._visible_row(task_id)]
        total = len(states)
        success = states.count("success")
        failed = states.count("failed")
        cancelled = states.count("cancelled")
        waiting = states.count("pending")
        restorable = states.count("needs_restore")
        running = total - success - failed - cancelled - waiting - restorable
        self._progress.set((success + failed + cancelled) / total if total else 0)
        self._prog_label.configure(
            text=f"总计: {total}  |  成功: {success}  |  失败: {failed}  |  已取消: {cancelled}  |  待开始: {waiting}  |  待恢复: {restorable}  |  进行中: {running}")

    def _update_controls(self):
        active = self.task_manager.has_active()
        available = any(row["state"] == "pending"
                        for row in self._rows.values())
        self._start_btn.configure(state="normal" if available else "disabled")
        self._abort_btn.configure(state="normal" if active else "disabled")
