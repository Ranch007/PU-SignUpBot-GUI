"""PU-SignUpBot GUI 入口"""
import os
import sys
from loguru import logger

from core.user_data_manager import UserDataManager
from ui.app import App


def setup_logging():
    """配置日志：文件（WARNING+）+ 控制台（INFO+）+ GUI 队列"""
    logger.remove()

    os.makedirs("logs", exist_ok=True)

    logger.add(
        "logs/{time:YYYY-MM-DD}.log",
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
    setup_logging()
    logger.info("PU-SignUpBot GUI 启动中...")

    user_manager = UserDataManager("user_data.json")

    if not user_manager.user_datas:
        logger.warning("未找到用户数据，请在 GUI 中添加用户")

    app = App(user_manager)
    app.mainloop()


if __name__ == "__main__":
    main()
