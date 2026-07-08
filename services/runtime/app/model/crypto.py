from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.settings import settings


def _fernet() -> Fernet:
    raw = settings.app_secret_key.encode()
    digest = hashlib.sha256(raw).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def decrypt_api_key(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()
