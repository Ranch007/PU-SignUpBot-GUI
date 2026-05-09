"""用户信息卡片组件"""
from typing import Callable, Dict
import customtkinter as ctk
from ui.styles import FONT_SM, FONT_MD, PAD_MD, RADIUS


class UserCard(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        user: Dict,
        on_delete: Callable,
        on_select_activity: Callable,
        **kwargs,
    ):
        super().__init__(parent, corner_radius=RADIUS, **kwargs)

        self.user = user

        # 用户名
        name_label = ctk.CTkLabel(
            self,
            text=user.get("userName", "未知"),
            font=(ctk.CTkFont, FONT_MD, "bold"),
        )
        name_label.pack(anchor="w", padx=PAD_MD, pady=(PAD_MD, 2))

        # 学院
        college = user.get("college", "未知学院")
        ctk.CTkLabel(
            self,
            text=college,
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        ).pack(anchor="w", padx=PAD_MD)

        # Token 状态
        has_token = bool(user.get("token"))
        token_text = "Token 有效" if has_token else "Token 无效"
        token_color = "#2ecc71" if has_token else "#e74c3c"
        ctk.CTkLabel(
            self,
            text=f"  {token_text}",
            font=(ctk.CTkFont, FONT_SM),
            text_color=token_color,
        ).pack(anchor="w", padx=PAD_MD, pady=2)

        # 已选活动数
        activity_count = len(user.get("activity_ids", []))
        ctk.CTkLabel(
            self,
            text=f"已选活动: {activity_count}",
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        ).pack(anchor="w", padx=PAD_MD)

        # 按钮行
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=PAD_MD, pady=PAD_MD)

        ctk.CTkButton(
            btn_frame,
            text="删除",
            fg_color="#c0392b",
            hover_color="#a93226",
            width=60,
            height=28,
            font=(ctk.CTkFont, FONT_SM),
            command=lambda: on_delete(user.get("userName")),
        ).pack(side="left", padx=(0, 5))

        ctk.CTkButton(
            btn_frame,
            text="选活动",
            width=60,
            height=28,
            font=(ctk.CTkFont, FONT_SM),
            command=lambda: on_select_activity(user.get("userName")),
        ).pack(side="left")
