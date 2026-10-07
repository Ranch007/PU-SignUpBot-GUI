"""Dashboard 单页：用户卡片 + 内联表单区 + 日志"""
import os
import threading
from queue import Empty, Queue
import webbrowser
import tkinter as tk
from datetime import datetime
import darkdetect
import customtkinter as ctk
from PIL import Image, ImageDraw

from ui.styles import (
    FONT_XL, FONT_LG, FONT_MD, FONT_SM,
    PAD_LG, PAD_MD, PAD_SM, RADIUS,
    LIGHT_BORDER, DARK_BORDER,
)
from ui.widgets.user_card import UserCard
from ui.widgets.log_widget import LogWidget
from ui.pages.signup_inline import SignupInline
from core.activity_plan import upcoming_signups, countdown, parse_activity_time
from core.signup_tasks import TaskPersistenceError

_IMG_DIR = os.path.dirname(os.path.abspath(__file__))
_SUN_PATH = os.path.join(_IMG_DIR, "sun.png")
_MOON_PATH = os.path.join(_IMG_DIR, "moon.png")
_CONTRIB_DIR = os.path.join(_IMG_DIR, "contributors")

def _make_circle(path: str, size: int) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    img.putalpha(mask)
    return img

_CONTRIBUTORS = [
    ("_RedForest.png",   "RedForestLonvor", "https://github.com/RedForestLonvor"),
    ("yifeng.jpg",       "yiqjffeng",       "https://github.com/yiqjffeng"),
    ("DGYJ.jpg",         "DGYJ-fufu",       "https://github.com/DGYJ-fufu"),
    ("ZhangLei_.jpg",    "later-we",        "https://github.com/later-we"),
    ("Mhenwa.jpg",       "Mhenwa",          "https://github.com/Mhenwa"),
    ("Ranch007.jpg",     "Ranch007",        "https://github.com/Ranch007"),
]


