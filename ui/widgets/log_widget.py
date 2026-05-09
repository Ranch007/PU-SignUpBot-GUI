"""实时彩色日志控件"""
import queue
import customtkinter as ctk
from ui.styles import FONT_SM, LOG_COLORS


class LogWidget(ctk.CTkTextbox):
    def __init__(self, parent, log_queue: queue.Queue, **kwargs):
        super().__init__(
            parent,
            font=(ctk.CTkFont, FONT_SM),
            wrap="word",
            state="disabled",
            **kwargs,
        )
        self._log_queue = log_queue
        self._log_colors = LOG_COLORS
        self._pull_logs()

    def _pull_logs(self):
        try:
            while not self._log_queue.empty():
                level, message = self._log_queue.get_nowait()
                self._append_log(level, message)
        except Exception:
            pass
        self.after(250, self._pull_logs)

    def _append_log(self, level: str, message: str):
        self.configure(state="normal")
        color = self._log_colors.get(level, "#ffffff")

        tag = f"log_{level.lower()}"
        self._ensure_tag(tag, color)

        self.insert("end", f"{message}\n", tag)
        self.see("end")
        self.configure(state="disabled")

    def _ensure_tag(self, tag: str, color: str):
        try:
            self.tag_config(tag, foreground=color)
        except Exception:
            pass
