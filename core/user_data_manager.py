import base64
import binascii
from typing import Dict, List, Optional

from core.crypto_utils import decrypt_password, protect_secret, unprotect_secret
from core.atomic_json import read_json, write_json
from loguru import logger
from core.accounts import account_key
from core.config import MAX_ACCOUNTS


class UserDataManager:
    def __init__(self, file_path: str, settings_path: str = "settings.json"):
        self.file_path = file_path
        self.settings_path = settings_path
        self.recovered_from_backup = False
        self._migration_needed = False
        self.user_datas: List[Dict] = self.read_user_data()
        self.settings: Dict = self._read_settings()
        if self._migration_needed or self.recovered_from_backup:
            self.write_user_data()

    @staticmethod
    def _looks_encrypted(value: str) -> bool:
        try:
            raw = base64.b64decode(value, validate=True)
            return len(raw) >= 32 and len(raw) % 16 == 0
        except (ValueError, binascii.Error):
            return False

    def read_user_data(self) -> List[Dict]:
        logger.info("开始加载用户数据")
        data, backup = read_json(self.file_path, [], list)
        self.recovered_from_backup = backup
        if backup:
            logger.warning("用户数据主文件损坏，已从备份恢复")

        if not data:
            logger.warning("用户数据为空")
            return []

        usernames = [user.get("userName") for user in data if isinstance(user, dict)]
        if len(usernames) != len(data) or any(
                not isinstance(name, str) or not name for name in usernames):
            raise ValueError("账号文件格式错误，请保留原文件与备份")
        identities = [account_key(user) for user in data]
        if len(identities) != len(set(identities)):
            raise ValueError("账号文件存在同学校重名学号；请备份后删除重复记录再启动")

        for user in data:
            for field in ("password", "token"):
                if field not in user:
                    continue
                stored = user[field]
                try:
                    if not isinstance(stored, str):
                        raise ValueError("凭据不是字符串")
                    if stored.startswith(("dpapi:v1:", "enc:v1:")):
                        user[field] = unprotect_secret(stored)
                        if stored.startswith("enc:v1:"):
                            self._migration_needed = True
                    elif field == "password" and self._looks_encrypted(stored):
                        user[field] = decrypt_password(stored)
                        self._migration_needed = True
                    else:
                        self._migration_needed = True
                except Exception:
                    user.pop("password", None)
                    user.pop("token", None)
                    user["credential_error"] = "本地凭据无法解密，请重新登录"
                    break

            user.pop("email", None)

        return data

    def write_user_data(self) -> None:
        data_to_write = []
        for user in self.user_datas:
            u = {k: v for k, v in user.items() if k not in ("email", "credential_error")}
            for field in ("password", "token"):
                if u.get(field):
                    u[field] = protect_secret(u[field])
                else:
                    u.pop(field, None)
            data_to_write.append(u)

        write_json(self.file_path, data_to_write)

    def add_user(self, user: Dict) -> bool:
        if self.get_user(account_key(user)) is not None:
            logger.warning("同名账号已存在: {}", user.get("userName"))
            return False
        if len(self.user_datas) >= MAX_ACCOUNTS:
            logger.warning("用户数已达上限（{}个）", MAX_ACCOUNTS)
            return False
        user.pop("email", None)
        self.user_datas.append(user)
        logger.info(f"新用户添加成功: {user.get('userName')}")
        return True

    def remove_user(self, username: str) -> bool:
        user = self.get_user(username)
        if user is None:
            return False
        self.user_datas.remove(user)
        return True

    def update_user(self, username: str, updates: Dict) -> bool:
        user = self.get_user(username)
        if user is None:
            return False
        clean = {key: value for key, value in updates.items() if key != "email"}
        if account_key(dict(user, **clean)) != account_key(user):
            raise ValueError("不能通过资料更新改变学校或学号")
        user.update(clean)
        return True

    def get_user(self, username: str) -> Optional[Dict]:
        if isinstance(username, tuple):
            matches = [user for user in self.user_datas if account_key(user) == tuple(map(str, username))]
        else:
            matches = [user for user in self.user_datas if user.get("userName") == username]
        if len(matches) > 1:
            raise ValueError("学号对应多个学校，请使用学校和学号选择账号")
        return matches[0] if matches else None

    # -------- settings.json 管理 --------

    def _read_settings(self) -> Dict:
        data, backup = read_json(self.settings_path, {"pending_monitors": []}, dict)
        if backup:
            logger.warning("设置主文件损坏，已从备份恢复")
            write_json(self.settings_path, data)
        return data

    def get_pending_monitors(self) -> List[Dict]:
        monitors = self.settings.get("pending_monitors", [])
        return [item for item in monitors if isinstance(item, dict)] if isinstance(monitors, list) else []
