"""主窗口：单页布局，分区显示"""
import os
import queue
import customtkinter as ctk
from loguru import logger

from ui.styles import LIGHT_BG, DARK_BG
from ui.pages.dashboard_page import DashboardPage


class App(ctk.CTk):
    def __init__(self, user_manager):
        super().__init__()
        self.user_manager = user_manager
        self.log_queue = queue.Queue()

        self.title("PU-SignUpBot   PU口袋校园报名助手")
        self.minsize(960, 640)
        self.geometry("1100x740")
        self.configure(fg_color=(LIGHT_BG, DARK_BG))

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PU.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self._build()
        self._setup_log_pipeline()

    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.dashboard = DashboardPage(
            self,
            self.user_manager,
            log_queue=self.log_queue,
        )
        self.dashboard.grid(row=0, column=0, sticky="nsew")

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
