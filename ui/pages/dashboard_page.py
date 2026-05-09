"""首页：用户概览与操作入口"""
import customtkinter as ctk

from ui.styles import FONT_LG, FONT_MD, PAD_LG, PAD_MD, RADIUS
from ui.widgets.user_card import UserCard


class DashboardPage(ctk.CTkFrame):
    def __init__(self, parent, user_manager, **kwargs):
        super().__init__(parent, corner_radius=0, fg_color="transparent", **kwargs)
        self.user_manager = user_manager
        self.cards = []

        self._build_header()
        self._build_grid()
        self._build_statusbar()
        self.refresh()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        ctk.CTkLabel(
            header,
            text="首页",
            font=(ctk.CTkFont, FONT_LG, "bold"),
        ).pack(side="left")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")

        self.add_btn = ctk.CTkButton(
            btn_frame,
            text="＋ 添加用户",
            height=34,
            font=(ctk.CTkFont, FONT_MD),
        )
        self.add_btn.pack(side="left", padx=(0, PAD_MD))

        self.signup_btn = ctk.CTkButton(
            btn_frame,
            text="▶ 全部报名",
            fg_color="#2e8b57",
            hover_color="#1e6b3a",
            height=34,
            font=(ctk.CTkFont, FONT_MD),
        )
        self.signup_btn.pack(side="left")

    def _build_grid(self):
        self.grid_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=RADIUS,
        )
        self.grid_frame.pack(fill="both", expand=True, padx=PAD_LG, pady=PAD_MD)

    def _build_statusbar(self):
        self.statusbar = ctk.CTkFrame(
            self, height=36, corner_radius=0, fg_color=("#d9d9d9", "#2b2b2b")
        )
        self.statusbar.pack(fill="x", side="bottom")

        self.status_label = ctk.CTkLabel(
            self.statusbar,
            text="",
            font=(ctk.CTkFont, FONT_MD),
        )
        self.status_label.pack(side="left", padx=PAD_LG)

    def refresh(self):
        for card in self.cards:
            card.destroy()
        self.cards.clear()

        users = self.user_manager.user_datas
        total_activities = sum(len(u.get("activity_ids", [])) for u in users)

        for i, user in enumerate(users):
            card = UserCard(
                self.grid_frame,
                user,
                on_delete=self._on_delete,
                on_select_activity=self._on_select_activity,
                width=280,
                height=150,
            )
            row, col = divmod(i, 3)
            card.grid(row=row, column=col, padx=PAD_MD, pady=PAD_MD, sticky="nsew")
            self.cards.append(card)

        self.status_label.configure(
            text=f"用户: {len(users)}  |  活动: {total_activities}  |  报名中: 0"
        )

    def _on_delete(self, username: str):
        self.user_manager.remove_user(username)
        self.user_manager.write_user_data()
        self.refresh()

    def _on_select_activity(self, username: str):
        from ui.pages.activity_select_page import ActivitySelectPage

        ActivitySelectPage.show_dialog(self, username, self.user_manager, self.refresh)
