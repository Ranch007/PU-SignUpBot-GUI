"""Dashboard 单页：用户卡片 + 内联表单区 + 日志"""
import os
import threading
from queue import Empty, Queue
import webbrowser
import tkinter as tk
from datetime import datetime, timedelta
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
from core.accounts import account_key, account_from_task, credential_snapshot, credentials_match
from core.config import MAX_ACCOUNTS

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
        self._credit_generation = 0
        self._task_clock = {}
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
            for snapshot, aid, result in results:
                if isinstance(result, Exception):
                    continue
                user = self.user_manager.get_user(snapshot[1])
                if credentials_match(user, snapshot) and aid in {str(item) for item in user.get("activity_ids", [])}:
                    user.setdefault("activity_details", {})[aid] = result
                    changed = True
            if changed:
                try:
                    self.user_manager.write_user_data()
                except OSError as exc:
                    self._show_notification(f"保存活动详情失败：{exc}")
                self._render_plan()
        while True:
            try:
                generation, snapshot, status, value = self._credit_results.get_nowait()
            except Empty:
                break
            user = self.user_manager.get_user(snapshot[1])
            if generation != self._credit_generation or not credentials_match(user, snapshot):
                continue
            key = account_key(user)
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
                self._apply_task_time(event)
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

    def _apply_task_time(self, event):
        user = self.user_manager.get_user(account_from_task(event.task_id))
        if user is None or event.activity_id not in {str(aid) for aid in user.get("activity_ids", [])}:
            return
        self._task_clock[event.task_id] = event.server_offset
        if event.join_start_time:
            info = user.setdefault("activity_details", {}).setdefault(event.activity_id, {})
            info["开始报名时间"] = event.join_start_time
            if event.join_end_time:
                info["报名截止时间"] = event.join_end_time

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
        self.add_btn.pack(side="left", padx=(0, PAD_MD))

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
        self._plan_index = 0
        self._render_plan()
        self.after(1000, self._tick_plan)

    def _render_plan(self):
        users = self.user_manager.user_datas
        total = sum(len(user.get("activity_ids", [])) for user in users)
        tasks = self.task_manager.snapshot() if self.task_manager else []
        upcoming = upcoming_signups(users, tasks=tasks)
        if upcoming:
            if self._plan_index >= len(upcoming):
                self._plan_index = 0
            start, username, aid, info = upcoming[self._plan_index]
            self._plan_label.configure(text=self._plan_text(
                username, info.get("活动名称") or f"活动 {aid}", info))
            sid = next((user.get("sid") for user in users if user.get("userName") == username and
                        (user.get("activity_details") or {}).get(aid) is info), "")
            offset = self._task_clock.get(f"{sid}:{username}:{aid}", 0.0)
            self._countdown_label.configure(text=countdown(start, datetime.now() + timedelta(seconds=offset)))
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
                    missing.append((credential_snapshot(user), dict(user), aid))

        def run():
            results = []
            for snapshot, user, aid in missing:
                try:
                    result = get_single_activity(aid, get_info(aid, user.get("token"), user.get("sid"), strict=True))
                except Exception as exc:
                    result = exc
                results.append((snapshot, aid, result))
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

        self.status_label.configure(text=f"用户: {len(users)}/{MAX_ACCOUNTS}  |  活动: {total}")
        self.signup_btn.configure(state="normal" if total else "disabled")
        self._render_plan()
        self._hydrate_plan()

        if users:
            self._fetch_credits(users)

    def _fetch_credits(self, users):
        from core.tools import get_user_credit
        from core.pu_api import PuApiError
        self._credit_generation += 1
        generation = self._credit_generation
        snapshots = [(credential_snapshot(user), dict(user)) for user in users]

        def run():
            for snapshot, user in snapshots:
                if not user.get("token") or not user.get("sid"):
                    continue
                try:
                    info = get_user_credit(user["token"], user["sid"], strict=True)
                    try:
                        credit = float(info["credit"]) if info.get("credit") is not None else None
                    except (TypeError, ValueError):
                        credit = None
                    self._credit_results.put((generation, snapshot, "valid", credit))
                except PuApiError as exc:
                    if exc.kind == "auth":
                        self._credit_results.put((generation, snapshot, "expired", None))
                    self._credit_results.put((generation, snapshot, "error", str(exc)))
                except Exception as exc:
                    self._credit_results.put((generation, snapshot, "error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def _update_card_credit(self, key: tuple, credit: float):
        for card in self.cards:
            if account_key(card.user) == key:
                card.set_credit(credit)
                break

    def _update_card_token(self, key: tuple, valid: bool):
        for card in self.cards:
            if account_key(card.user) == key:
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
        if len(self.user_manager.user_datas) >= MAX_ACCOUNTS:
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
            on_relogin=self._on_relogin,
            on_details=self._on_select_activity,
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
            self.task_manager.cancel_account(user.get("sid"), user.get("userName"))
        self.user_manager.remove_user(username)
        self.user_manager.write_user_data()
        self.refresh()

    def _on_clear_activities(self, username: str):
        user = self.user_manager.get_user(username)
        if user and self.task_manager:
            self.task_manager.cancel_account(user.get("sid"), user.get("userName"))
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
