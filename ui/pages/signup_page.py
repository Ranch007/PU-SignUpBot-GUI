"""报名监控页：进度条 + 状态表格 + 实时日志"""
import threading
from typing import Dict, List
import customtkinter as ctk

from ui.styles import FONT_XL, FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, RADIUS
from ui.widgets.log_widget import LogWidget
from core.single import single_account


class SignupPage(ctk.CTkFrame):
    def __init__(self, parent, user_manager, log_queue, **kwargs):
        super().__init__(parent, corner_radius=0, fg_color="transparent", **kwargs)
        self.user_manager = user_manager
        self.log_queue = log_queue
        self._abort_flags: Dict[str, bool] = {}
        self._status_rows: List[Dict] = []

        self._build()

    def _build(self):
        # 标题
        title_bar = ctk.CTkFrame(self, fg_color="transparent")
        title_bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        ctk.CTkLabel(
            title_bar,
            text="报名监控",
            font=(ctk.CTkFont, FONT_XL, "bold"),
        ).pack(side="left")

        btn_frame = ctk.CTkFrame(title_bar, fg_color="transparent")
        btn_frame.pack(side="right")

        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="▶ 全部开始",
            fg_color="#2e8b57",
            hover_color="#1e6b3a",
            height=34,
            font=(ctk.CTkFont, FONT_MD),
            command=self._start_all,
        )
        self.start_btn.pack(side="left", padx=(0, PAD_SM))

        self.abort_btn = ctk.CTkButton(
            btn_frame,
            text="⏹ 中止",
            fg_color="#c0392b",
            hover_color="#a93226",
            height=34,
            font=(ctk.CTkFont, FONT_MD),
            state="disabled",
            command=self._abort_all,
        )
        self.abort_btn.pack(side="left")

        # 进度条
        self.progress_frame = ctk.CTkFrame(self, corner_radius=RADIUS)
        self.progress_frame.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame, height=20, corner_radius=10
        )
        self.progress_bar.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))
        self.progress_bar.set(0)

        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="总计: 0  |  成功: 0  |  失败: 0  |  等待: 0",
            font=(ctk.CTkFont, FONT_SM),
            text_color="gray",
        )
        self.progress_label.pack(anchor="w", padx=PAD_MD, pady=(0, PAD_MD))

        # 状态表格
        self.table_frame = ctk.CTkScrollableFrame(
            self,
            height=160,
            corner_radius=RADIUS,
        )
        self.table_frame.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))

        self._build_table_header()

        # 日志
        log_label = ctk.CTkLabel(
            self,
            text="实时日志",
            font=(ctk.CTkFont, FONT_LG, "bold"),
        )
        log_label.pack(anchor="w", padx=PAD_LG)

        self.log_widget = LogWidget(
            self,
            log_queue=self.log_queue,
        )
        self.log_widget.pack(
            fill="both", expand=True, padx=PAD_LG, pady=(PAD_SM, PAD_LG)
        )

    def _build_table_header(self):
        header = ctk.CTkFrame(self.table_frame, fg_color="transparent")
        header.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))

        cols = [("用户", 140), ("活动ID", 100), ("状态", 120), ("时间", 100)]
        for text, width in cols:
            ctk.CTkLabel(
                header, text=text, font=(ctk.CTkFont, FONT_SM, "bold"), width=width
            ).pack(side="left", padx=PAD_SM)

    def _add_status_row(self, username: str, activity_id: str):
        row_frame = ctk.CTkFrame(self.table_frame, corner_radius=6)
        row_frame.pack(fill="x", padx=PAD_MD, pady=2)

        items = [
            ctk.CTkLabel(row_frame, text=username, font=(ctk.CTkFont, FONT_SM), width=140),
            ctk.CTkLabel(row_frame, text=activity_id, font=(ctk.CTkFont, FONT_SM), width=100),
            ctk.CTkLabel(row_frame, text="⏳ 等待", font=(ctk.CTkFont, FONT_SM), width=120),
            ctk.CTkLabel(row_frame, text="", font=(ctk.CTkFont, FONT_SM), width=100),
        ]
        for item in items:
            item.pack(side="left", padx=PAD_SM)

        self._status_rows.append({
            "frame": row_frame,
            "labels": items,
            "user": username,
            "activity_id": activity_id,
        })

    def _update_status(self, username: str, activity_id: str, status: str, icon: str):
        for row in self._status_rows:
            if row["user"] == username and row["activity_id"] == activity_id:
                row["labels"][2].configure(text=f"{icon} {status}")
                break
        self._update_progress()

    def _update_progress(self):
        total = len(self._status_rows)
        if total == 0:
            return
        success = sum(
            1 for r in self._status_rows
            if "成功" in r["labels"][2].cget("text")
        )
        failed = sum(
            1 for r in self._status_rows
            if "失败" in r["labels"][2].cget("text")
        )
        waiting = total - success - failed
        done = success + failed

        self.progress_bar.set(done / total)
        self.progress_label.configure(
            text=f"总计: {total}  |  成功: {success}  |  失败: {failed}  |  等待: {waiting}"
        )

    def _start_all(self):
        self.start_btn.configure(state="disabled")
        self.abort_btn.configure(state="normal")

        for row in self._status_rows:
            row["frame"].destroy()
        self._status_rows.clear()

        for user in self.user_manager.user_datas:
            for aid in user.get("activity_ids", []):
                self._add_status_row(user["userName"], str(aid))

        def _run():
            for user in self.user_manager.user_datas:
                if not user.get("activity_ids"):
                    continue

                def callback(status, msg):
                    for aid in user.get("activity_ids", []):
                        if aid in msg or str(aid) in msg:
                            if "成功" in msg:
                                self.after(0, lambda: self._update_status(
                                    user["userName"], str(aid), "成功", "✅"
                                ))
                            elif "失败" in msg:
                                self.after(0, lambda: self._update_status(
                                    user["userName"], str(aid), "失败", "❌"
                                ))

                single_account(user, callback=callback)

            self.after(0, self._all_done)

        threading.Thread(target=_run, daemon=True).start()

    def _abort_all(self):
        self.abort_btn.configure(state="disabled")
        # 通过标记位中止（core/activity_bot.py 的 abort 方法）
        from core.activity_bot import ActivityBot
        self.log_queue.put(("WARNING", "用户请求中止所有报名任务"))

    def _all_done(self):
        self.start_btn.configure(state="normal")
        self.abort_btn.configure(state="disabled")
        self.log_queue.put(("SUCCESS", "所有报名任务已完成"))
