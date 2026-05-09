"""活动筛选与选择页面"""
from typing import Dict, List
import threading
import customtkinter as ctk

from ui.styles import (
    FONT_XL, FONT_LG, FONT_MD, FONT_SM,
    PAD_XS, PAD_SM, PAD_MD, PAD_LG, RADIUS,
)
from core.tools import get_activity_type, get_allowed_activity_list


class ActivitySelectPage(ctk.CTkFrame):
    def __init__(self, parent, user_manager, **kwargs):
        super().__init__(parent, corner_radius=0, fg_color="transparent", **kwargs)
        self.user_manager = user_manager
        self._activities: List[Dict] = []
        self._checked: Dict[str, bool] = {}
        self._selected_user: str | None = None
        self._filter_widgets: Dict[str, list] = {}

        self._build()

    def select_user(self, username: str):
        """外部调用：预选用户并加载活动数据"""
        self._selected_user = username
        self._user_dropdown.set(username)

        user = self.user_manager.get_user(username)
        if user and user.get("token"):
            self._load_filters(user)
        else:
            self._show_empty("Token 已过期，请重新添加用户")

    # ======================== 构建 ========================

    def _build(self):
        # 标题行
        title_bar = ctk.CTkFrame(self, fg_color="transparent")
        title_bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        ctk.CTkLabel(
            title_bar,
            text="选择活动",
            font=(ctk.CTkFont, FONT_XL, "bold"),
        ).pack(side="left")

        # 用户下拉 + 操作按钮
        self._user_dropdown = ctk.CTkComboBox(
            title_bar,
            values=[""],
            width=160,
            height=34,
            font=(ctk.CTkFont, FONT_MD),
            command=self._on_user_changed,
        )
        self._user_dropdown.pack(side="right", padx=(0, PAD_SM))

        self._fetch_btn = ctk.CTkButton(
            title_bar,
            text="获取活动",
            height=34,
            font=(ctk.CTkFont, FONT_MD),
            command=self._on_fetch_clicked,
        )
        self._fetch_btn.pack(side="right", padx=(0, PAD_SM))

        self._save_btn = ctk.CTkButton(
            title_bar,
            text="保存选择",
            height=34,
            fg_color="#2e8b57",
            hover_color="#1e6b3a",
            font=(ctk.CTkFont, FONT_MD),
            command=self._on_save,
        )
        self._save_btn.pack(side="right", padx=(0, PAD_MD))

        # 提示
        hint = ctk.CTkLabel(
            self,
            text="筛选规则：同级维度内为 OR（多选），跨维度为 AND（交集）",
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        )
        hint.pack(anchor="w", padx=PAD_LG, pady=(0, PAD_MD))

        # 主内容区
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=PAD_LG, pady=(0, PAD_LG))

        # 左侧筛选
        self._filter_scroll = ctk.CTkScrollableFrame(
            main, width=260, corner_radius=RADIUS
        )
        self._filter_scroll.pack(side="left", fill="y", padx=(0, PAD_MD))

        # 右侧活动列表
        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        self._count_label = ctk.CTkLabel(
            right, text="", font=(ctk.CTkFont, FONT_SM), text_color="gray"
        )
        self._count_label.pack(anchor="w", pady=(0, PAD_SM))

        self._list_scroll = ctk.CTkScrollableFrame(right, corner_radius=RADIUS)
        self._list_scroll.pack(fill="both", expand=True)

    # ======================== 数据加载 ========================

    def _on_user_changed(self, choice: str):
        if not choice:
            return
        self._selected_user = choice
        user = self.user_manager.get_user(choice)
        if user and user.get("token"):
            self._load_filters(user)
        else:
            self._show_empty("Token 已过期，请重新添加用户")

    def _load_filters(self, user: Dict):
        self._clear_filter()
        self._clear_list()

        # 用户信息
        info_frame = ctk.CTkFrame(self._filter_scroll, fg_color="transparent")
        info_frame.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))

        ctk.CTkLabel(
            info_frame,
            text=f"当前用户：{self._selected_user}",
            font=(ctk.CTkFont, FONT_MD, "bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            info_frame,
            text=f"院系：{user.get('college', '未知')}",
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        ).pack(anchor="w")

        sep = ctk.CTkFrame(self._filter_scroll, height=2, fg_color=("gray80", "gray30"))
        sep.pack(fill="x", padx=PAD_MD, pady=PAD_MD)

        ctk.CTkLabel(
            self._filter_scroll,
            text="筛选条件",
            font=(ctk.CTkFont, FONT_MD, "bold"),
        ).pack(anchor="w", padx=PAD_MD, pady=(0, PAD_MD))

        types = get_activity_type(user.get("token"), str(user.get("sid")))
        if types:
            self._build_filter_widgets(types, user)
        else:
            ctk.CTkLabel(
                self._filter_scroll,
                text="无法加载筛选条件",
                font=(ctk.CTkFont, FONT_SM),
                text_color="gray",
            ).pack(padx=PAD_MD)

    def _build_filter_widgets(self, activity_types: List[Dict], user: Dict):
        self._filter_widgets.clear()
        for at in activity_types:
            key = at.get("key", "")
            name = at.get("name", "未知")

            section = ctk.CTkFrame(
                self._filter_scroll, corner_radius=RADIUS, fg_color=("gray95", "gray17")
            )
            section.pack(fill="x", padx=PAD_MD, pady=PAD_SM)

            ctk.CTkLabel(
                section,
                text=name,
                font=(ctk.CTkFont, FONT_SM, "bold"),
            ).pack(anchor="w", padx=PAD_SM, pady=(PAD_SM, 2))

            self._filter_widgets[key] = []
            for info in at.get("infoList", []):
                info_id = str(info.get("id"))
                var = ctk.BooleanVar(
                    value=(key == "allowYears") or (info_id in user.get(key, []))
                )
                ctk.CTkCheckBox(
                    section,
                    text=info.get("name", info_id),
                    font=(ctk.CTkFont, FONT_SM),
                    variable=var,
                ).pack(anchor="w", padx=PAD_SM, pady=1)
                self._filter_widgets[key].append((info_id, var))

    def _on_fetch_clicked(self):
        if not self._selected_user:
            self._count_label.configure(text="请先选择用户", text_color="#e74c3c")
            return

        user = self.user_manager.get_user(self._selected_user)
        if not user:
            return

        # 应用筛选条件
        for key, widgets in self._filter_widgets.items():
            selected = [iid for iid, var in widgets if var.get()]
            if selected:
                user[key] = selected
            else:
                user.pop(key, None)

        self._count_label.configure(text="加载中...", text_color="gray")
        self._clear_list()

        def _fetch():
            activities = get_allowed_activity_list(user)
            self.after(0, lambda: self._display(activities))

        threading.Thread(target=_fetch, daemon=True).start()

    def _display(self, activities: List[Dict]):
        self._activities = activities
        self._checked.clear()

        existing = set(
            self.user_manager.get_user(self._selected_user).get("activity_ids", [])
        )

        for a in activities:
            aid = str(a.get("activity_id"))
            self._checked[aid] = aid in existing

            row = ctk.CTkFrame(self._list_scroll, corner_radius=6)
            row.pack(fill="x", padx=PAD_SM, pady=2)

            var = ctk.BooleanVar(value=self._checked[aid])
            ctk.CTkCheckBox(
                row,
                text="",
                width=20,
                variable=var,
                command=lambda a=aid, v=var: self._toggle(a, v.get()),
            ).pack(side="left", padx=PAD_SM)

            info_text = (
                f"{a.get('活动名称', '')}  |  "
                f"{a.get('分数', 0)}分  |  "
                f"{a.get('活动分类', '')}  |  "
                f"{a.get('举办组织', '')}  |  "
                f"剩余名额: {a.get('可报名人数', '-')}"
            )
            ctk.CTkLabel(
                row,
                text=info_text,
                font=(ctk.CTkFont, FONT_SM),
            ).pack(side="left", padx=PAD_SM, pady=PAD_SM)

        self._count_label.configure(
            text=f"共找到 {len(activities)} 个活动", text_color="gray"
        )

    def _toggle(self, activity_id: str, checked: bool):
        self._checked[activity_id] = checked

    def _on_save(self):
        if not self._selected_user:
            return
        selected = [aid for aid, v in self._checked.items() if v]
        self.user_manager.update_user(self._selected_user, {"activity_ids": selected})
        self.user_manager.write_user_data()

        self._save_btn.configure(text="已保存 ✓", fg_color="#27ae60")
        self.after(1500, lambda: self._save_btn.configure(
            text="保存选择", fg_color="#2e8b57"
        ))

    # ======================== 工具 ========================

    def refresh(self):
        """刷新用户下拉列表"""
        users = self.user_manager.user_datas
        names = [u.get("userName", "") for u in users]
        self._user_dropdown.configure(values=names)

        if self._selected_user and self._selected_user not in names:
            self._selected_user = None
            self._clear_filter()
            self._clear_list()

    def _on_show(self):
        """外部调用：页面显示时刷新"""
        self.refresh()

    def _clear_filter(self):
        for w in self._filter_scroll.winfo_children():
            w.destroy()

    def _clear_list(self):
        for w in self._list_scroll.winfo_children():
            w.destroy()

    def _show_empty(self, msg: str):
        self._clear_filter()
        self._clear_list()
        self._count_label.configure(text=msg, text_color="#e74c3c")
