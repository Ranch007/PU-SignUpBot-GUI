"""为现有账号重新登录，同时保留已选活动。"""

import threading
from queue import Empty, Queue
from typing import Callable

import customtkinter as ctk

from core.tools import login
from ui.styles import FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, RADIUS, LIGHT_FRAME, DARK_FRAME


class ReloginInline(ctk.CTkFrame):
    def __init__(self, parent, username: str, user_manager, task_manager,
                 on_done: Callable, on_cancel: Callable, **kw):
        super().__init__(parent, corner_radius=RADIUS,
                         fg_color=(LIGHT_FRAME, DARK_FRAME), **kw)
        self.username = username
        self.user_manager = user_manager
        self.task_manager = task_manager
        self._on_done = on_done
        self._on_cancel = on_cancel
        self._results = Queue()
        self._active = True
        self._build()
        self.after(100, self._poll)

    def _build(self):
        user = self.user_manager.get_user(self.username)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))
        ctk.CTkLabel(bar, text=f"重新登录 · {self.username}",
                     font=(ctk.CTkFont, FONT_LG, "bold")).pack(side="left")
        ctk.CTkButton(bar, text="取消", width=60, height=30, fg_color="gray",
                      command=self._on_cancel).pack(side="right")

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=PAD_LG)
        ctk.CTkLabel(form, text=f"学校 SID：{user.get('sid')}  ·  已选 {len(user.get('activity_ids', []))} 项活动",
                     font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(anchor="w", pady=(0, PAD_MD))
        ctk.CTkLabel(form, text="PU 密码", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w")
        self._password = ctk.CTkEntry(form, show="*", placeholder_text="输入当前 PU 密码", height=36)
        self._password.pack(fill="x", pady=(PAD_SM, PAD_MD))
        ctk.CTkLabel(form, text="院系全称", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w")
        self._college = ctk.CTkEntry(form, height=36)
        self._college.pack(fill="x", pady=PAD_SM)
        self._college.insert(0, user.get("college") or "")
        self._status = ctk.CTkLabel(form, text="验证成功后才会更新账号；已选活动会保留",
                                    font=(ctk.CTkFont, FONT_SM), text_color="gray")
        self._status.pack(anchor="w", pady=PAD_MD)
        self._save = ctk.CTkButton(form, text="验证并更新", height=34,
                                   fg_color="#2e8b57", hover_color="#1e6b3a",
                                   command=self._submit)
        self._save.pack(anchor="e")

    def _submit(self):
        password = self._password.get()
        college = self._college.get().strip()
        if not password or not college:
            self._status.configure(text="请输入密码和院系全称", text_color="#e74c3c")
            return
        user = self.user_manager.get_user(self.username)
        data = {"userName": self.username, "password": password, "sid": user.get("sid")}
        self._save.configure(state="disabled")
        self._status.configure(text="正在验证登录...", text_color="gray")

        def run():
            try:
                result = login(data)
                from core.tools import get_school_name
                school = get_school_name(data["sid"])
                if school:
                    result["school"] = school
            except Exception as exc:
                result = exc
            self._results.put((result, password, college))

        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        if not self._active:
            return
        try:
            result, password, college = self._results.get_nowait()
        except Empty:
            self.after(100, self._poll)
            return
        if isinstance(result, Exception):
            self._status.configure(text=f"登录失败：{result}", text_color="#e74c3c")
            self._save.configure(state="normal")
            self.after(100, self._poll)
            return
        user = self.user_manager.get_user(self.username)
        sid = user.get("sid")
        if self.task_manager:
            self.task_manager.cancel_account(sid, self.username)
            self.task_manager.reset_account_token(sid, self.username, result["token"])
        updates = {"password": password, "college": college, "token": result["token"]}
        if result.get("realname"):
            updates["realname"] = result["realname"]
        if result.get("year"):
            updates["year"] = result["year"]
        if result.get("school"):
            updates["school"] = result["school"]
        self.user_manager.update_user(self.username, updates)
        user.pop("credential_error", None)
        self.user_manager.write_user_data()
        self._on_done()

    def cancel_pending(self):
        self._active = False
