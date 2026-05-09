"""Dashboard 单页：用户卡片 + 内联表单区 + 日志"""
import customtkinter as ctk

from ui.styles import (
    FONT_XL, FONT_LG, FONT_MD, FONT_SM,
    PAD_LG, PAD_MD, PAD_SM, RADIUS,
)
from ui.widgets.user_card import UserCard
from ui.widgets.log_widget import LogWidget


class DashboardPage(ctk.CTkFrame):
    def __init__(self, parent, user_manager, log_queue=None, **kwargs):
        super().__init__(parent, corner_radius=0, fg_color="transparent", **kwargs)
        self.user_manager = user_manager
        self.log_queue = log_queue
        self.cards = []
        self._inline = None  # 当前内联表单

        self._build_header()
        self._build_main()
        self._build_log()
        self._build_statusbar()
        self.refresh()

    # ======================== 头部 ========================

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left")

        ctk.CTkLabel(title_col, text="PU-SignUpBot", font=(ctk.CTkFont, FONT_XL, "bold")).pack(anchor="w")
        ctk.CTkLabel(title_col, text="PU 口袋校园报名助手", font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(anchor="w")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")

        self.add_btn = ctk.CTkButton(btn_frame, text="＋ 添加用户", height=36, font=(ctk.CTkFont, FONT_MD), command=self._show_add_user)
        self.add_btn.pack(side="left", padx=(0, PAD_SM))

        self.signup_btn = ctk.CTkButton(btn_frame, text="▶ 全部报名", fg_color="#2e8b57", hover_color="#1e6b3a", height=36, font=(ctk.CTkFont, FONT_MD), command=self._show_signup)
        self.signup_btn.pack(side="left")

    # ======================== 主体 ========================

    def _build_main(self):
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.pack(fill="both", expand=True, padx=PAD_LG)

        # 用户卡片区
        self.cards_frame = ctk.CTkScrollableFrame(self.main_area, fg_color="transparent", corner_radius=RADIUS)
        self.cards_frame.pack(fill="both", expand=True)
        for i in range(3):
            self.cards_frame.grid_columnconfigure(i, weight=1)

        # 内联表单区（初始隐藏，动态 pack/unpack）
        self.inline_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")

    # ======================== 日志区 ========================

    def _build_log(self):
        log_section = ctk.CTkFrame(self, fg_color="transparent")
        log_section.pack(fill="x", padx=PAD_LG, pady=(PAD_MD, 0))

        ctk.CTkLabel(log_section, text="实时日志", font=(ctk.CTkFont, FONT_LG, "bold")).pack(anchor="w")

        self.log_widget = LogWidget(log_section, log_queue=self.log_queue, height=120)
        self.log_widget.pack(fill="x", pady=(PAD_SM, 0))

    # ======================== 状态栏 ========================

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, height=32, corner_radius=0, fg_color=("gray85", "gray20"))
        bar.pack(fill="x", side="bottom")
        self.status_label = ctk.CTkLabel(bar, text="", font=(ctk.CTkFont, FONT_MD))
        self.status_label.pack(side="left", padx=PAD_LG)

    # ======================== 用户卡片 ========================

    def refresh(self):
        for card in self.cards:
            card.destroy()
        self.cards.clear()

        users = self.user_manager.user_datas
        total = sum(len(u.get("activity_ids", [])) for u in users)

        if not users:
            ctk.CTkLabel(
                self.cards_frame, text="暂无用户\n点击「＋ 添加用户」开始",
                font=(ctk.CTkFont, FONT_LG), text_color="gray",
            ).grid(row=0, column=0, columnspan=3, pady=80)

        for i, user in enumerate(users):
            card = UserCard(
                self.cards_frame, user,
                on_delete=self._on_delete,
                on_select_activity=self._on_select_activity,
                width=280, height=150,
            )
            row, col = divmod(i, 3)
            card.grid(row=row, column=col, padx=PAD_MD, pady=PAD_MD, sticky="nsew")
            self.cards.append(card)

        self.status_label.configure(text=f"用户: {len(users)}  |  活动: {total}")
        self.signup_btn.configure(state="normal" if users else "disabled")

    # ======================== 内联表单管理 ========================

    def _show_inline(self, widget):
        """显示内联表单，隐藏之前的内容"""
        self._hide_inline()
        self.cards_frame.pack_forget()
        self.inline_frame.pack(fill="both", expand=True, pady=(0, PAD_MD))
        widget.pack(fill="both", expand=True)
        self._inline = widget

    def _hide_inline(self):
        if self._inline:
            self._inline.pack_forget()
            self._inline = None
        self.inline_frame.pack_forget()
        self.cards_frame.pack(fill="both", expand=True, pady=(0, PAD_MD))

    def _show_add_user(self):
        for child in self.inline_frame.winfo_children():
            child.destroy()
        from ui.pages.add_user_inline import AddUserInline
        w = AddUserInline(
            self.inline_frame,
            self.user_manager,
            on_done=lambda: [self._hide_inline(), self.refresh()],
            on_cancel=self._hide_inline,
        )
        self._show_inline(w)

    def _show_signup(self):
        for child in self.inline_frame.winfo_children():
            child.destroy()
        from ui.pages.signup_inline import SignupInline
        w = SignupInline(
            self.inline_frame,
            self.user_manager,
            self.log_queue,
            on_close=self._hide_inline,
        )
        self._show_inline(w)

    # ======================== 回调 ========================

    def _on_delete(self, username: str):
        self.user_manager.remove_user(username)
        self.user_manager.write_user_data()
        self.refresh()

    def _on_select_activity(self, username: str):
        for child in self.inline_frame.winfo_children():
            child.destroy()
        from ui.pages.activity_select_inline import ActivitySelectInline
        w = ActivitySelectInline(
            self.inline_frame,
            username,
            self.user_manager,
            on_close=lambda: [self._hide_inline(), self.refresh()],
        )
        self._show_inline(w)
