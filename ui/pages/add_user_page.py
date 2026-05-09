"""添加用户：多步骤向导"""
import customtkinter as ctk

from ui.styles import FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, RADIUS
from core.tools import get_sid, get_token


class AddUserPage(ctk.CTkFrame):
    def __init__(self, parent, user_manager, on_done=None, **kwargs):
        super().__init__(parent, corner_radius=0, fg_color="transparent", **kwargs)
        self.user_manager = user_manager
        self.on_done = on_done
        self.step = 0
        self._data = {}

        self._build()
        self._show_step()

    def _build(self):
        self.header_label = ctk.CTkLabel(
            self,
            text="添加用户",
            font=(ctk.CTkFont, FONT_LG, "bold"),
        )
        self.header_label.pack(anchor="w", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        self.step_label = ctk.CTkLabel(
            self,
            text="",
            font=(ctk.CTkFont, FONT_MD),
            text_color="gray",
        )
        self.step_label.pack(anchor="w", padx=PAD_LG)

        self.form_frame = ctk.CTkFrame(
            self,
            corner_radius=RADIUS,
        )
        self.form_frame.pack(
            fill="both", expand=True, padx=PAD_LG, pady=PAD_MD
        )

        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=(ctk.CTkFont, FONT_SM),
        )
        self.status_label.pack(anchor="w", padx=PAD_LG)

        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(fill="x", padx=PAD_LG, pady=(0, PAD_LG))

    def _clear_form(self):
        for w in self.form_frame.winfo_children():
            w.destroy()
        for w in self.btn_frame.winfo_children():
            w.destroy()

    def _show_step(self):
        self._clear_form()
        self.status_label.configure(text="")

        if self.step == 0:
            self._build_step1_credentials()
        elif self.step == 1:
            self._build_step2_school()
        elif self.step == 2:
            self._build_step3_college()

    # -------- 步骤 1：输入凭证 --------

    def _build_step1_credentials(self):
        self.step_label.configure(text="步骤 1/3：输入凭证")

        ctk.CTkLabel(
            self.form_frame, text="用户名（学号）", font=(ctk.CTkFont, FONT_MD)
        ).pack(anchor="w", padx=PAD_LG, pady=(PAD_LG, PAD_SM))

        self.username_entry = ctk.CTkEntry(
            self.form_frame,
            placeholder_text="请输入学号",
            height=36,
            font=(ctk.CTkFont, FONT_MD),
        )
        self.username_entry.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))

        ctk.CTkLabel(
            self.form_frame, text="密码", font=(ctk.CTkFont, FONT_MD)
        ).pack(anchor="w", padx=PAD_LG, pady=(0, PAD_SM))

        self.password_entry = ctk.CTkEntry(
            self.form_frame,
            placeholder_text="请输入密码",
            show="*",
            height=36,
            font=(ctk.CTkFont, FONT_MD),
        )
        self.password_entry.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))

        ctk.CTkButton(
            self.btn_frame,
            text="下一步",
            height=36,
            font=(ctk.CTkFont, FONT_MD),
            command=self._step1_next,
        ).pack(side="right")

    def _step1_next(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            self.status_label.configure(text="请输入用户名和密码", text_color="#e74c3c")
            return

        self._data["userName"] = username
        self._data["password"] = password
        self._data["device"] = "pc"
        self._data["activity_ids"] = []
        self._data["categorys"] = []
        self._data["oids"] = []
        self._data["cids"] = []
        self._data["allowYears"] = []

        self.step = 1
        self._show_step()

    # -------- 步骤 2：选择学校 --------

    def _build_step2_school(self):
        self.step_label.configure(text="步骤 2/3：选择学校")

        ctk.CTkLabel(
            self.form_frame, text="学校关键词", font=(ctk.CTkFont, FONT_MD)
        ).pack(anchor="w", padx=PAD_LG, pady=(PAD_LG, PAD_SM))

        search_frame = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        search_frame.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))

        self.school_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="如：山东科技大学",
            height=36,
            font=(ctk.CTkFont, FONT_MD),
        )
        self.school_entry.pack(side="left", fill="x", expand=True, padx=(0, PAD_SM))

        ctk.CTkButton(
            search_frame,
            text="搜索",
            width=80,
            height=36,
            font=(ctk.CTkFont, FONT_MD),
            command=self._search_school,
        ).pack(side="right")

        self.school_result_label = ctk.CTkLabel(
            self.form_frame,
            text="",
            font=(ctk.CTkFont, FONT_SM),
        )
        self.school_result_label.pack(anchor="w", padx=PAD_LG, pady=PAD_MD)

        ctk.CTkButton(
            self.btn_frame,
            text="上一步",
            height=36,
            fg_color="gray",
            font=(ctk.CTkFont, FONT_MD),
            command=lambda: self._go_back(0),
        ).pack(side="left")

        self.step2_next_btn = ctk.CTkButton(
            self.btn_frame,
            text="下一步",
            height=36,
            font=(ctk.CTkFont, FONT_MD),
            state="disabled",
            command=self._step2_next,
        )
        self.step2_next_btn.pack(side="right")

    def _search_school(self):
        name = self.school_entry.get().strip()
        if not name:
            self.school_result_label.configure(text="请输入学校名称", text_color="#e74c3c")
            return

        self.school_result_label.configure(text="搜索中...", text_color="gray")
        sid = get_sid(name)
        if sid:
            self._data["sid"] = sid
            self.school_result_label.configure(
                text=f"已匹配学校，SID: {sid}", text_color="#2ecc71"
            )
            self.step2_next_btn.configure(state="normal")
        else:
            self.school_result_label.configure(
                text="未找到匹配的学校，请尝试更精确的关键词", text_color="#e74c3c"
            )

    def _step2_next(self):
        self.step = 2
        self._show_step()

    # -------- 步骤 3：院系 --------

    def _build_step3_college(self):
        self.step_label.configure(text="步骤 3/3：补充信息")

        ctk.CTkLabel(
            self.form_frame,
            text="院系全称",
            font=(ctk.CTkFont, FONT_MD),
        ).pack(anchor="w", padx=PAD_LG, pady=(PAD_LG, PAD_SM))

        self.college_entry = ctk.CTkEntry(
            self.form_frame,
            placeholder_text="如：经济管理学院",
            height=36,
            font=(ctk.CTkFont, FONT_MD),
        )
        self.college_entry.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))

        ctk.CTkLabel(
            self.form_frame,
            text="请务必输入院系全称，错误将导致无法匹配活动",
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        ).pack(anchor="w", padx=PAD_LG)

        ctk.CTkButton(
            self.btn_frame,
            text="上一步",
            height=36,
            fg_color="gray",
            font=(ctk.CTkFont, FONT_MD),
            command=lambda: self._go_back(1),
        ).pack(side="left")

        ctk.CTkButton(
            self.btn_frame,
            text="验证并保存",
            height=36,
            fg_color="#2e8b57",
            hover_color="#1e6b3a",
            font=(ctk.CTkFont, FONT_MD),
            command=self._step3_save,
        ).pack(side="right")

    def _step3_save(self):
        college = self.college_entry.get().strip()
        if not college:
            self.status_label.configure(text="请输入院系名称", text_color="#e74c3c")
            return

        self._data["college"] = college

        self.status_label.configure(text="正在验证登录...", text_color="gray")
        token = get_token(self._data)
        if not token:
            self.status_label.configure(
                text="登录失败，请检查用户名和密码是否正��", text_color="#e74c3c"
            )
            return

        self._data["token"] = token
        self.user_manager.add_user(self._data)
        self.user_manager.write_user_data()

        self.status_label.configure(text="用户添加成功！", text_color="#2ecc71")

        if self.on_done:
            self.after(500, self.on_done)

    # -------- 导航 --------

    def _go_back(self, target_step: int):
        self.step = target_step
        self._show_step()
