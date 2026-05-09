"""活动筛选与选择页面"""
from typing import Dict, List
import threading
import customtkinter as ctk

from ui.styles import FONT_XL, FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, RADIUS
from core.tools import get_activity_type, get_allowed_activity_list


class ActivitySelectPage(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        user_manager,
        log_queue=None,
        **kwargs,
    ):
        super().__init__(parent, corner_radius=0, fg_color="transparent", **kwargs)
        self.user_manager = user_manager
        self.log_queue = log_queue
        self._activities: List[Dict] = []
        self._checked: Dict[str, bool] = {}
        self._selected_user = None
        self._filter_widgets = {}

        self._build()

    @staticmethod
    def show_dialog(parent, username: str, user_manager, on_close=None):
        """弹出活动选择对话框"""
        dialog = ctk.CTkToplevel(parent)
        dialog.title(f"选择活动 - {username}")
        dialog.geometry("900x620")
        dialog.minsize(700, 500)

        page = ActivitySelectPage(
            dialog,
            user_manager,
        )
        page.pack(fill="both", expand=True)
        page._selected_user = username

        user = user_manager.get_user(username)
        if user and user.get("token"):
            existing_ids = set(user.get("activity_ids", []))
            page._get_activities(user)
        else:
            page._show_refresh_token_prompt()

        page._save_btn.configure(
            command=lambda: page._save_selection(username, dialog, on_close)
        )

        dialog.transient(parent)
        dialog.grab_set()

    def _build(self):
        # 标题
        ctk.CTkLabel(
            self,
            text="选择活动",
            font=(ctk.CTkFont, FONT_XL, "bold"),
        ).pack(anchor="w", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        # 筛选逻辑提示
        ctk.CTkLabel(
            self,
            text="筛选规则：同级维度内为 OR（多选），跨维度为 AND（交集）",
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        ).pack(anchor="w", padx=PAD_LG, pady=(0, PAD_MD))

        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=PAD_LG, pady=(0, PAD_MD))

        # 左侧筛选面板
        self.filter_frame = ctk.CTkScrollableFrame(
            main_frame,
            width=280,
            corner_radius=RADIUS,
        )
        self.filter_frame.pack(side="left", fill="y", padx=(0, PAD_MD))

        # 右侧活动列表
        right_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        right_frame.pack(side="left", fill="both", expand=True)

        top_bar = ctk.CTkFrame(right_frame, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, PAD_MD))

        self.count_label = ctk.CTkLabel(
            top_bar, text="", font=(ctk.CTkFont, FONT_SM), text_color="gray"
        )
        self.count_label.pack(side="left")

        self._save_btn = ctk.CTkButton(
            top_bar,
            text="保存选择",
            height=34,
            font=(ctk.CTkFont, FONT_MD),
        )
        self._save_btn.pack(side="right")

        self.activity_list_frame = ctk.CTkScrollableFrame(
            right_frame,
            corner_radius=RADIUS,
        )
        self.activity_list_frame.pack(fill="both", expand=True)

    def _show_refresh_token_prompt(self):
        user = self.user_manager.get_user(self._selected_user)
        self.status_label = ctk.CTkLabel(
            self.filter_frame,
            text="Token 已过期\n请回到首页重新添加用户",
            font=(ctk.CTkFont, FONT_SM),
            text_color="#e74c3c",
        )
        self.status_label.pack(padx=PAD_MD, pady=PAD_LG)

    def _get_activities(self, user: Dict):
        self._clear_filter()
        self._clear_list()

        ctk.CTkLabel(
            self.filter_frame,
            text=f"当前用户: {self._selected_user}",
            font=(ctk.CTkFont, FONT_MD, "bold"),
        ).pack(anchor="w", padx=PAD_MD, pady=(PAD_MD, PAD_SM))

        ctk.CTkButton(
            self.filter_frame,
            text="获取活动",
            height=32,
            font=(ctk.CTkFont, FONT_SM),
            command=lambda: self._load_activities(user),
        ).pack(fill="x", padx=PAD_MD, pady=(0, PAD_MD))

        ctk.CTkLabel(
            self.filter_frame,
            text="筛选条件：",
            font=(ctk.CTkFont, FONT_MD, "bold"),
        ).pack(anchor="w", padx=PAD_MD, pady=(PAD_MD, PAD_SM))

        types = get_activity_type(user.get("token"), str(user.get("sid")))
        if types:
            self._build_filters(types, user)

    def _build_filters(self, activity_types: List[Dict], user: Dict):
        existing_ids = set(user.get("activity_ids", []))
        for at in activity_types:
            key = at.get("key")
            name = at.get("name", "未知")

            expandable = ctk.CTkFrame(self.filter_frame, fg_color="transparent")
            expandable.pack(fill="x", padx=PAD_MD, pady=PAD_SM)

            ctk.CTkLabel(
                expandable,
                text=f"▼ {name}",
                font=(ctk.CTkFont, FONT_SM, "bold"),
            ).pack(anchor="w", pady=(0, PAD_SM))

            self._filter_widgets[key] = []
            for info in at.get("infoList", []):
                info_id = str(info.get("id"))
                var = ctk.BooleanVar(
                    value=key == "allowYears"
                    or (info_id in user.get(key, []))
                )
                cb = ctk.CTkCheckBox(
                    expandable,
                    text=info.get("name", info_id),
                    font=(ctk.CTkFont, FONT_SM),
                    variable=var,
                )
                cb.pack(anchor="w", padx=PAD_SM)
                self._filter_widgets[key].append((info_id, var))

    def _load_activities(self, user: Dict):
        self.count_label.configure(text="加载中...")
        self._clear_list()

        for key, widgets in self._filter_widgets.items():
            selected = [info_id for info_id, var in widgets if var.get()]
            if selected:
                user[key] = selected
            else:
                user.pop(key, None)

        def _fetch():
            activities = get_allowed_activity_list(user)
            self.after(0, lambda: self._display_activities(activities))

        threading.Thread(target=_fetch, daemon=True).start()

    def _display_activities(self, activities: List[Dict]):
        self._activities = activities
        self._checked.clear()

        existing_ids = set(
            self.user_manager.get_user(self._selected_user).get("activity_ids", [])
        )

        for a in activities:
            aid = str(a.get("activity_id"))
            self._checked[aid] = aid in existing_ids

            row = ctk.CTkFrame(
                self.activity_list_frame,
                corner_radius=RADIUS,
            )
            row.pack(fill="x", padx=PAD_SM, pady=2)

            var = ctk.BooleanVar(value=self._checked[aid])
            ctk.CTkCheckBox(
                row,
                text="",
                width=20,
                variable=var,
                command=lambda a=aid, v=var: self._toggle(a, v.get()),
            ).pack(side="left", padx=(PAD_SM, 0))

            ctk.CTkLabel(
                row,
                text=f"{a.get('活动名称', '')}  |  "
                     f"{a.get('分数', 0)}分  |  "
                     f"{a.get('活动分类', '')}  |  "
                     f"{a.get('举办组织', '')}",
                font=(ctk.CTkFont, FONT_SM),
            ).pack(side="left", padx=PAD_SM, pady=PAD_SM)

        self.count_label.configure(text=f"共找到 {len(activities)} 个活动")

    def _toggle(self, activity_id: str, checked: bool):
        self._checked[activity_id] = checked

    def _save_selection(self, username: str, dialog, on_close=None):
        selected_ids = [aid for aid, v in self._checked.items() if v]
        self.user_manager.update_user(username, {"activity_ids": selected_ids})
        self.user_manager.write_user_data()
        if on_close:
            on_close()
        dialog.destroy()

    def _clear_filter(self):
        for w in self.filter_frame.winfo_children():
            w.destroy()

    def _clear_list(self):
        for w in self.activity_list_frame.winfo_children():
            w.destroy()
