import base64
import binascii
import hashlib
import re
from typing import Any

password_pattern = r"^(?=.*[a-zA-Z])(?=.*\d)[A-Za-z\d._@#$%*!?\-]{6,32}$"

# PBKDF2-HMAC-SHA256 迭代次数（OWASP 2023 推荐 ≥ 600,000）
PBKDF2_ITERATIONS = 600_000
# 历史版本 1 的迭代次数（10,000），用于兼容存量哈希；登录成功后透明升级到新参数
PBKDF2_ITERATIONS_V1 = 10_000

# 当前密码哈希格式版本号：1=旧参数(10k 迭代)，2=新参数(600k 迭代)
PASSWORD_HASH_VERSION_CURRENT = 2


def password_iterations_for_version(version: Any) -> int:
    """根据存储的密码哈希版本返回对应的迭代次数。"""
    return PBKDF2_ITERATIONS if int(version or 1) >= 2 else PBKDF2_ITERATIONS_V1


def validate_password(password: str, pattern: str = password_pattern):
    """校验传入的密码是否符合相应的匹配规则"""
    if re.match(pattern, password) is None:
        raise ValueError("密码规则校验失败，至少包含一个字母，一个数字，支持常规符号，并且长度为6-32位")
    return


def hash_password(password: str, salt: Any, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    """将传入的密码+盐值进行哈希加密"""
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return binascii.hexlify(dk)


def compare_password(
    password: str,
    password_hashed_base64: Any,
    salt_base64: Any,
    iterations: int = PBKDF2_ITERATIONS,
) -> bool:
    """根据传递的密码+盐值校验比对是否一致"""
    return hash_password(password, base64.b64decode(salt_base64), iterations) == base64.b64decode(
        password_hashed_base64
    )
