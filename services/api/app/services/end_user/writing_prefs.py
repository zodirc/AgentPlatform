from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from agent_contracts.writing_prefs import (
    PRESET_LABELS,
    SCHEMA_VERSION,
    merge_prefs,
    platform_fragment_weights,
    platform_prefs_payload,
    validate_signal_table,
)
from pydantic import BaseModel, Field

from app.db.pool import get_pool


class WritingPrefsResponse(BaseModel):
    preset_label: str
    fragment_weights: dict[str, dict[str, float]]
    signal_penalties: dict[str, dict[str, float]]
    signal_rewards: dict[str, dict[str, float]]
    exemplars: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    schema_version: int
    updated_at: datetime | None = None
    is_custom: bool = False


class UpdateWritingPrefsRequest(BaseModel):
    preset_label: str | None = None
    fragment_weights: dict[str, dict[str, float]] | None = None
    signal_penalties: dict[str, Any] | None = None
    signal_rewards: dict[str, Any] | None = None


def _row_to_response(row: Any | None, *, merged: dict[str, Any]) -> WritingPrefsResponse:
    is_custom = row is not None
    updated = row["updated_at"] if row is not None else None
    return WritingPrefsResponse(
        preset_label=str(merged.get("preset_label") or "balanced"),
        fragment_weights=merged["fragment_weights"],
        signal_penalties=merged["signal_penalties"],
        signal_rewards=merged["signal_rewards"],
        exemplars=merged.get("exemplars") or {},
        schema_version=int(merged.get("schema_version") or SCHEMA_VERSION),
        updated_at=updated,
        is_custom=is_custom,
    )


async def get_prefs(owner_user_id: UUID) -> WritingPrefsResponse:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT preset_label, fragment_weights, signal_penalties, signal_rewards,
               schema_version, updated_at
        FROM writing_account_prefs
        WHERE owner_user_id = $1
        """,
        owner_user_id,
    )
    stored = None
    if row is not None:
        stored = {
            "preset_label": row["preset_label"],
            "fragment_weights": row["fragment_weights"],
            "signal_penalties": row["signal_penalties"],
            "signal_rewards": row["signal_rewards"],
            "schema_version": row["schema_version"],
        }
    merged = merge_prefs(stored)
    return _row_to_response(row, merged=merged)


async def upsert_prefs(owner_user_id: UUID, body: UpdateWritingPrefsRequest) -> WritingPrefsResponse:
    existing = await get_prefs(owner_user_id)
    preset = body.preset_label or existing.preset_label
    if preset not in PRESET_LABELS:
        preset = "custom"

    if preset != "custom" and body.fragment_weights is None and body.signal_penalties is None:
        base = platform_prefs_payload(preset_label=preset)
        weights = base["fragment_weights"]
        penalties = base["signal_penalties"]
        rewards = base["signal_rewards"]
    else:
        weights = platform_fragment_weights()
        penalties = validate_signal_table(
            body.signal_penalties or existing.signal_penalties,
            field="signal_penalties",
        )
        rewards = validate_signal_table(
            body.signal_rewards or existing.signal_rewards,
            field="signal_rewards",
        )
        if body.preset_label is None and (
            body.signal_penalties is not None or body.signal_rewards is not None
        ):
            preset = "custom"

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO writing_account_prefs (
            owner_user_id, preset_label, fragment_weights, signal_penalties,
            signal_rewards, schema_version, updated_at
        )
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6, now())
        ON CONFLICT (owner_user_id) DO UPDATE SET
            preset_label = EXCLUDED.preset_label,
            fragment_weights = EXCLUDED.fragment_weights,
            signal_penalties = EXCLUDED.signal_penalties,
            signal_rewards = EXCLUDED.signal_rewards,
            schema_version = EXCLUDED.schema_version,
            updated_at = now()
        RETURNING preset_label, fragment_weights, signal_penalties, signal_rewards,
                  schema_version, updated_at
        """,
        owner_user_id,
        preset,
        json.dumps(weights),
        json.dumps(penalties),
        json.dumps(rewards),
        SCHEMA_VERSION,
    )
    merged = merge_prefs(
        {
            "preset_label": row["preset_label"],
            "fragment_weights": row["fragment_weights"],
            "signal_penalties": row["signal_penalties"],
            "signal_rewards": row["signal_rewards"],
            "schema_version": row["schema_version"],
        }
    )
    return _row_to_response(row, merged=merged)


async def reset_prefs(owner_user_id: UUID) -> WritingPrefsResponse:
    pool = await get_pool()
    await pool.execute(
        "DELETE FROM writing_account_prefs WHERE owner_user_id = $1",
        owner_user_id,
    )
    merged = platform_prefs_payload()
    return WritingPrefsResponse(
        preset_label=merged["preset_label"],
        fragment_weights=merged["fragment_weights"],
        signal_penalties=merged["signal_penalties"],
        signal_rewards=merged["signal_rewards"],
        exemplars=merged.get("exemplars") or {},
        schema_version=merged["schema_version"],
        updated_at=None,
        is_custom=False,
    )
