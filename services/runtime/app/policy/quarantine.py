"""Encrypted quarantine. Raw bodies do not go into turn_events."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from app.settings import settings

_TTL_SECONDS = 7 * 24 * 3600


def _root() -> Path:
    return Path(settings.data_dir) / "quarantine"


def _key() -> bytes:
    secret = str(getattr(settings, "internal_service_token", "") or "quarantine")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _seal(body: bytes) -> bytes:
    nonce = os.urandom(16)
    stream = _keystream(nonce, len(body))
    cipher = bytes(left ^ right for left, right in zip(body, stream))
    mac = hmac.new(_key(), nonce + cipher, hashlib.sha256).digest()
    return nonce + mac + cipher


def _open(blob: bytes) -> bytes | None:
    if len(blob) < 48:
        return None
    nonce, mac, cipher = blob[:16], blob[16:48], blob[48:]
    expected = hmac.new(_key(), nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        return None
    stream = _keystream(nonce, len(cipher))
    return bytes(left ^ right for left, right in zip(cipher, stream))


def _keystream(nonce: bytes, size: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < size:
        block = hashlib.sha256(_key() + nonce + counter.to_bytes(4, "big")).digest()
        out += block
        counter += 1
    return out[:size]


def put(*, body: str, turn_id: str, tool_name: str) -> str:
    """Store a body and return its id. The audit log keeps the id only."""
    item_id = uuid.uuid4().hex
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": item_id,
        "turn_id": turn_id,
        "tool_name": tool_name,
        "created_at": time.time(),
        "expires_at": time.time() + _TTL_SECONDS,
        "access_count": 0,
    }
    (root / f"{item_id}.json").write_text(json.dumps(meta), encoding="utf-8")
    (root / f"{item_id}.bin").write_bytes(_seal(body.encode("utf-8")))
    return item_id


def meta(item_id: str) -> dict[str, Any] | None:
    """Metadata only. Does not decrypt the body or count as a read."""
    path = _root() / f"{item_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read(item_id: str, *, actor: str = "") -> str | None:
    """Decrypt one body and append an access record. Expired items return None."""
    root = _root()
    meta_path = root / f"{item_id}.json"
    blob_path = root / f"{item_id}.bin"
    if not meta_path.is_file() or not blob_path.is_file():
        return None
    meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    if float(meta.get("expires_at") or 0) < time.time():
        return None
    body = _open(blob_path.read_bytes())
    if body is None:
        return None
    meta["access_count"] = int(meta.get("access_count") or 0) + 1
    accesses = meta.get("accesses")
    if not isinstance(accesses, list):
        accesses = []
    accesses.append({"at": time.time(), "actor": actor})
    meta["accesses"] = accesses
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return body.decode("utf-8")


def release(item_id: str, *, actor: str = "") -> dict[str, Any] | None:
    """Audit the read, return the body to the caller, then delete the ciphertext.

    The body is the release. It is not written into turn_events. The caller
    shows it to the user so they can send it as their own message.
    """
    body = read(item_id, actor=actor)
    if body is None:
        return None
    root = _root()
    blob = root / f"{item_id}.bin"
    meta_path = root / f"{item_id}.json"
    try:
        blob.unlink()
    except OSError:
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["released"] = True
        meta["released_by"] = actor
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass
    return {"released": True, "id": item_id, "body": body}
