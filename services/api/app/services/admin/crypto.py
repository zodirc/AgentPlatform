from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.settings import settings


def _fernet_from_secret(secret: str) -> Fernet:
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
    return _fernet_from_secret(_encryption_secrets()[0])


def encrypt_api_key(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_api_key(ciphertext: bytes) -> str:
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
    if len(api_key) <= 4:
        return "••••"
    return f"••••{api_key[-4:]}"
