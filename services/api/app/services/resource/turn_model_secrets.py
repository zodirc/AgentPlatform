"""Per-turn model override escrow (encrypted; claim consumes once)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.services.admin.crypto import encrypt_api_key
from app.settings import settings


def _normalize_override(override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "provider": str(override.get("provider") or "openai"),
        "model_name": str(override.get("model_name") or "model"),
        "api_key": str(override["api_key"]),
    }
    if override.get("base_url"):
        out["base_url"] = str(override["base_url"])
    cw = override.get("context_window_tokens")
    if isinstance(cw, int) and cw >= 4096:
        out["context_window_tokens"] = cw
    return out


async def store_turn_model_secret(
    conn,
    *,
    run_id: UUID,
    turn_id: UUID,
    model_override: dict[str, Any],
    ttl_seconds: float | None = None,
) -> None:
    """Encrypt override into turn_model_secrets (same Fernet as provider profiles)."""
    payload = _normalize_override(model_override)
    if not payload.get("api_key"):
        raise ValueError("model_override.api_key required")
    ttl = ttl_seconds
    if ttl is None:
        claim = float(getattr(settings, "turn_claim_timeout_seconds", 15.0) or 15.0)
        ttl = max(60.0, claim * 4.0)
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    ciphertext = encrypt_api_key(json.dumps(payload, separators=(",", ":")))
    await conn.execute(
        """
        INSERT INTO turn_model_secrets (run_id, turn_id, ciphertext, expires_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (run_id) DO UPDATE SET
            ciphertext = EXCLUDED.ciphertext,
            expires_at = EXCLUDED.expires_at,
            consumed_at = NULL,
            created_at = now()
        """,
        run_id,
        turn_id,
        ciphertext,
        expires,
    )


async def purge_expired_turn_model_secrets() -> int:
    pool = await get_pool()
    result = await pool.execute(
        """
        DELETE FROM turn_model_secrets
        WHERE consumed_at IS NOT NULL
           OR expires_at < now()
        """
    )
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0
