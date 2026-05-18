"""Dashboard 单页：用户卡片 + 内联表单区 + 日志"""
import os
import threading
import webbrowser
import tkinter as tk
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
    def __init__(self, parent, user_manager, log_queue=None, **kwargs):
        super().__init__(parent, corner_radius=0, fg_color="transparent", **kwargs)
        self.user_manager = user_manager
        self.log_queue = log_queue
        self.cards = []
        self._inline = None  # 当前内联表单
        self._dark_mode = darkdetect.isDark()
        self._tooltip = None

        self._sun_img = ctk.CTkImage(Image.open(_SUN_PATH), size=(24, 24))
        self._moon_img = ctk.CTkImage(Image.open(_MOON_PATH), size=(24, 24))

        self._build_header()
        self._build_main()
        self._build_log()
        self._build_statusbar()
        self.refresh()

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

        self.signup_btn = ctk.CTkButton(btn_frame, text="▶ 全部报名", fg_color="#2e8b57", hover_color="#1e6b3a", height=36, font=(ctk.CTkFont, FONT_MD), command=self._show_signup)
        self.signup_btn.pack(side="left", padx=(0, PAD_SM))

        self.theme_btn = ctk.CTkButton(btn_frame, text="", image=self._sun_img if self._dark_mode else self._moon_img, width=40, height=36, fg_color="transparent", hover_color=("gray80", "gray30"), command=self._toggle_theme)
        self.theme_btn.pack(side="left")

        sep = ctk.CTkFrame(self, height=1, fg_color=(LIGHT_BORDER, DARK_BORDER))
        sep.pack(fill="x", padx=PAD_LG)

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
        for i in range(2):
            self.cards_frame.grid_columnconfigure(i, weight=1)

        # 内联表单区（初始隐藏，动态 pack/unpack）
        self.inline_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")

    # ======================== 日志区 ========================

    def _build_log(self):
        sep = ctk.CTkFrame(self, height=1, fg_color=(LIGHT_BORDER, DARK_BORDER))
        sep.pack(fill="x", padx=PAD_LG, pady=(0, PAD_SM))

        log_section = ctk.CTkFrame(self, fg_color="transparent")
        log_section.pack(fill="x", padx=PAD_LG)

        ctk.CTkLabel(log_section, text="实时日志", font=(ctk.CTkFont, FONT_LG, "bold")).pack(anchor="w")

        self.log_widget = LogWidget(log_section, log_queue=self.log_queue, height=140)
        self.log_widget.pack(fill="x", pady=(PAD_SM, 0))

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
            )
            row, col = divmod(i, 2)
            card.grid(row=row, column=col, padx=PAD_MD, pady=PAD_MD, sticky="nsew")
            self.cards.append(card)
            card.load_activities()

        # 行和列都设置权重，均匀分配空间
        num_rows = max(1, (len(users) + 1) // 2)
        for r in range(num_rows):
            self.cards_frame.grid_rowconfigure(r, weight=1)

        self.status_label.configure(text=f"用户: {len(users)}/2  |  活动: {total}")
        self.signup_btn.configure(state="normal" if users else "disabled")

        if users:
            self._fetch_credits(users)

    def _fetch_credits(self, users):
        from core.tools import get_user_credit

        def _run():
            for i, user in enumerate(users):
                token = user.get("token")
                sid = user.get("sid")
                if not token or not sid:
                    continue
                info = get_user_credit(token, sid)
                credit = info.get("credit")
                if credit is not None:
                    self.after(0, lambda idx=i, c=float(credit): self._update_card_credit(idx, c))

        threading.Thread(target=_run, daemon=True).start()

    def _update_card_credit(self, index: int, credit: float):
        if index < len(self.cards):
            self.cards[index].set_credit(credit)

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
            self._inline.pack_forget()
            self._inline = None
        self.inline_frame.pack_forget()
        self.cards_frame.pack(fill="both", expand=True, pady=(0, PAD_MD))

    def _show_add_user(self):
        if len(self.user_manager.user_datas) >= 2:
            self._show_notification("用户添加数量已达上限，请删除后再添加！")
            return
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

    def _show_notification(self, message: str):
        """在页面顶部显示短暂通知"""
        banner = ctk.CTkFrame(self, fg_color="#e74c3c", corner_radius=0, height=40)
        banner.pack(fill="x", side="top", before=self.main_area)
        ctk.CTkLabel(
            banner, text=message, font=(ctk.CTkFont, FONT_MD), text_color="white"
        ).pack(expand=True)
        self.after(2500, banner.destroy)

    def _show_signup(self):
        for child in self.inline_frame.winfo_children():
            child.destroy()
        from ui.pages.signup_inline import SignupInline
        w = SignupInline(
            self.inline_frame,
            self.user_manager,
            self.log_queue,
            on_close=self._hide_inline,
        )
        self._show_inline(w)

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
        self.after(1, lambda: ctk.set_appearance_mode(new_mode))

    def _on_delete(self, username: str):
        self.user_manager.remove_user(username)
        self.user_manager.write_user_data()
        self.refresh()

    def _on_clear_activities(self, username: str):
        self.user_manager.update_user(username, {"activity_ids": []})
        self.user_manager.write_user_data()
        self.refresh()

    def _on_select_activity(self, username: str):
        for child in self.inline_frame.winfo_children():
            child.destroy()
        from ui.pages.activity_select_inline import ActivitySelectInline
        w = ActivitySelectInline(
            self.inline_frame,
            username,
            self.user_manager,
            on_close=lambda: [self._hide_inline(), self.refresh()],
        )
        self._show_inline(w)
