"""用户信息卡片组件"""
import threading
from queue import Empty, Queue
from typing import Callable, Dict, List
import customtkinter as ctk
from core.activity_plan import parse_activity_time
from core.accounts import account_key, credential_snapshot, credentials_match
from ui.styles import FONT_SM, FONT_MD, PAD_MD, PAD_SM, RADIUS, LIGHT_BORDER, DARK_BORDER, LIGHT_FRAME, DARK_FRAME


class UserCard(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        user: Dict,
        on_delete: Callable,
        on_select_activity: Callable,
        on_clear_activities: Callable,
        on_relogin: Callable,
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
        self._activity_row_widgets = []  # [(名称, 学分, 时间)] 三元组，供宽窄布局重排
        self._wide_layout = None
        self._detail_results = Queue()
        self._detail_generation = 0
        self._detail_poll_id = self.after(100, self._poll_details)

        # 卡片占一整行：账号信息按内容宽度，活动列表吸收全部剩余空间。
        self.grid_columnconfigure(1, weight=1)

        # ========== 左板块 ==========
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsw", padx=(PAD_MD, PAD_SM), pady=PAD_MD)

        # 第一行：用户名
        user_name = user.get("userName", "未知")
        realname = user.get("realname")
        ctk.CTkLabel(
            left,
            text=f"{user_name} · {realname}" if realname else user_name,
            font=(ctk.CTkFont, FONT_MD, "bold"),
            height=26,
        ).pack(anchor="w", pady=(0, PAD_SM))

        # 第二行：学校 · 学院 · 年级（缺哪段就显示哪段）
        parts = [user.get("school"), user.get("college", "未知学院")]
        if user.get("year"):
            parts.append(f"{user['year']}级")
        school_line = " · ".join(str(p) for p in parts if p) or "未知学院"
        ctk.CTkLabel(
            left, text=school_line, font=(ctk.CTkFont, FONT_SM),
            text_color=("#55514d", "#c1c1c1")
        ).pack(anchor="w")

        # 第三行：学分
        credit_row = ctk.CTkFrame(left, fg_color="transparent")
        credit_row.pack(fill="x", pady=(0, PAD_SM))

        ctk.CTkLabel(
            credit_row, text="学分: ", font=(ctk.CTkFont, FONT_MD, "bold"),
            text_color=("#55514d", "#c1c1c1")
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
        token_text = (user.get("credential_error") or
                      ("登录待验证" if has_token else "未登录"))
        token_color = ("#55514d", "#c1c1c1") if has_token and not user.get("credential_error") else ("#a72727", "#ff8989")
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
            width=64,
            height=30,
            font=(ctk.CTkFont, FONT_SM),
            command=lambda: on_delete(account_key(user)),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btn_frame,
            text="选活动",
            width=70,
            height=30,
            font=(ctk.CTkFont, FONT_SM),
            command=lambda: on_select_activity(account_key(user)),
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="重新登录",
            width=78,
            height=30,
            font=(ctk.CTkFont, FONT_SM),
            command=lambda: on_relogin(account_key(user)),
        ).pack(side="left", padx=(4, 0))

        # ========== 右板块 ==========
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="new", padx=(PAD_SM, PAD_MD), pady=PAD_MD)

        activity_ids = user.get("activity_ids", [])
        right_header = ctk.CTkFrame(right, fg_color="transparent")
        right_header.pack(fill="x", pady=(0, 2))

        self.activity_count_label = ctk.CTkLabel(
            right_header,
            text=f"已选活动: {len(activity_ids)}",
            font=(ctk.CTkFont, FONT_MD, "bold"),
            height=26,
        )
        self.activity_count_label.pack(side="left")

        self.clear_btn = ctk.CTkButton(
            right_header,
            text="清空活动",
            fg_color="gray",
            width=76,
            height=26,
            font=(ctk.CTkFont, FONT_MD),
            command=lambda: on_clear_activities(account_key(user)),
            state="normal" if activity_ids else "disabled",
        )
        self.clear_btn.pack(side="right")

        self.activity_scroll = ctk.CTkScrollableFrame(
            right,
            fg_color="transparent",
            corner_radius=4,
            height=108,
        )
        # CTkScrollableFrame 的滚动条默认高 200，会反过来撑大整张卡片。
        self.activity_scroll._scrollbar.configure(height=108)
        self.activity_scroll.pack(fill="x")
        # 内容左紧凑：唯一拉伸列放在末尾，多余空间留在右侧
        self.activity_scroll.grid_columnconfigure(3, weight=1)
        self.activity_scroll.grid_columnconfigure(1, minsize=55)
        self.activity_scroll.bind("<Configure>", lambda e: self._relayout_if_needed())

    def set_credit(self, credit: float):
        self.credit_label.configure(text=f"{credit:.1f}")

    def set_token_status(self, valid: bool):
        dot = "●" if valid else "●"
        color = ("#196b42", "#6bd69b") if valid else ("#a72727", "#ff8989")
        text = "已登录" if valid else "登录已过期"
        self.token_label.configure(text=f"{dot} {text}", text_color=color)

    def load_activities(self):
        """后台获取活动详情并更新右板块"""
        activity_ids = self.user.get("activity_ids", [])
        if not activity_ids:
            self._show_activity_placeholder("暂无已选活动")
            return

        self._show_activity_placeholder("加载中...")
        self._detail_generation += 1
        generation = self._detail_generation
        snapshot = credential_snapshot(self.user)
        user_data = dict(self.user)

        def _run():
            from core.tools import get_info
            token = user_data.get("token", "")
            sid = str(user_data.get("sid", ""))
            activities = []
            errors = []
            for aid in activity_ids:
                try:
                    info = get_info(str(aid), token, sid, strict=True)
                    activities.append({
                        "name": info.get("name", str(aid)),
                        "credit": info.get("credit", 0),
                        "startTime": info.get("startTime", ""),
                        "joinStartTime": info.get("joinStartTime", ""),
                        "joinEndTime": info.get("joinEndTime", ""),
                        "endTime": info.get("endTime", ""),
                    })
                except Exception as exc:
                    errors.append(f"活动 {aid}：{exc}")
            self._detail_results.put((generation, snapshot, activities, errors))

        threading.Thread(target=_run, daemon=True).start()

    def _poll_details(self):
        while True:
            try:
                generation, snapshot, activities, errors = self._detail_results.get_nowait()
            except Empty:
                break
            if generation == self._detail_generation and credentials_match(self.user, snapshot):
                if activities:
                    self._populate_activities(activities)
                else:
                    self._show_activity_placeholder("详情加载失败，请刷新或重新登录" if errors else "暂无已选活动")
                if errors:
                    label = ctk.CTkLabel(self.activity_scroll, text="；".join(errors),
                                        font=(ctk.CTkFont, FONT_SM), text_color="#c0392b",
                                        wraplength=500, justify="left")
                    label.grid(row=len(activities) * 2 + 1, column=0, columnspan=4, sticky="w")
                    self._activity_rows.append(label)
                self.activity_count_label.configure(text=f"已选活动: {len(self.user.get('activity_ids', []))}")
        self._detail_poll_id = self.after(100, self._poll_details)

    def destroy(self):
        self._detail_generation += 1
        if self._detail_poll_id:
            self.after_cancel(self._detail_poll_id)
            self._detail_poll_id = None
        super().destroy()

    def _show_activity_placeholder(self, text: str):
        self._clear_activities()
        lbl = ctk.CTkLabel(
            self.activity_scroll,
            text=text,
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        )
        lbl.grid(row=0, column=0, sticky="w", padx=4, pady=2, columnspan=4)
        self._activity_rows.append(lbl)

    def _populate_activities(self, activities: List[Dict]):
        self._clear_activities()
        if not activities:
            self._show_activity_placeholder("暂无已选活动")
            return

        for a in activities:
            name = a["name"]
            credit = a.get("credit", 0)

            lbl_name = ctk.CTkLabel(
                self.activity_scroll, text=name, anchor="w",
                font=(ctk.CTkFont, FONT_SM, "bold"),
                text_color=("#34312e", "#e0e0e0"),
            )
            self._activity_rows.append(lbl_name)

            lbl_credit = ctk.CTkLabel(
                self.activity_scroll, text=f"{credit}分", anchor="e",
                font=(ctk.CTkFont, FONT_SM),
                text_color=("#55514d", "#c1c1c1"),
            )
            self._activity_rows.append(lbl_credit)

            lbl_time = ctk.CTkLabel(
                self.activity_scroll, text=self._time_text(a), anchor="w",
                font=(ctk.CTkFont, FONT_SM),
                text_color=("#55514d", "#c1c1c1"),
            )
            self._activity_rows.append(lbl_time)
            self._activity_row_widgets.append((lbl_name, lbl_credit, lbl_time))

        self._wide_layout = None  # 数据重建后强制重新判定布局
        self._relayout_if_needed()
        self.activity_count_label.configure(text=f"已选活动: {len(activities)}")

    @staticmethod
    def _time_text(a):
        """活动开始与结束时间区间；时间缺失时尽量显示已知部分。"""
        parts = []
        start = parse_activity_time(a.get("startTime"))
        end = parse_activity_time(a.get("endTime"))
        if start:
            parts.append(f"活动开始：{start:%m-%d %H:%M}")
        if end:
            parts.append(f"活动结束：{end:%m-%d %H:%M}")
        return " ~ ".join(parts)

    def _relayout_if_needed(self):
        """窗口够宽时时间排第三列（单行紧凑），不够时落到第二行（完整显示）。"""
        if not self._activity_row_widgets:
            return
        width = self.activity_scroll.winfo_width()
        if width < 50:
            wide = False
        else:
            need = max(t.winfo_reqwidth() for _, _, t in self._activity_row_widgets) + 55 + 120
            wide = width >= need
        if wide != self._wide_layout:
            self._wide_layout = wide
            self._apply_row_layout(wide)

    def _apply_row_layout(self, wide: bool):
        for i, (lbl_name, lbl_credit, lbl_time) in enumerate(self._activity_row_widgets):
            if wide:
                lbl_name.grid(row=i, column=0, sticky="w", padx=(4, 2), pady=1)
                lbl_credit.grid(row=i, column=1, sticky="e", padx=(4, 10), pady=1)
                lbl_time.grid(row=i, column=2, sticky="w", padx=(0, 2), pady=1)
            else:
                row = i * 2
                lbl_name.grid(row=row, column=0, sticky="w", padx=(4, 2), pady=(1, 0))
                lbl_credit.grid(row=row, column=1, sticky="e", padx=(4, 10), pady=(1, 0))
                lbl_time.grid(row=row + 1, column=0, columnspan=4, sticky="w",
                              padx=(4, 2), pady=(0, 1))

    def _clear_activities(self):
        for w in self._activity_rows:
            w.destroy()
        self._activity_rows.clear()
        self._activity_row_widgets.clear()
        self._wide_layout = None
