"""添加用户内联表单"""
import customtkinter as ctk
import threading
from queue import Empty, Queue
from typing import Callable

from ui.styles import FONT_LG, FONT_MD, FONT_SM, PAD_LG, PAD_MD, PAD_SM, RADIUS, LIGHT_FRAME, DARK_FRAME
from core.tools import get_school_candidates, login
from core.config import MAX_ACCOUNTS
from core.accounts import account_key


class AddUserInline(ctk.CTkFrame):
    def __init__(self, parent, user_manager, on_done: Callable, on_cancel: Callable, **kw):
        super().__init__(parent, corner_radius=RADIUS, fg_color=(LIGHT_FRAME, DARK_FRAME), **kw)
        self.user_manager = user_manager
        self._on_done = on_done
        self._on_cancel = on_cancel
        self.step = 0
        self._data = {}
        self._status = None
        self._form = None
        self._btn_frame = None
        self._results = Queue()
        self._generation = 0
        self._active = True

        self._build_header()
        self._show_step()
        self.after(100, self._poll_results)

    def _poll_results(self):
        if not self._active:
            return
        while True:
            try:
                kind, generation, result = self._results.get_nowait()
            except Empty:
                break
            if generation != self._generation:
                continue
            if kind == "school" and self.step == 1:
                self._search_btn.configure(state="normal")
                if isinstance(result, Exception):
                    self.school_result.configure(text=f"学校搜索失败：{result}", text_color="#e74c3c")
                elif result:
                    self._schools = {f"{school['name']} (SID: {school['id']})": school["id"]
                                     for school in result}
                    options = list(self._schools)
                    self.school_choice.configure(values=options, state="normal")
                    self.school_choice.set(options[0] if len(options) == 1 else "请选择学校")
                    if len(options) == 1:
                        self._choose_school(options[0])
                    else:
                        self.school_result.configure(text=f"找到 {len(options)} 所学校，请确认完整名称",
                                                     text_color="gray")
                else:
                    self.school_result.configure(text="未找到匹配学校", text_color="#e74c3c")
            elif kind == "profile" and self.step == 2:
                self._save_btn.configure(state="normal")
                if isinstance(result, Exception):
                    self._status.configure(text=f"登录失败：{result}", text_color="#e74c3c")
                    self._save_btn.configure(text="重新验证")
                else:
                    self._data.update(result)
                    for entry, field in ((self.college_entry, "college"), (self.year_entry, "year")):
                        if result.get(field) and not entry.get().strip():
                            entry.insert(0, str(result[field]))
                    self._status.configure(text="登录已验证，请核对院系和年级后保存；未返回的资料可手动补充", text_color="gray")
                    self._save_btn.configure(text="保存账号")
        self.after(100, self._poll_results)

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_MD))

        self.step_label = ctk.CTkLabel(
            bar, text="", font=(ctk.CTkFont, FONT_LG, "bold")
        )
        self.step_label.pack(side="left")

        ctk.CTkButton(
            bar, text="取消", fg_color="gray", width=60, height=30,
            font=(ctk.CTkFont, FONT_SM), command=self._cancel,
        ).pack(side="right")

    def cancel_pending(self):
        self._generation += 1
        self._active = False

    def _cancel(self):
        self.cancel_pending()
        self._on_cancel()

    def _make_form(self):
        if self._form:
            self._form.destroy()
        if self._btn_frame:
            self._btn_frame.destroy()
        if self._status:
            self._status.destroy()

        self._form = ctk.CTkFrame(self, fg_color="transparent")
        self._form.pack(fill="both", expand=True, padx=PAD_LG, pady=PAD_MD)

        self._status = ctk.CTkLabel(self, text="", font=(ctk.CTkFont, FONT_SM))
        self._status.pack(anchor="w", padx=PAD_LG)

        self._btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._btn_frame.pack(fill="x", padx=PAD_LG, pady=(0, PAD_LG))

    def _show_step(self):
        self._generation += 1
        self._make_form()

        if self.step == 0:
            self._step1()
        elif self.step == 1:
            self._step2()
        elif self.step == 2:
            self._step3()

    def _step1(self):
        self.step_label.configure(text="步骤 1/3：输入凭证")

        ctk.CTkLabel(self._form, text="用户名（学号）", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w", pady=(0, PAD_SM))
        self.user_entry = ctk.CTkEntry(self._form, placeholder_text="请输入学号", height=36, font=(ctk.CTkFont, FONT_MD))
        self.user_entry.pack(fill="x", pady=(0, PAD_MD))

        ctk.CTkLabel(self._form, text="密码", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w", pady=(0, PAD_SM))
        self.pw_entry = ctk.CTkEntry(self._form, placeholder_text="请输入密码", show="*", height=36, font=(ctk.CTkFont, FONT_MD))
        self.pw_entry.pack(fill="x")

        ctk.CTkButton(self._btn_frame, text="下一步", height=34, font=(ctk.CTkFont, FONT_MD), command=self._s1_next).pack(side="right")

    def _s1_next(self):
        u = self.user_entry.get().strip()
        p = self.pw_entry.get()
        if not u or not p.strip():
            self._status.configure(text="请输入用户名和密码", text_color="#e74c3c")
            return
        self._data.pop("token", None)
        self._data["userName"] = u
        self._data["password"] = p
        self._data["device"] = "pc"
        self._data["activity_ids"] = []
        self._data["categorys"] = []
        self._data["oids"] = []
        self._data["cids"] = []
        self._data["allowYears"] = []
        self.step = 1
        self._show_step()

    def _step2(self):
        self.step_label.configure(text="步骤 2/3：选择学校")

        ctk.CTkLabel(self._form, text="学校关键词", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w", pady=(0, PAD_SM))

        row = ctk.CTkFrame(self._form, fg_color="transparent")
        row.pack(fill="x", pady=(0, PAD_MD))

        self.school_entry = ctk.CTkEntry(row, placeholder_text="如：山东科技大学", height=36, font=(ctk.CTkFont, FONT_MD))
        self.school_entry.pack(side="left", fill="x", expand=True, padx=(0, PAD_SM))

        self._search_btn = ctk.CTkButton(row, text="搜索", width=80, height=36,
                                         font=(ctk.CTkFont, FONT_MD), command=self._search)
        self._search_btn.pack(side="right")

        self.school_result = ctk.CTkLabel(self._form, text="", font=(ctk.CTkFont, FONT_SM))
        self.school_result.pack(anchor="w")
        self._schools = {}
        self.school_choice = ctk.CTkOptionMenu(self._form, values=["请先搜索学校"],
                                               state="disabled", command=self._choose_school)
        self.school_choice.pack(fill="x", pady=PAD_SM)

        ctk.CTkButton(self._btn_frame, text="上一步", height=34, fg_color="gray", font=(ctk.CTkFont, FONT_MD), command=lambda: self._go(0)).pack(side="left")

        self.next2 = ctk.CTkButton(self._btn_frame, text="下一步", height=34, font=(ctk.CTkFont, FONT_MD), state="disabled", command=self._s2_next)
        self.next2.pack(side="right")

    def _search(self):
        name = self.school_entry.get().strip()
        if not name:
            return
        self.school_result.configure(text="搜索中...", text_color="gray")
        self.next2.configure(state="disabled")
        self._search_btn.configure(state="disabled")
        self.school_choice.configure(state="disabled")
        self._schools = {}
        self._data.pop("sid", None)
        self._generation += 1
        generation = self._generation

        def run():
            try:
                result = get_school_candidates(name)
            except Exception as exc:
                result = exc
            self._results.put(("school", generation, result))

        threading.Thread(target=run, daemon=True).start()

    def _choose_school(self, label: str):
        sid = self._schools.get(label)
        if sid is None:
            return
        self._data.pop("token", None)
        if self._data.get("sid") != sid:
            for field in ("college", "year", "realname", "sex"):
                self._data.pop(field, None)
        self._data["sid"] = sid
        self._data["school"] = label.rsplit(" (SID:", 1)[0]
        self.school_result.configure(text=f"已选择：{label}", text_color="#2ecc71")
        self.next2.configure(state="normal")

    def _s2_next(self):
        if self.user_manager.get_user(account_key(self._data)):
            self._status.configure(text="此学校的学号已添加，请在原账号上重新登录", text_color="#e74c3c")
            return
        self.step = 2
        self._show_step()
        self._verify_profile()

    def _step3(self):
        self.step_label.configure(text="步骤 3/3：补充信息")

        ctk.CTkLabel(self._form, text="院系全称", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w", pady=(0, PAD_SM))
        self.college_entry = ctk.CTkEntry(self._form, placeholder_text="如：经济管理学院", height=36, font=(ctk.CTkFont, FONT_MD))
        self.college_entry.pack(fill="x", pady=(0, PAD_MD))
        ctk.CTkLabel(self._form, text="年级（可选，与 PU 年级编号一致）", font=(ctk.CTkFont, FONT_MD)).pack(anchor="w")
        self.year_entry = ctk.CTkEntry(self._form, height=36, placeholder_text="未返回时可补充")
        self.year_entry.pack(fill="x", pady=(0, PAD_MD))


        ctk.CTkLabel(self._form, text="PU 未返回的院系和年级可手动补充；请使用与 PU 一致的值", font=(ctk.CTkFont, FONT_SM), text_color="gray").pack(anchor="w")

        ctk.CTkButton(self._btn_frame, text="上一步", height=34, fg_color="gray", font=(ctk.CTkFont, FONT_MD), command=lambda: self._go(1)).pack(side="left")
        self._save_btn = ctk.CTkButton(self._btn_frame, text="验证并保存", height=34,
                                       fg_color="#2e8b57", hover_color="#1e6b3a",
                                       font=(ctk.CTkFont, FONT_MD), command=self._s3_save)
        self._save_btn.pack(side="right")

    def _s3_save(self):
        if not self._data.get("token"):
            self._verify_profile()
            return
        college = self.college_entry.get().strip()
        if not college:
            self._status.configure(text="PU 未返回院系，请补充院系全称", text_color="#e74c3c")
            return
        self._data["college"] = college
        if self.year_entry.get().strip():
            self._data["year"] = self.year_entry.get().strip()
        if not self.user_manager.add_user(dict(self._data)):
            self._status.configure(text=f"此学校的学号已添加，或账号数已达 {MAX_ACCOUNTS} 个上限", text_color="#e74c3c")
            return
        try:
            self.user_manager.write_user_data()
        except OSError as exc:
            self.user_manager.remove_user(account_key(self._data))
            self._status.configure(text=f"保存失败：{exc}", text_color="#e74c3c")
            return
        self._on_done()

    def _verify_profile(self):
        self._status.configure(text="正在验证登录并读取资料...", text_color="gray")
        self._save_btn.configure(state="disabled")
        self._generation += 1
        generation = self._generation
        data = dict(self._data)
        def run():
            try:
                result = login(data)
            except Exception as exc:
                result = exc
            self._results.put(("profile", generation, result))
        threading.Thread(target=run, daemon=True).start()

    def _go(self, target: int):
        self.step = target
        self._show_step()
