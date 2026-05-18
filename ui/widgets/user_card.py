"""用户信息卡片组件"""
import threading
from typing import Callable, Dict, List
import customtkinter as ctk
from ui.styles import FONT_SM, FONT_MD, PAD_MD, PAD_SM, RADIUS, LIGHT_BORDER, DARK_BORDER, LIGHT_FRAME, DARK_FRAME


class UserCard(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        user: Dict,
        on_delete: Callable,
        on_select_activity: Callable,
        on_clear_activities: Callable,
        credit: float | None = None,
        **kwargs,
    ):
        super().__init__(
            parent,
            corner_radius=RADIUS,
            fg_color=(LIGHT_FRAME, DARK_FRAME),
            border_width=1,
            border_color=(LIGHT_BORDER, DARK_BORDER),
            **kwargs,
        )

        self.user = user
        self._activity_rows = []

        # 两列布局：左右比例 1:2
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # ========== 左板块 ==========
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsw", padx=(PAD_MD, PAD_SM), pady=PAD_MD)

        # 第一行：用户名
        ctk.CTkLabel(
            left,
            text=user.get("userName", "未知"),
            font=(ctk.CTkFont, FONT_MD, "bold"),
        ).pack(anchor="w", pady=(0, PAD_SM))

        # 第二行：学院
        college = user.get("college", "未知学院")
        ctk.CTkLabel(
            left, text=college, font=(ctk.CTkFont, FONT_MD,"bold"), text_color="gray"
        ).pack(anchor="w")

        # 第三行：学分
        credit_row = ctk.CTkFrame(left, fg_color="transparent")
        credit_row.pack(fill="x", pady=(0, PAD_SM))

        ctk.CTkLabel(
            credit_row, text="学分: ", font=(ctk.CTkFont, FONT_MD, "bold"), text_color="gray"
        ).pack(side="left")
        credit_value = f"{credit:.1f}" if credit is not None else "--"
        self.credit_label = ctk.CTkLabel(
            credit_row, text=credit_value,
            font=(ctk.CTkFont, FONT_MD), text_color="#1f6aa5",
        )
        self.credit_label.pack(side="left")

        # 第三行：Token 状态（带圆点）
        has_token = bool(user.get("token"))
        dot = "●" if has_token else "●"
        token_text = "Token 有效" if has_token else "Token 无效"
        token_color = "#2ecc71" if has_token else "#e74c3c"
        self.token_label = ctk.CTkLabel(
            left,
            text=f"{dot} {token_text}",
            font=(ctk.CTkFont, FONT_SM),
            text_color=token_color,
        )
        self.token_label.pack(anchor="w", pady=(0, PAD_MD))

        # 按钮行
        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame,
            text="删除",
            fg_color="#c0392b",
            hover_color="#a93226",
            width=52,
            height=26,
            font=(ctk.CTkFont, FONT_SM),
            command=lambda: on_delete(user.get("userName")),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btn_frame,
            text="选活动",
            width=52,
            height=26,
            font=(ctk.CTkFont, FONT_SM),
            command=lambda: on_select_activity(user.get("userName")),
        ).pack(side="left")

        # ========== 右板块 ==========
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(PAD_SM, PAD_MD), pady=PAD_MD)

        activity_ids = user.get("activity_ids", [])
        right_header = ctk.CTkFrame(right, fg_color="transparent")
        right_header.pack(fill="x", pady=(0, 2))

        self.activity_count_label = ctk.CTkLabel(
            right_header,
            text=f"已选活动: {len(activity_ids)}",
            font=(ctk.CTkFont, FONT_SM, "bold"),
        )
        self.activity_count_label.pack(side="left")

        self.clear_btn = ctk.CTkButton(
            right_header,
            text="清空活动",
            fg_color="gray",
            width=52,
            height=22,
            font=(ctk.CTkFont, FONT_SM - 2),
            command=lambda: on_clear_activities(user.get("userName")),
            state="normal" if activity_ids else "disabled",
        )
        self.clear_btn.pack(side="right")

        self.activity_scroll = ctk.CTkScrollableFrame(
            right,
            fg_color="transparent",
            corner_radius=4,
        )
        self.activity_scroll.pack(fill="both", expand=True)
        self.activity_scroll.grid_columnconfigure(0, weight=1)
        self.activity_scroll.grid_columnconfigure(1, minsize=55)
        self.activity_scroll.grid_columnconfigure(2, minsize=65)

    def set_credit(self, credit: float):
        self.credit_label.configure(text=f"{credit:.1f}")

    def set_token_status(self, valid: bool):
        dot = "●" if valid else "●"
        color = "#2ecc71" if valid else "#e74c3c"
        text = "Token 有效" if valid else "Token 无效"
        self.token_label.configure(text=f"{dot} {text}", text_color=color)

    def load_activities(self):
        """后台获取活动详情并更新右板块"""
        activity_ids = self.user.get("activity_ids", [])
        if not activity_ids:
            self._show_activity_placeholder("暂无已选活动")
            return

        self._show_activity_placeholder("加载中...")

        def _run():
            from core.tools import get_info
            token = self.user.get("token", "")
            sid = str(self.user.get("sid", ""))
            activities = []
            for aid in activity_ids:
                info = get_info(str(aid), token, sid)
                if info:
                    activities.append({
                        "name": info.get("name", str(aid)),
                        "credit": info.get("credit", 0),
                        "startTime": info.get("startTime", ""),
                    })
            self.after(0, lambda: self._populate_activities(activities))

        threading.Thread(target=_run, daemon=True).start()

    def _show_activity_placeholder(self, text: str):
        self._clear_activities()
        lbl = ctk.CTkLabel(
            self.activity_scroll,
            text=text,
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        )
        lbl.grid(row=0, column=0, sticky="w", padx=4, pady=2, columnspan=3)
        self._activity_rows.append(lbl)

    def _populate_activities(self, activities: List[Dict]):
        self._clear_activities()
        if not activities:
            self._show_activity_placeholder("暂无已选活动")
            return

        for i, a in enumerate(activities):
            name = a["name"]
            credit = a.get("credit", 0)
            raw_time = a.get("startTime", "")
            if len(raw_time) >= 16:
                start_time = raw_time[5:16]
            else:
                start_time = raw_time

            lbl_name = ctk.CTkLabel(
                self.activity_scroll, text=name, anchor="w",
                font=(ctk.CTkFont, FONT_SM - 1), text_color="gray",
            )
            lbl_name.grid(row=i, column=0, sticky="w", padx=(4, 2), pady=1)
            self._activity_rows.append(lbl_name)

            lbl_credit = ctk.CTkLabel(
                self.activity_scroll, text=f"{credit}分", anchor="e",
                font=(ctk.CTkFont, FONT_SM - 1), text_color="gray",
            )
            lbl_credit.grid(row=i, column=1, sticky="e", padx=(4, 10), pady=1)
            self._activity_rows.append(lbl_credit)

            lbl_time = ctk.CTkLabel(
                self.activity_scroll, text=start_time, anchor="w",
                font=(ctk.CTkFont, FONT_SM - 1), text_color="gray",
            )
            lbl_time.grid(row=i, column=2, sticky="w", padx=(0, 2), pady=1)
            self._activity_rows.append(lbl_time)

        self.activity_count_label.configure(text=f"已选活动: {len(activities)}")

    def _clear_activities(self):
        for w in self._activity_rows:
            w.destroy()
        self._activity_rows.clear()
