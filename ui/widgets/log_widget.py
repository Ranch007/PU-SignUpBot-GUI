"""实时彩色日志控件"""
import queue
import customtkinter as ctk
from ui.styles import FONT_SM, LOG_COLORS_LIGHT, LOG_COLORS_DARK


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
        self.update_theme_colors()
        self._pull_logs()

    def update_theme_colors(self):
        self._log_colors = (LOG_COLORS_DARK if ctk.get_appearance_mode() == "Dark"
                            else LOG_COLORS_LIGHT)
        for level, color in self._log_colors.items():
            self._ensure_tag(f"log_{level.lower()}", color)

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
        color = self._log_colors.get(level, self._log_colors["INFO"])

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
