"""终端用户 PBKDF2 密码哈希与校验。

格式 ``pbkdf2_sha256$iterations$salt$digest``；使用 ``hmac.compare_digest`` 防时序攻击。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 210_000
_PREFIX = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """对新密码生成随机 salt 并 PBKDF2 哈希。

    参数:
        password: 明文密码。

    返回:
        可存入 DB 的哈希字符串。
    """
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _ITERATIONS,
    ).hex()
    return f"{_PREFIX}${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文是否与存储哈希匹配。

    参数:
        password: 用户输入明文。
        password_hash: DB 中 ``password_hash`` 列。

    返回:
        True 匹配；格式错误或 prefix 不对时为 False。
    """
    try:
        prefix, iters_s, salt, expected = password_hash.split("$", 3)
        if prefix != _PREFIX:
            return False
        iterations = int(iters_s)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(digest, expected)
