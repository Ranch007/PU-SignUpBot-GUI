"""主窗口、侧边导航、页面路由、日志管道"""
import queue
import customtkinter as ctk
from loguru import logger

from ui.styles import (
    FONT_MD, FONT_SM,
    PAD_LG, PAD_MD,
    PRIMARY, PRIMARY_HOVER,
    LIGHT_NAV, DARK_NAV,
    LIGHT_BG, DARK_BG,
)
from ui.pages.dashboard_page import DashboardPage
from ui.pages.add_user_page import AddUserPage
from ui.pages.signup_page import SignupPage


class App(ctk.CTk):
    def __init__(self, user_manager):
        super().__init__()
        self.user_manager = user_manager
        self.log_queue = queue.Queue()

        self.title("PU-SignUpBot - PU 口袋校园报名助手")
        self.minsize(960, 640)
        self.geometry("1100x720")

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self._build()
        self._setup_log_pipeline()
        self._navigate("dashboard")

    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # 侧边导航
        self.nav_frame = ctk.CTkFrame(
            self,
            width=180,
            corner_radius=0,
            fg_color=(LIGHT_NAV, DARK_NAV),
        )
        self.nav_frame.grid(row=0, column=0, sticky="nsew")
        self.nav_frame.grid_propagate(False)

        ctk.CTkLabel(
            self.nav_frame,
            text="PU-SignUpBot",
            font=(ctk.CTkFont, FONT_MD, "bold"),
            text_color="#ffffff",
        ).pack(pady=(PAD_LG, PAD_LG))

        self.nav_buttons = {}
        nav_items = [
            ("dashboard", "首页"),
            ("add_user", "添加用户"),
            ("signup", "开始报名"),
        ]
        for key, label in nav_items:
            btn = ctk.CTkButton(
                self.nav_frame,
                text=label,
                fg_color="transparent",
                hover_color=(PRIMARY, PRIMARY_HOVER),
                anchor="w",
                height=40,
                corner_radius=6,
                font=(ctk.CTkFont, FONT_MD),
                command=lambda k=key: self._navigate(k),
            )
            btn.pack(fill="x", padx=PAD_MD, pady=2)
            self.nav_buttons[key] = btn

        # 内容区域
        self.content_frame = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=(LIGHT_BG, DARK_BG),
        )
        self.content_frame.grid(row=0, column=1, sticky="nsew")
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        self.pages = {}
        self.current_page = None

    def _navigate(self, key: str):
        # 高亮
        for k, btn in self.nav_buttons.items():
            btn.configure(fg_color=PRIMARY if k == key else "transparent")

        # 切换页面
        if self.current_page:
            self.current_page.pack_forget()

        if key not in self.pages:
            if key == "dashboard":
                page = DashboardPage(self.content_frame, self.user_manager)
                page.add_btn.configure(command=lambda: self._navigate("add_user"))
                page.signup_btn.configure(command=lambda: self._navigate("signup"))
            elif key == "add_user":
                page = AddUserPage(
                    self.content_frame,
                    self.user_manager,
                    on_done=lambda: self._navigate("dashboard"),
                )
            elif key == "signup":
                page = SignupPage(
                    self.content_frame,
                    self.user_manager,
                    self.log_queue,
                )
            else:
                return

            page.pack(fill="both", expand=True)
            self.pages[key] = page
        else:
            page = self.pages[key]
            page.pack(fill="both", expand=True)
            if hasattr(page, "refresh"):
                page.refresh()

        self.current_page = page

    def _setup_log_pipeline(self):
        from loguru import logger as loguru_logger

        def enqueue(msg):
            line = str(msg).rstrip()
            if "|" in line:
                level, _, text = line.partition("|")
                self.log_queue.put((level.strip(), text.strip()))
            else:
                self.log_queue.put(("INFO", line))

        loguru_logger.add(
            enqueue,
            format="{level.name}|{message}",
            level="INFO",
        )
        logger.info("GUI 日志管道已初始化")
