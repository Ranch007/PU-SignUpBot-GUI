"""主窗口：单页布局，分区显示"""
import os
import queue
import customtkinter as ctk
from tkinter import messagebox
from loguru import logger

from core.signup_tasks import SignupTasks
from ui.styles import LIGHT_BG, DARK_BG
from ui.pages.dashboard_page import DashboardPage


class App(ctk.CTk):
    def __init__(self, user_manager, task_store=None):
        super().__init__()
        self.user_manager = user_manager
        self.log_queue = queue.Queue()
        self.task_manager = SignupTasks(store=task_store)
        self.task_manager.import_legacy_monitors(
            user_manager.get_pending_monitors(), user_manager.user_datas)

        self.title("PU-SignUpBot  ‧  PU口袋校园报名助手")
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
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self.task_manager.has_active() and not messagebox.askyesno(
            "报名任务仍在运行", "关闭程序会停止正在等待或报名的任务。确定退出吗？", parent=self
        ):
            return
        self.task_manager.cancel_all()
        self.destroy()

    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.dashboard = DashboardPage(
            self,
            self.user_manager,
            log_queue=self.log_queue,
            task_manager=self.task_manager,
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
