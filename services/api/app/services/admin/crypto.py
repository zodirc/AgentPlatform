"""模型 Provider API Key 的 Fernet 加解密与掩码展示。

优先 ``CONFIG_ENCRYPTION_KEY``，保留 ``APP_SECRET_KEY`` 用于旧密文解密轮换。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.settings import settings


def _fernet_from_secret(secret: str) -> Fernet:
    """从任意长度 secret 派生 Fernet 密钥。"""
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encryption_secrets() -> list[str]:
    """Prefer CONFIG_ENCRYPTION_KEY when set; always keep APP_SECRET_KEY for decrypt."""
    secrets: list[str] = []
    extra = str(getattr(settings, "config_encryption_key", "") or "").strip()
    primary = str(settings.app_secret_key or "").strip()
    if extra:
        secrets.append(extra)
    if primary and primary not in secrets:
        secrets.append(primary)
    return secrets or [""]


def _fernet() -> Fernet:
    """当前加密用 Fernet（secrets 列表首项）。"""
    return _fernet_from_secret(_encryption_secrets()[0])


def encrypt_api_key(plaintext: str) -> bytes:
    """加密 API Key 明文为 Fernet 密文字节。

    参数:
        plaintext: 原始 API Key。

    返回:
        Fernet token bytes（存 DB ``api_key_ciphertext``）。
    """
    return _fernet().encrypt(plaintext.encode())


def decrypt_api_key(ciphertext: bytes) -> str:
    """解密 API Key；依次尝试全部配置 secret。

    参数:
        ciphertext: DB 密文。

    返回:
        明文 API Key。

    异常:
        InvalidToken: 所有 secret 均无法解密。
    """
    last: Exception | None = None
    for secret in _encryption_secrets():
        try:
            return _fernet_from_secret(secret).decrypt(ciphertext).decode()
        except InvalidToken as exc:
            last = exc
    if last is not None:
        raise last
    raise InvalidToken("no encryption secret configured")


def mask_api_key(api_key: str) -> str:
    """返回 UI 安全 hint（末 4 位可见）。

    参数:
        api_key: 明文 key。

    返回:
        如 ``••••abcd``；过短时 ``••••``。
    """
    if len(api_key) <= 4:
        return "••••"
    return f"••••{api_key[-4:]}"
