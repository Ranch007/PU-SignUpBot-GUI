"""PU-SignUpBot GUI 入口"""
import sys
from pathlib import Path
from loguru import logger

from core.data_paths import data_directory, migrate_legacy_data
from core.user_data_manager import UserDataManager
from core.task_store import TaskStore
from ui.app import App


def setup_logging(directory: Path):
    """配置日志：文件（WARNING+）+ 控制台（INFO+）+ GUI 队列"""
    logger.remove()

    logs = directory / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(logs / "{time:YYYY-MM-DD}.log"),
        rotation="00:00",
        retention="7 days",
        compression="zip",
        enqueue=True,
        encoding="utf-8",
        filter=lambda rec: rec["level"].no >= 30,
    )

    if sys.stdout is not None:
        logger.add(
            sys.stdout,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<level>{message}</level>"
            ),
            level="INFO",
        )


def main():
    legacy_directory = (Path(sys.executable).resolve().parent if
                        getattr(sys, "frozen", False) else Path(__file__).resolve().parent)
    directory = data_directory()
    try:
        migrated = migrate_legacy_data(legacy_directory, directory)
        setup_logging(directory)
    except OSError as exc:
        from tkinter import messagebox
        messagebox.showerror("无法准备数据目录", f"无法写入 {directory}：{exc}")
        return
    logger.info("PU-SignUpBot GUI 启动中...")

    try:
        user_manager = UserDataManager(str(directory / "user_data.json"),
                                       str(directory / "settings.json"))
    except (OSError, ValueError) as exc:
        logger.error("读取本地数据失败：{}", exc)
        from tkinter import messagebox
        messagebox.showerror("本地数据需要修复",
                             f"账号或设置文件无法读取：{exc}\n数据目录：{directory}"
                             "\n请保留原文件与 .bak 备份后再处理。")
        return

    if not user_manager.user_datas:
        logger.warning("未找到用户数据，请在 GUI 中添加用户")

    try:
        app = App(user_manager, TaskStore(str(directory / "signup_tasks.json")))
    except (OSError, ValueError) as exc:
        logger.error("读取报名任务失败：{}", exc)
        from tkinter import messagebox
        messagebox.showerror("报名计划需要修复", f"任务记录无法读取：{exc}\n请保留原文件与 .bak 备份后再处理。")
        return
    if migrated:
        from tkinter import messagebox
        app.after(200, lambda: messagebox.showinfo(
            "旧数据已迁移",
            f"账号及任务数据已复制到：\n{directory}\n\n"
            "原目录文件仍保留。确认新版本正常后，请妥善处理旧副本。",
            parent=app))
    app.mainloop()


if __name__ == "__main__":
    main()
