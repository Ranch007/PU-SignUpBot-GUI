"""单账号报名调度：按顺序处理每个活动的报名"""
from typing import Dict, Optional, Callable

from core.activity_bot import ActivityBot
from core.PUExceptions import ActivityIDsEmptyError
from loguru import logger


def single_account(user_data: Dict, callback: Optional[Callable] = None) -> None:
    logger.info(f"开始处理用户 {user_data['userName']} 的报名请求")
    bot = ActivityBot(user_data)

    try:
        activity_ids = user_data.get("activity_ids", [])
        if not activity_ids:
            raise ActivityIDsEmptyError(user_data["userName"])

        logger.info(f"用户 {user_data['userName']} 需要报名的活动ID: {activity_ids}")
        bot.sync_server_time(activity_ids[0])

        for activity_id in activity_ids:
            if bot._abort:
                break
            logger.info(f"用户 {user_data['userName']} 开始处理活动 {activity_id}")
            bot.signup(activity_id, callback=callback)

        logger.info(f"用户 {user_data['userName']} 所有活动报名已完成")

    except ActivityIDsEmptyError:
        logger.warning(
            f"用户 {user_data['userName']} 活动列表为空，跳过"
        )
        if callback:
            callback("warning", f"用户 {user_data['userName']} 没有待报名的活动")
