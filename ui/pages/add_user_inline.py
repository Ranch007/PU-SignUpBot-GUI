"""添加用户内联表单"""
import customtkinter as ctk
from typing import Callable

from ui.styles import FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, RADIUS
from core.tools import get_sid, get_token


class AddUserInline(ctk.CTkFrame):
    def __init__(self, parent, user_manager, on_done: Callable, on_cancel: Callable, **kw):
        super().__init__(parent, corner_radius=RADIUS, **kw)
        self.user_manager = user_manager
        self._on_done = on_done
        self._on_cancel = on_cancel
        self.step = 0
        self._data = {}
        self._status = None
        self._form = None
        self._btn_frame = None

        self._build_header()
        self._show_step()

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        self.step_label = ctk.CTkLabel(
            bar, text="", font=(ctk.CTkFont, FONT_LG, "bold")
        )
        self.step_label.pack(side="left")

        ctk.CTkButton(
            bar, text="取消", fg_color="gray", width=60, height=30,
            font=(ctk.CTkFont, FONT_SM), command=self._on_cancel,
        ).pack(side="right")

    def _make_form(self):
        if self._form:
            self._form.destroy()
        if self._btn_frame:
            self._btn_frame.destroy()
        if self._status:
            self._status.destroy()

        self._form = ctk.CTkFrame(self, fg_color="transparent")
        self._form.pack(fill="both", expand=True, padx=PAD_LG, pady=PAD_MD)

        self._status = ctk.CTkLabel(self, text="", font=(ctk.CTkFont, FONT_SM))
        self._status.pack(anchor="w", padx=PAD_LG)

        self._btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._btn_frame.pack(fill="x", padx=PAD_LG, pady=(0, PAD_LG))

    def _show_step(self):
        self._make_form()

        if self.step == 0:
            self._step1()
        elif self.step == 1:
            self._step2()
        elif self.step == 2:
            self._step3()

    def _step1(self):
        self.step_label.configure(text="步骤 1/3：输入凭证")

        ctk.CTkLabel(self._form, text="用户名（学号）", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w", pady=(0, PAD_SM))
        self.user_entry = ctk.CTkEntry(self._form, placeholder_text="请输入学号", height=36, font=(ctk.CTkFont, FONT_MD))
        self.user_entry.pack(fill="x", pady=(0, PAD_MD))

        ctk.CTkLabel(self._form, text="密码", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w", pady=(0, PAD_SM))
        self.pw_entry = ctk.CTkEntry(self._form, placeholder_text="请输入密码", show="*", height=36, font=(ctk.CTkFont, FONT_MD))
        self.pw_entry.pack(fill="x")

        ctk.CTkButton(self._btn_frame, text="下一步", height=34, font=(ctk.CTkFont, FONT_MD), command=self._s1_next).pack(side="right")

    def _s1_next(self):
        u = self.user_entry.get().strip()
        p = self.pw_entry.get().strip()
        if not u or not p:
            self._status.configure(text="请输入用户名和密码", text_color="#e74c3c")
            return
        self._data["userName"] = u
        self._data["password"] = p
        self._data["device"] = "pc"
        self._data["activity_ids"] = []
        self._data["categorys"] = []
        self._data["oids"] = []
        self._data["cids"] = []
        self._data["allowYears"] = []
        self.step = 1
        self._show_step()

    def _step2(self):
        self.step_label.configure(text="步骤 2/3：选择学校")

        ctk.CTkLabel(self._form, text="学校关键词", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w", pady=(0, PAD_SM))

        row = ctk.CTkFrame(self._form, fg_color="transparent")
        row.pack(fill="x", pady=(0, PAD_MD))

        self.school_entry = ctk.CTkEntry(row, placeholder_text="如：山东科技大学", height=36, font=(ctk.CTkFont, FONT_MD))
        self.school_entry.pack(side="left", fill="x", expand=True, padx=(0, PAD_SM))

        ctk.CTkButton(row, text="搜索", width=80, height=36, font=(ctk.CTkFont, FONT_MD), command=self._search).pack(side="right")

        self.school_result = ctk.CTkLabel(self._form, text="", font=(ctk.CTkFont, FONT_SM))
        self.school_result.pack(anchor="w")

        ctk.CTkButton(self._btn_frame, text="上一步", height=34, fg_color="gray", font=(ctk.CTkFont, FONT_MD), command=lambda: self._go(0)).pack(side="left")

        self.next2 = ctk.CTkButton(self._btn_frame, text="下一步", height=34, font=(ctk.CTkFont, FONT_MD), state="disabled", command=self._s2_next)
        self.next2.pack(side="right")

    def _search(self):
        name = self.school_entry.get().strip()
        if not name:
            return
        self.school_result.configure(text="搜索中...", text_color="gray")
        sid = get_sid(name)
        if sid:
            self._data["sid"] = sid
            self.school_result.configure(text=f"已匹配，SID: {sid}", text_color="#2ecc71")
            self.next2.configure(state="normal")
        else:
            self.school_result.configure(text="未找到匹配学校", text_color="#e74c3c")

    def _s2_next(self):
        self.step = 2
        self._show_step()

    def _step3(self):
        self.step_label.configure(text="步骤 3/3：补充信息")

        ctk.CTkLabel(self._form, text="院系全称", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w", pady=(0, PAD_SM))
        self.college_entry = ctk.CTkEntry(self._form, placeholder_text="如：经济管理学院", height=36, font=(ctk.CTkFont, FONT_MD))
        self.college_entry.pack(fill="x", pady=(0, PAD_MD))

        ctk.CTkLabel(self._form, text="请务必输入院系全称", font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(anchor="w")

        ctk.CTkButton(self._btn_frame, text="上一步", height=34, fg_color="gray", font=(ctk.CTkFont, FONT_MD), command=lambda: self._go(1)).pack(side="left")
        ctk.CTkButton(self._btn_frame, text="验证并保存", height=34, fg_color="#2e8b57", hover_color="#1e6b3a", font=(ctk.CTkFont, FONT_MD), command=self._s3_save).pack(side="right")

    def _s3_save(self):
        college = self.college_entry.get().strip()
        if not college:
            self._status.configure(text="请输入院系名称", text_color="#e74c3c")
            return
        self._data["college"] = college
        self._status.configure(text="正在验证登录...", text_color="gray")

        token = get_token(self._data)
        if not token:
            self._status.configure(text="登录失败，请检查用户名和密码", text_color="#e74c3c")
            return

        self._data["token"] = token
        self.user_manager.add_user(self._data)
        self.user_manager.write_user_data()
        self._on_done()

    def _go(self, target: int):
        self.step = target
        self._show_step()
