"""活动选择内联面板"""
from typing import Dict, List, Callable
import threading
from queue import Empty, Queue
import customtkinter as ctk

from ui.styles import FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, PAD_XS, RADIUS, LIGHT_FRAME, DARK_FRAME
from core.tools import get_activity_type, get_allowed_activity_list
from core.activity_plan import visible_activities, overlapping_activities


class ActivitySelectInline(ctk.CTkFrame):
    def __init__(self, parent, username: str, user_manager, on_close: Callable,
                 task_manager=None, **kw):
        super().__init__(parent, corner_radius=RADIUS, fg_color=(LIGHT_FRAME, DARK_FRAME), **kw)
        self.user_manager = user_manager
        self._username = username
        self._on_close = on_close
        self.task_manager = task_manager
        self._activities: List[Dict] = []
        user = user_manager.get_user(username) or {}
        self._selected = {str(aid) for aid in user.get("activity_ids", [])}
        self._details = dict(user.get("activity_details") or {})
        self._overlap_confirmed = False
        self._filter_widgets: Dict[str, list] = {}
        self._results = Queue()
        self._fetch_generation = 0
        self._active = True

        self._build()
        self.after(100, self._poll_results)
        user = user_manager.get_user(username)
        if user and user.get("token"):
            self._init_filters(user)
        else:
            self._show_msg("当前账号未登录，请先检查账号状态")

    def _build(self):
        # 标题栏
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        ctk.CTkLabel(bar, text=f"选择活动 — {self._username}", font=(ctk.CTkFont, FONT_LG, "bold")).pack(side="left")
        ctk.CTkLabel(bar, text="同级 OR，跨级 AND", font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(side="left", padx=PAD_MD)

        self._save_btn = ctk.CTkButton(bar, text="保存选择", height=32, state="disabled",
                                       fg_color="#2e8b57", hover_color="#1e6b3a",
                                       font=(ctk.CTkFont, FONT_SM), command=self._on_save)
        self._save_btn.pack(side="right", padx=(0, PAD_SM))

        ctk.CTkButton(bar, text="关闭", fg_color="gray", width=60, height=30, font=(ctk.CTkFont, FONT_SM), command=self._on_close).pack(side="right")

        # 主体
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=PAD_LG, pady=(0, PAD_LG))

        self._filter_scroll = ctk.CTkScrollableFrame(main, corner_radius=RADIUS, width=240)
        self._filter_scroll.pack(side="left", fill="y", padx=(0, PAD_MD))

        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        find_bar = ctk.CTkFrame(right, fg_color="transparent")
        find_bar.pack(fill="x", pady=(0, PAD_SM))
        self._search = ctk.CTkEntry(find_bar, placeholder_text="按活动名称搜索", height=30)
        self._search.pack(side="left", fill="x", expand=True, padx=(0, PAD_SM))
        self._search.bind("<KeyRelease>", lambda _event: self._render_list())
        self._sort = ctk.CTkOptionMenu(find_bar, values=["报名时间", "活动时间", "学分"],
                                       width=100, height=30, command=lambda _value: self._render_list())
        self._sort.pack(side="right")

        self._count_label = ctk.CTkLabel(right, text="", font=(ctk.CTkFont, FONT_SM), text_color="gray")
        self._count_label.pack(anchor="w", pady=(0, PAD_SM))

        self._list_scroll = ctk.CTkScrollableFrame(right, corner_radius=RADIUS)
        self._list_scroll.pack(fill="both", expand=True)
        self._warning_label = ctk.CTkLabel(right, text="", font=(ctk.CTkFont, FONT_SM),
                                           text_color="#c26a00", anchor="w")
        self._warning_label.pack(fill="x", pady=(PAD_SM, 0))

    def _init_filters(self, user: Dict):
        self._clear_filter()

        info = ctk.CTkFrame(self._filter_scroll, fg_color="transparent")
        info.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))
        ctk.CTkLabel(info, text=f"院系：{user.get('college', '未知')}", font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(anchor="w")

        sep = ctk.CTkFrame(self._filter_scroll, height=2, fg_color=("gray80", "gray30"))
        sep.pack(fill="x", padx=PAD_MD, pady=PAD_MD)

        ctk.CTkLabel(self._filter_scroll, text="筛选条件", font=(ctk.CTkFont, FONT_MD, "bold")).pack(anchor="w", padx=PAD_MD, pady=(0, PAD_MD))
        self._fetch_btn = ctk.CTkButton(self._filter_scroll, text="获取活动", height=32,
                                        font=(ctk.CTkFont, FONT_SM), command=lambda: self._fetch(user))
        self._fetch_btn.pack(fill="x", padx=PAD_MD, pady=(0, PAD_MD))
        self._count_label.configure(text="正在加载筛选条件...", text_color="gray")

        def run():
            try:
                result = get_activity_type(user.get("token"), str(user.get("sid")), strict=True)
            except Exception as exc:
                result = exc
            self._results.put(("filters", 0, result, user))

        threading.Thread(target=run, daemon=True).start()

    def _poll_results(self):
        if not self._active:
            return
        while True:
            try:
                kind, generation, result, user = self._results.get_nowait()
            except Empty:
                break
            if kind == "filters":
                if isinstance(result, Exception):
                    self._count_label.configure(text=f"筛选条件加载失败：{result}", text_color="#e74c3c")
                elif result:
                    self._build_filters(result, user)
                    self._count_label.configure(text="筛选条件已加载", text_color="gray")
                else:
                    self._count_label.configure(text="暂无筛选条件，可以直接获取活动", text_color="gray")
            elif kind == "activities" and generation == self._fetch_generation:
                self._fetch_btn.configure(state="normal")
                if isinstance(result, Exception):
                    self._count_label.configure(text=f"活动加载失败：{result}", text_color="#e74c3c")
                else:
                    self._save_btn.configure(state="normal")
                    self._display(result)
        self.after(100, self._poll_results)

    def cancel_pending(self):
        self._active = False
        self._fetch_generation += 1

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
        self._activities = []
        self._fetch_btn.configure(state="disabled")

        for key, widgets in self._filter_widgets.items():
            selected = [iid for iid, var in widgets if var.get()]
            if selected:
                user[key] = selected
            else:
                user.pop(key, None)

        self._fetch_generation += 1
        generation = self._fetch_generation

        def _run():
            try:
                result = get_allowed_activity_list(dict(user), strict=True)
            except Exception as exc:
                result = exc
            self._results.put(("activities", generation, result, None))

        threading.Thread(target=_run, daemon=True).start()

    def _display(self, activities: List[Dict]):
        self._activities = activities
        for a in activities:
            aid = str(a.get("activity_id"))
            self._details[aid] = a
        self._render_list()

    def _render_list(self):
        self._clear_list()
        shown = visible_activities(self._activities, self._search.get(), self._sort.get())
        for a in shown:
            aid = str(a.get("activity_id"))

            row = ctk.CTkFrame(self._list_scroll, corner_radius=6)
            row.pack(fill="x", padx=PAD_SM, pady=2)

            var = ctk.BooleanVar(value=aid in self._selected)
            ctk.CTkCheckBox(row, text="", width=20, variable=var, command=lambda a=aid, v=var: self._toggle(a, v.get())).pack(side="left", padx=PAD_SM)

            body = ctk.CTkFrame(row, fg_color="transparent")
            body.pack(side="left", fill="x", expand=True, padx=PAD_SM, pady=PAD_SM)
            title = a.get('活动名称') or '未命名活动'
            ctk.CTkLabel(body, text=title, font=(ctk.CTkFont, FONT_MD, "bold"),
                         anchor="w", justify="left", wraplength=460).pack(fill="x")
            ctk.CTkLabel(body,
                         text=f"{a.get('分数') or 0} 分  ·  剩余 {a.get('可报名人数', '-')} 名",
                         font=(ctk.CTkFont, FONT_SM),
                         text_color=("#245b82", "#89c8f0"), anchor="w").pack(fill="x")
            summary = (f"报名：{a.get('开始报名时间') or '待确认'}\n"
                       f"活动：{a.get('活动开始时间') or '待确认'}")
            ctk.CTkLabel(body, text=summary, font=(ctk.CTkFont, FONT_SM),
                         text_color=("#55514d", "#c1c1c1"),
                         anchor="w", justify="left").pack(fill="x")
            detail = ctk.CTkLabel(body, text=(
                f"地点：{a.get('活动地址') or '待确认'}  |  {a.get('活动分类') or '分类未知'}  |  "
                f"{a.get('举办组织') or '组织未知'}  |  结束：{a.get('活动结束时间') or '待确认'}\n"
                "其他参与条件请在 PU 活动详情中核对"),
                font=(ctk.CTkFont, FONT_SM),
                text_color=("#55514d", "#c1c1c1"), anchor="w", justify="left",
                wraplength=460)
            ctk.CTkButton(row, text="详情", width=52, height=24, font=(ctk.CTkFont, FONT_SM),
                          command=lambda d=detail: d.pack_forget() if d.winfo_manager() else d.pack(fill="x"))\
                .pack(side="right", padx=PAD_SM)

        self._count_label.configure(text=f"显示 {len(shown)}/{len(self._activities)} 个活动  ·  已选 {len(self._selected)} 个",
                                    text_color="gray")

    def _toggle(self, aid: str, checked: bool):
        self._overlap_confirmed = False
        self._warning_label.configure(text="")
        self._save_btn.configure(text="保存选择")
        if checked:
            self._selected.add(aid)
        else:
            self._selected.discard(aid)
        shown = visible_activities(self._activities, self._search.get(), self._sort.get())
        self._count_label.configure(text=f"显示 {len(shown)}/{len(self._activities)} 个活动  ·  已选 {len(self._selected)} 个")

    def _on_save(self):
        overlaps = overlapping_activities(self._details, self._selected)
        if overlaps and not self._overlap_confirmed:
            names = "、".join(f"{first} / {second}" for first, second in overlaps[:2])
            self._warning_label.configure(text=f"活动时间重叠：{names}。如仍需保留，请再次点击保存选择。")
            self._overlap_confirmed = True
            return
        selected = sorted(self._selected)
        details = {aid: self._details[aid] for aid in selected if aid in self._details}
        self.user_manager.update_user(self._username, {"activity_ids": selected,
                                                        "activity_details": details})
        self.user_manager.write_user_data()
        if self.task_manager:
            user = self.user_manager.get_user(self._username)
            self.task_manager.cancel_unselected(user.get("sid"), self._username, self._selected)
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
