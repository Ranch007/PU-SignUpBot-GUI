"""报名监控内联面板"""
from typing import Dict, List, Callable
import threading
import customtkinter as ctk

from ui.styles import FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, RADIUS, LIGHT_FRAME, DARK_FRAME
from core.single import single_account


class SignupInline(ctk.CTkFrame):
    def __init__(self, parent, user_manager, log_queue, on_close: Callable, **kw):
        super().__init__(parent, corner_radius=RADIUS, fg_color=(LIGHT_FRAME, DARK_FRAME), **kw)
        self.user_manager = user_manager
        self.log_queue = log_queue
        self._on_close = on_close
        self._status_rows: List[Dict] = []
        self._running = False

        self._build()

    def _build(self):
        # 标题栏
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        ctk.CTkLabel(bar, text="报名监控", font=(ctk.CTkFont, FONT_LG, "bold")).pack(side="left")

        self._abort_btn = ctk.CTkButton(bar, text="⏹ 中止", fg_color="#c0392b", hover_color="#a93226", height=32, font=(ctk.CTkFont, FONT_SM), state="disabled", command=self._abort)
        self._abort_btn.pack(side="right", padx=(0, PAD_SM))

        self._start_btn = ctk.CTkButton(bar, text="▶ 全部开始", fg_color="#2e8b57", hover_color="#1e6b3a", height=32, font=(ctk.CTkFont, FONT_SM), command=self._start)
        self._start_btn.pack(side="right", padx=(0, PAD_SM))

        # 进度条
        prog = ctk.CTkFrame(self, corner_radius=8, fg_color=("gray90", "gray17"))
        prog.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))

        self._progress = ctk.CTkProgressBar(prog, height=18, corner_radius=9)
        self._progress.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))
        self._progress.set(0)

        self._prog_label = ctk.CTkLabel(prog, text="总计: 0  |  成功: 0  |  失败: 0  |  等待: 0", font=(ctk.CTkFont, FONT_SM), text_color="gray")
        self._prog_label.pack(anchor="w", padx=PAD_MD, pady=(0, PAD_MD))

        # 状态表格
        self._table = ctk.CTkScrollableFrame(self, height=140, corner_radius=RADIUS)
        self._table.pack(fill="x", padx=PAD_LG, pady=(0, PAD_MD))

        # 表头
        hdr = ctk.CTkFrame(self._table, fg_color="transparent")
        hdr.pack(fill="x", padx=PAD_MD, pady=(PAD_MD, PAD_SM))
        for txt, w in [("用户", 140), ("活动ID", 100), ("状态", 120), ("时间", 100)]:
            ctk.CTkLabel(hdr, text=txt, font=(ctk.CTkFont, FONT_SM, "bold"), width=w).pack(side="left", padx=PAD_SM)

    # ======================== 报名逻辑 ========================

    def _start(self):
        self._start_btn.configure(state="disabled")
        self._abort_btn.configure(state="normal")
        self._clear_table()

        for user in self.user_manager.user_datas:
            for aid in user.get("activity_ids", []):
                self._add_row(user["userName"], str(aid))

        if not self._status_rows:
            self.log_queue.put(("WARNING", "没有待报名的活动"))
            self._start_btn.configure(state="normal")
            self._abort_btn.configure(state="disabled")
            return

        self._running = True

        def _run():
            for user in self.user_manager.user_datas:
                if not user.get("activity_ids"):
                    continue

                def cb(status, msg):
                    for aid in user.get("activity_ids", []):
                        if aid in msg or str(aid) in msg:
                            if "成功" in msg:
                                self.after(0, lambda u=user["userName"], a=str(aid): self._update(u, a, "成功", "✅"))
                            elif "失败" in msg:
                                self.after(0, lambda u=user["userName"], a=str(aid): self._update(u, a, "失败", "❌"))

                single_account(user, callback=cb)
                if not self._running:
                    break

            self.after(0, self._done)

        threading.Thread(target=_run, daemon=True).start()

    def _abort(self):
        self._running = False
        self._abort_btn.configure(state="disabled")
        self.log_queue.put(("WARNING", "用户请求中止所有报名任务"))

    def _add_row(self, username: str, activity_id: str):
        row = ctk.CTkFrame(self._table, corner_radius=6)
        row.pack(fill="x", padx=PAD_MD, pady=2)

        items = [
            ctk.CTkLabel(row, text=username, font=(ctk.CTkFont, FONT_SM), width=140),
            ctk.CTkLabel(row, text=activity_id, font=(ctk.CTkFont, FONT_SM), width=100),
            ctk.CTkLabel(row, text="⏳ 等待", font=(ctk.CTkFont, FONT_SM), width=120),
            ctk.CTkLabel(row, text="", font=(ctk.CTkFont, FONT_SM), width=100),
        ]
        for item in items:
            item.pack(side="left", padx=PAD_SM)

        self._status_rows.append({"frame": row, "labels": items, "user": username, "aid": activity_id})

    def _update(self, username: str, activity_id: str, status: str, icon: str):
        for r in self._status_rows:
            if r["user"] == username and r["aid"] == activity_id:
                r["labels"][2].configure(text=f"{icon} {status}")
                break
        self._refresh_progress()

    def _refresh_progress(self):
        total = len(self._status_rows)
        if total == 0:
            return
        success = sum(1 for r in self._status_rows if "成功" in r["labels"][2].cget("text"))
        failed = sum(1 for r in self._status_rows if "失败" in r["labels"][2].cget("text"))
        done = success + failed
        self._progress.set(done / total)
        self._prog_label.configure(text=f"总计: {total}  |  成功: {success}  |  失败: {failed}  |  等待: {total - done}")

    def _done(self):
        self._running = False
        self._start_btn.configure(state="normal")
        self._abort_btn.configure(state="disabled")
        self.log_queue.put(("SUCCESS", "所有报名任务已完成"))

    def _clear_table(self):
        for r in self._status_rows:
            r["frame"].destroy()
        self._status_rows.clear()
        self._progress.set(0)
        self._prog_label.configure(text="总计: 0  |  成功: 0  |  失败: 0  |  等待: 0")