class DashboardPage(ctk.CTkFrame):
    def __init__(self, parent, user_manager, log_queue=None, task_manager=None, **kwargs):
        super().__init__(parent, corner_radius=0, fg_color="transparent", **kwargs)
        self.user_manager = user_manager
        self.log_queue = log_queue
        self.task_manager = task_manager
        self._credit_results = Queue()
        self._plan_results = Queue()
        self._plan_generation = 0
        self._plan_index = 0   # 8s 轮换的当前页
        self._plan_ticks = 0
        self.cards = []
        self._inline = None  # 当前内联表单
        self._dark_mode = darkdetect.isDark()
        self._tooltip = None

        self._sun_img = ctk.CTkImage(Image.open(_SUN_PATH), size=(24, 24))
        self._moon_img = ctk.CTkImage(Image.open(_MOON_PATH), size=(24, 24))

        self._build_header()
        self._build_plan()
        self._build_main()
        self._build_log()
        self._build_statusbar()
        self.refresh()
        self.after(100, self._poll_task_events)
        self.after(1000, self._tick_plan)

    def _poll_task_events(self):
        while True:
            try:
                generation, results = self._plan_results.get_nowait()
            except Empty:
                break
            if generation != self._plan_generation:
                continue
            changed = False
            for key, aid, result in results:
                if isinstance(result, Exception):
                    continue
                for user in self.user_manager.user_datas:
                    if (str(user.get("sid")), user.get("userName")) == key and aid in {
                            str(item) for item in user.get("activity_ids", [])}:
                        user.setdefault("activity_details", {})[aid] = result
                        changed = True
                        break
            if changed:
                self.user_manager.write_user_data()
                self._render_plan()
        while True:
            try:
                key, status, value = self._credit_results.get_nowait()
            except Empty:
                break
            if status == "valid":
                self._update_card_token(key, True)
                if value is not None:
                    self._update_card_credit(key, value)
            elif status == "expired":
                self._update_card_token(key, False)
            elif status == "error":
                self.log_queue.put(("WARNING", f"获取学分失败：{value}"))
        if self.task_manager:
            while True:
                try:
                    message = self.task_manager.persistence_errors.get_nowait()
                except Empty:
                    break
                self.log_queue.put(("ERROR", message))
                self._show_notification(message)
            finished = []
            while True:
                try:
                    event = self.task_manager.events.get_nowait()
                except Empty:
                    break
                if isinstance(self._inline, SignupInline):
                    self._inline.on_task_event(event)
                if event.state in ("success", "failed", "cancelled"):
                    self.log_queue.put(("SUCCESS" if event.state == "success" else "WARNING",
                                        f"{event.username} · 活动 {event.activity_id}：{event.message}"))
                    finished.append(event)
            if isinstance(self._inline, SignupInline):
                self._inline._update_controls()
            if finished:
                latest = finished[-1]
                prefix = f"{len(finished)} 项任务有新结果。" if len(finished) > 1 else ""
                self._show_notification(
                    f"{prefix}{latest.username} | 活动 {latest.activity_id}：{latest.message}",
                    kind="success" if all(item.state == "success" for item in finished) else "warning")
        self.after(100, self._poll_task_events)

    # ======================== 头部 ========================

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        avatars = ctk.CTkFrame(header, fg_color="transparent")
        avatars.pack(side="left")

        ctk.CTkLabel(avatars, text="贡\n献\n者", font=("KaiTi", 14, "bold"), text_color="gray", width=18).pack(side="left", padx=(0, 6))

        for filename, username, url in _CONTRIBUTORS:
            path = os.path.join(_CONTRIB_DIR, filename)
            circle = _make_circle(path, 40)
            img = ctk.CTkImage(circle, size=(40, 40))

            lbl = ctk.CTkLabel(avatars, text="", image=img, width=40, height=40,
                               fg_color="transparent", cursor="hand2")
            lbl.pack(side="left", padx=1)
            lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            lbl.bind("<Enter>", lambda e, n=username: self._show_tooltip(e, n))
            lbl.bind("<Leave>", lambda e: self._hide_tooltip())

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")

        self.add_btn = ctk.CTkButton(btn_frame, text="＋ 添加用户", height=36, font=(ctk.CTkFont, FONT_MD), command=self._show_add_user)
        self.add_btn.pack(side="left", padx=(0, PAD_SM))

        self.signup_btn = ctk.CTkButton(btn_frame, text="▶ 开始等待报名", fg_color="#2e8b57", hover_color="#1e6b3a", height=36, font=(ctk.CTkFont, FONT_MD), command=self._start_signup)
        self.signup_btn.pack(side="left", padx=(0, PAD_SM))

        self.theme_btn = ctk.CTkButton(btn_frame, text="", image=self._sun_img if self._dark_mode else self._moon_img, width=40, height=36, fg_color="transparent", hover_color=("gray80", "gray30"), command=self._toggle_theme)
        self.theme_btn.pack(side="left")

        sep = ctk.CTkFrame(self, height=1, fg_color=(LIGHT_BORDER, DARK_BORDER))
        sep.pack(fill="x", padx=PAD_LG)

    def _build_plan(self):
        plan = ctk.CTkFrame(self, corner_radius=RADIUS,
                            fg_color=("#f4f2ed", "gray17"),
                            border_width=1, border_color=(LIGHT_BORDER, DARK_BORDER))
        plan.pack(fill="x", padx=PAD_LG, pady=(PAD_MD, 0))
        ctk.CTkLabel(plan, text="下一场报名", font=(ctk.CTkFont, FONT_MD, "bold"),
                     width=90).pack(side="left", padx=PAD_MD, pady=PAD_SM)
        self._page_label = ctk.CTkLabel(plan, text="", font=(ctk.CTkFont, FONT_SM),
                                        text_color=("#55514d", "#c1c1c1"))
        self._page_label.pack(side="left", padx=(0, PAD_SM))
        self._plan_label = ctk.CTkLabel(plan, text="", font=(ctk.CTkFont, FONT_SM),
                                        anchor="w", justify="left")
        self._plan_label.pack(side="left", fill="x", expand=True, padx=PAD_SM)
        self._countdown_label = ctk.CTkLabel(plan, text="", font=(ctk.CTkFont, FONT_MD, "bold"),
                                             text_color="#2e8b57")
        self._countdown_label.pack(side="right", padx=PAD_MD)

    def _tick_plan(self):
        self._plan_ticks += 1
        if self._plan_ticks >= 8:
            self._plan_ticks = 0
            self._plan_index += 1
        self._render_plan()
        self.after(1000, self._tick_plan)

    def _render_plan(self):
        users = self.user_manager.user_datas
        total = sum(len(user.get("activity_ids", [])) for user in users)
        upcoming = upcoming_signups(users)
        if upcoming:
            if self._plan_index >= len(upcoming):
                self._plan_index = 0
            start, username, aid, info = upcoming[self._plan_index]
            self._plan_label.configure(text=self._plan_text(
                username, info.get("活动名称") or f"活动 {aid}", info))
            self._countdown_label.configure(text=countdown(start))
            self._page_label.configure(text=f"({self._plan_index + 1}/{len(upcoming)})")
        else:
            self._plan_index = 0
            self._plan_label.configure(text=f"已选 {total} 项活动，暂无可确认的下一场报名时间" if total
                                       else "先添加账号并选择活动")
            self._countdown_label.configure(text="")
            self._page_label.configure(text="")

    def _plan_text(self, username, name, info):
        start = parse_activity_time(info.get("开始报名时间"))
        deadline = parse_activity_time(info.get("报名截止时间"))
        end = parse_activity_time(info.get("活动结束时间"))
        enroll = f"报名时间： {start:%m-%d %H:%M}"
        if deadline:
            enroll += f"，截至时间： {deadline:%m-%d %H:%M}"
        line = f"{username} | {name}  |  {enroll}"
        return line

    def _hydrate_plan(self):
        from core.tools import get_info, get_single_activity

        self._plan_generation += 1
        generation = self._plan_generation
        missing = []
        for user in self.user_manager.user_datas:
            details = user.get("activity_details") or {}
            for aid in user.get("activity_ids", []):
                aid = str(aid)
                if (aid not in details
                        or "报名截止时间" not in (details.get(aid) or {})) and user.get("token"):
                    missing.append((str(user.get("sid")), user.get("userName"),
                                    user.get("token"), aid))

        def run():
            results = []
            for sid, username, token, aid in missing:
                try:
                    result = get_single_activity(aid, get_info(aid, token, sid, strict=True))
                except Exception as exc:
                    result = exc
                results.append(((sid, username), aid, result))
            self._plan_results.put((generation, results))

        if missing:
            threading.Thread(target=run, daemon=True).start()

    # ======================== 主体 ========================

    def _build_main(self):
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.pack(fill="both", expand=True, padx=PAD_LG, pady=(PAD_MD, PAD_SM))

        # 用户卡片区
        self.cards_frame = ctk.CTkScrollableFrame(
            self.main_area,
            fg_color="transparent",
            corner_radius=RADIUS,
            border_width=1,
            border_color=(LIGHT_BORDER, DARK_BORDER),
        )
        self.cards_frame.pack(fill="both", expand=True)
        self.cards_frame.grid_columnconfigure(0, weight=1)

        # 内联表单区（初始隐藏，动态 pack/unpack）
        self.inline_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")

    # ======================== 日志区 ========================

    def _build_log(self):
        sep = ctk.CTkFrame(self, height=1, fg_color=(LIGHT_BORDER, DARK_BORDER))
        sep.pack(fill="x", padx=PAD_LG, pady=(0, PAD_SM))

        log_section = ctk.CTkFrame(self, fg_color="transparent")
        log_section.pack(fill="x", padx=PAD_LG)

        log_header = ctk.CTkFrame(log_section, fg_color="transparent")
        log_header.pack(fill="x")
        ctk.CTkLabel(log_header, text="运行日志", font=(ctk.CTkFont, FONT_MD, "bold")).pack(side="left")
        self._log_toggle = ctk.CTkButton(
            log_header, text="展开详情", width=90, height=28,
            fg_color="transparent", text_color=("#245b82", "#89c8f0"),
            hover_color=("#dedbd4", "#343434"),
            font=(ctk.CTkFont, FONT_SM), command=self._toggle_log)
        self._log_toggle.pack(side="right")

        self.log_widget = LogWidget(log_section, log_queue=self.log_queue, height=140)
        # 详细日志默认收起，给活动列表和报名任务留出可读空间。

    def _toggle_log(self):
        if self.log_widget.winfo_manager():
            self.log_widget.pack_forget()
            self._log_toggle.configure(text="展开详情")
        else:
            self.log_widget.pack(fill="x", pady=(PAD_SM, 0))
            self._log_toggle.configure(text="收起详情")

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
            self.after(200, self._show_add_user)

        for i, user in enumerate(users):
            card = UserCard(
                self.cards_frame, user,
                on_delete=self._on_delete,
                on_select_activity=self._on_select_activity,
                on_clear_activities=self._on_clear_activities,
                on_relogin=self._on_relogin,
            )
            card.grid(row=i, column=0, padx=PAD_MD, pady=PAD_MD, sticky="ew")
            self.cards.append(card)
            card.load_activities()

        self.status_label.configure(text=f"用户: {len(users)}/4  |  活动: {total}")
        self.signup_btn.configure(state="normal" if total else "disabled")
        self._render_plan()
        self._hydrate_plan()

        if users:
            self._fetch_credits(users)

    def _fetch_credits(self, users):
        from core.tools import get_user_credit
        from core.pu_api import PuApiError

        def _run():
            for user in users:
                token = user.get("token")
                sid = user.get("sid")
                if not token or not sid:
                    continue
                key = (user.get("userName"), sid)
                try:
                    info = get_user_credit(token, sid, strict=True)
                except PuApiError as exc:
                    if exc.kind == "auth":
                        self._credit_results.put((key, "expired", None))
                    self._credit_results.put((key, "error", str(exc)))
                    continue
                except Exception as exc:
                    self._credit_results.put((key, "error", str(exc)))
                    continue
                credit = info.get("credit")
                try:
                    credit = float(credit) if credit is not None else None
                except (TypeError, ValueError):
                    credit = None
                self._credit_results.put((key, "valid", credit))

        threading.Thread(target=_run, daemon=True).start()

    def _update_card_credit(self, key: tuple, credit: float):
        for card in self.cards:
            if (card.user.get("userName"), card.user.get("sid")) == key:
                card.set_credit(credit)
                break

    def _update_card_token(self, key: tuple, valid: bool):
        for card in self.cards:
            if (card.user.get("userName"), card.user.get("sid")) == key:
                card.set_token_status(valid)
                break

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
            if hasattr(self._inline, "cancel_pending"):
                self._inline.cancel_pending()
            self._inline.pack_forget()
            self._inline = None
        self.inline_frame.pack_forget()
        self.cards_frame.pack(fill="both", expand=True, pady=(0, PAD_MD))

    def _show_add_user(self):
        if len(self.user_manager.user_datas) >= 4:
            self._show_notification("用户添加数量已达上限，请删除后再添加！")
            return
        self._hide_inline()
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

    def _show_notification(self, message: str, kind: str = "warning"):
        """在页面顶部显示短暂通知"""
        color = "#2e8b57" if kind == "success" else "#c0392b"
        banner = ctk.CTkFrame(self, fg_color=color, corner_radius=0, height=40)
        banner.pack(fill="x", side="top", before=self.main_area)
        ctk.CTkLabel(
            banner, text=message, font=(ctk.CTkFont, FONT_MD), text_color="white"
        ).pack(expand=True)
        self.after(2500, banner.destroy)

    def _show_signup(self):
        self._hide_inline()
        for child in self.inline_frame.winfo_children():
            child.destroy()
        w = SignupInline(
            self.inline_frame,
            self.user_manager,
            self.log_queue,
            self.task_manager,
            on_close=self._hide_inline,
            on_change=self.refresh,
        )
        self._show_inline(w)

    def _start_signup(self):
        if self.task_manager:
            try:
                self.task_manager.start(self.user_manager.user_datas)
            except TaskPersistenceError:
                return
        self._show_signup()

    # ======================== 工具提示 ========================

    def _show_tooltip(self, event, name: str):
        if self._tooltip:
            self._tooltip.destroy()
        self._tooltip = tk.Toplevel(self.winfo_toplevel())
        self._tooltip.wm_overrideredirect(True)
        x = event.widget.winfo_rootx() + event.widget.winfo_width() // 2
        y = event.widget.winfo_rooty() + event.widget.winfo_height() + 4
        self._tooltip.wm_geometry(f"+{x - 30}+{y}")
        frame = tk.Frame(self._tooltip, bg="#333333", padx=6, pady=2)
        frame.pack()
        tk.Label(frame, text=name, fg="#ffffff", bg="#333333", font=("Microsoft YaHei", 10)).pack()

    def _hide_tooltip(self):
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None

    # ======================== 回调 ========================

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        new_mode = "dark" if self._dark_mode else "light"
        self.theme_btn.configure(image=self._sun_img if self._dark_mode else self._moon_img)
        def apply_theme():
            ctk.set_appearance_mode(new_mode)
            self.log_widget.update_theme_colors()
        self.after(1, apply_theme)

    def _on_delete(self, username: str):
        user = self.user_manager.get_user(username)
        if user and self.task_manager:
            self.task_manager.cancel_account(user.get("sid"), username)
        self.user_manager.remove_user(username)
        self.user_manager.write_user_data()
        self.refresh()

    def _on_clear_activities(self, username: str):
        user = self.user_manager.get_user(username)
        if user and self.task_manager:
            self.task_manager.cancel_account(user.get("sid"), username)
        self.user_manager.update_user(username, {"activity_ids": [], "activity_details": {}})
        self.user_manager.write_user_data()
        self.refresh()

    def _on_select_activity(self, username: str):
        self._hide_inline()
        for child in self.inline_frame.winfo_children():
            child.destroy()
        from ui.pages.activity_select_inline import ActivitySelectInline
        w = ActivitySelectInline(
            self.inline_frame,
            username,
            self.user_manager,
            on_close=lambda: [self._hide_inline(), self.refresh()],
            task_manager=self.task_manager,
        )
        self._show_inline(w)

    def _on_relogin(self, username: str):
        self._hide_inline()
        for child in self.inline_frame.winfo_children():
            child.destroy()
        from ui.pages.relogin_inline import ReloginInline
        w = ReloginInline(
            self.inline_frame, username, self.user_manager, self.task_manager,
            on_done=lambda: [self._hide_inline(), self.refresh()],
            on_cancel=self._hide_inline,
        )
        self._show_inline(w)
