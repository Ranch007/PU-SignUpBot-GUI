import json
import os
from typing import Dict, List, Optional

from core.crypto_utils import encrypt_password, decrypt_password
from loguru import logger


class UserDataManager:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.user_datas: List[Dict] = self.read_user_data()

    def read_user_data(self) -> List[Dict]:
        logger.info("开始加载用户数据")
        if not os.path.exists(self.file_path):
            logger.warning("未找到用户数据文件")
            return []

        with open(self.file_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                logger.error("用户数据格式解析错误")
                return []

        if not data:
            logger.warning("用户数据为空")
            return []

        for user in data:
            if "password" in user:
                try:
                    user["password"] = decrypt_password(user["password"])
                except Exception:
                    pass

            user.pop("email", None)

        return data

    def write_user_data(self) -> None:
        data_to_write = []
        for user in self.user_datas:
            u = {k: v for k, v in user.items() if k != "email"}
            if "password" in u:
                try:
                    decrypt_password(u["password"])
                    encrypted = encrypt_password(u["password"])
                except Exception:
                    encrypted = encrypt_password(u["password"])
                u["password"] = encrypted
            data_to_write.append(u)

        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data_to_write, f, indent=4, ensure_ascii=False)

    def add_user(self, user: Dict) -> None:
        if "email" in user:
            del user["email"]
        self.user_datas.append(user)
        logger.info(f"新用户添加成功: {user.get('userName')}")

    def remove_user(self, username: str) -> bool:
        for i, user in enumerate(self.user_datas):
            if user.get("userName") == username:
                self.user_datas.pop(i)
                logger.info(f"用户已删除: {username}")
                return True
        logger.warning(f"未找到要删除的用户: {username}")
        return False

    def update_user(self, username: str, updates: Dict) -> bool:
        for user in self.user_datas:
            if user.get("userName") == username:
                updates.pop("email", None)
                user.update(updates)
                logger.info(f"用户已更新: {username}")
                return True
        logger.warning(f"未找到要更新的用户: {username}")
        return False

    def get_user(self, username: str) -> Optional[Dict]:
        for user in self.user_datas:
            if user.get("userName") == username:
                return user
        return None

    def sign_up(self) -> None:
        logger.info("开始处理用户报名任务")
        from core.single import single_account

        for user in self.user_datas:
            single_account(user)
        logger.info("所有用户报名任务处理完成")
