"""活动选择内联面板"""
from typing import Dict, List, Callable
import threading
import customtkinter as ctk

from ui.styles import FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, PAD_XS, RADIUS, LIGHT_FRAME, DARK_FRAME
from core.tools import get_activity_type, get_allowed_activity_list


class ActivitySelectInline(ctk.CTkFrame):
    def __init__(self, parent, username: str, user_manager, on_close: Callable, **kw):
        super().__init__(parent, corner_radius=RADIUS, fg_color=(LIGHT_FRAME, DARK_FRAME), **kw)
        self.user_manager = user_manager
        self._username = username
        self._on_close = on_close
        self._activities: List[Dict] = []
        self._checked: Dict[str, bool] = {}
        self._filter_widgets: Dict[str, list] = {}

        self._build()
        user = user_manager.get_user(username)
        if user and user.get("token"):
            self._init_filters(user)
        else:
            self._show_msg("Token 已过期，请重新添加用户")

    def _build(self):
        # 标题栏
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        ctk.CTkLabel(bar, text=f"选择活动 — {self._username}", font=(ctk.CTkFont, FONT_LG, "bold")).pack(side="left")
        ctk.CTkLabel(bar, text="同级 OR，跨级 AND", font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(side="left", padx=PAD_MD)

        self._save_btn = ctk.CTkButton(bar, text="保存选择", height=32, fg_color="#2e8b57", hover_color="#1e6b3a", font=(ctk.CTkFont, FONT_SM), command=self._on_save)
        self._save_btn.pack(side="right", padx=(0, PAD_SM))

        ctk.CTkButton(bar, text="关闭", fg_color="gray", width=60, height=30, font=(ctk.CTkFont, FONT_SM), command=self._on_close).pack(side="right")

        # 主体
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=PAD_LG, pady=(0, PAD_LG))

        self._filter_scroll = ctk.CTkScrollableFrame(main, corner_radius=RADIUS)
        self._filter_scroll.pack(side="left", fill="both", expand=True, padx=(0, PAD_MD))

        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        self._count_label = ctk.CTkLabel(right, text="", font=(ctk.CTkFont, FONT_SM), text_color="gray")
        self._count_label.pack(anchor="w", pady=(0, PAD_SM))

        self._list_scroll = ctk.CTkScrollableFrame(right, corner_radius=RADIUS)
        self._list_scroll.pack(fill="both", expand=True)

    def _init_filters(self, user: Dict):
        self._clear_filter()

        info = ctk.CTkFrame(self._filter_scroll, fg_color="transparent")
        info.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))
        ctk.CTkLabel(info, text=f"院系：{user.get('college', '未知')}", font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(anchor="w")

        sep = ctk.CTkFrame(self._filter_scroll, height=2, fg_color=("gray80", "gray30"))
        sep.pack(fill="x", padx=PAD_MD, pady=PAD_MD)

        ctk.CTkLabel(self._filter_scroll, text="筛选条件", font=(ctk.CTkFont, FONT_MD, "bold")).pack(anchor="w", padx=PAD_MD, pady=(0, PAD_MD))
        ctk.CTkButton(self._filter_scroll, text="获取活动", height=32, font=(ctk.CTkFont, FONT_SM), command=lambda: self._fetch(user)).pack(fill="x", padx=PAD_MD, pady=(0, PAD_MD))

        types = get_activity_type(user.get("token"), str(user.get("sid")))
        if types:
            self._build_filters(types, user)
        else:
            ctk.CTkLabel(self._filter_scroll, text="无法加载筛选条件", font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(padx=PAD_MD)

    def _build_filters(self, types: List[Dict], user: Dict):
        self._filter_widgets.clear()
        for at in types:
            key = at.get("key", "")
            section = ctk.CTkFrame(self._filter_scroll, corner_radius=6, fg_color=("gray95", "gray17"))
            section.pack(fill="x", padx=PAD_MD, pady=PAD_XS)
            ctk.CTkLabel(section, text=at.get("name", ""), font=(ctk.CTkFont, FONT_SM, "bold")).pack(anchor="w", padx=PAD_SM, pady=(PAD_SM, 1))

            self._filter_widgets[key] = []
            for info in at.get("infoList", []):
                iid = str(info.get("id"))
                var = ctk.BooleanVar(value=(key == "allowYears") or (iid in user.get(key, [])))
                ctk.CTkCheckBox(section, text=info.get("name", iid), font=(ctk.CTkFont, FONT_SM), variable=var).pack(anchor="w", padx=PAD_SM, pady=1)
                self._filter_widgets[key].append((iid, var))

    def _fetch(self, user: Dict):
        self._count_label.configure(text="加载中...", text_color="gray")
        self._clear_list()

        for key, widgets in self._filter_widgets.items():
            selected = [iid for iid, var in widgets if var.get()]
            if selected:
                user[key] = selected
            else:
                user.pop(key, None)

        def _run():
            acts = get_allowed_activity_list(user)
            self.after(0, lambda: self._display(acts))

        threading.Thread(target=_run, daemon=True).start()

    def _display(self, activities: List[Dict]):
        self._activities = activities
        self._checked.clear()
        existing = set(self.user_manager.get_user(self._username).get("activity_ids", []))

        for a in activities:
            aid = str(a.get("activity_id"))
            self._checked[aid] = aid in existing

            row = ctk.CTkFrame(self._list_scroll, corner_radius=6)
            row.pack(fill="x", padx=PAD_SM, pady=2)

            var = ctk.BooleanVar(value=self._checked[aid])
            ctk.CTkCheckBox(row, text="", width=20, variable=var, command=lambda a=aid, v=var: self._toggle(a, v.get())).pack(side="left", padx=PAD_SM)

            txt = f"{a.get('活动名称','')}  |  {a.get('分数',0)}分  |  {a.get('活动分类','')}  |  {a.get('举办组织','')}  |  剩余: {a.get('可报名人数','-')}"
            ctk.CTkLabel(row, text=txt, font=(ctk.CTkFont, FONT_SM)).pack(side="left", padx=PAD_SM, pady=PAD_SM)

        self._count_label.configure(text=f"共找到 {len(activities)} 个活动", text_color="gray")

    def _toggle(self, aid: str, checked: bool):
        self._checked[aid] = checked

    def _on_save(self):
        selected = [aid for aid, v in self._checked.items() if v]
        self.user_manager.update_user(self._username, {"activity_ids": selected})
        self.user_manager.write_user_data()
        self._save_btn.configure(text="已保存 ✓", fg_color="#27ae60")
        self.after(800, self._on_close)

    def _clear_filter(self):
        for w in self._filter_scroll.winfo_children():
            w.destroy()

    def _clear_list(self):
        for w in self._list_scroll.winfo_children():
            w.destroy()

    def _show_msg(self, msg: str):
        self._clear_filter()
        self._clear_list()
        self._count_label.configure(text=msg, text_color="#e74c3c")
