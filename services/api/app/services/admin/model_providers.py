from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.pool import get_pool
from app.services.admin.crypto import encrypt_api_key, mask_api_key


class CreateModelProviderRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=32)
    model_name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1)
    base_url: str | None = None
    activate: bool = True


class UpdateModelProviderRequest(BaseModel):
    label: str | None = None
    provider: str | None = None
    model_name: str | None = None
    api_key: str | None = None
    base_url: str | None = None


class ModelProviderProfile(BaseModel):
    id: UUID
    label: str
    provider: str
    model_name: str
    base_url: str | None
    is_active: bool
    api_key_hint: str
    config_version: int
    updated_at: datetime


def _row_to_profile(row, *, hint: str) -> ModelProviderProfile:
    return ModelProviderProfile(
        id=row["id"],
        label=row["label"],
        provider=row["provider"],
        model_name=row["model_name"],
        base_url=row["base_url"],
        is_active=row["is_active"],
        api_key_hint=hint,
        config_version=row["config_version"],
        updated_at=row["updated_at"],
    )


async def list_profiles() -> list[ModelProviderProfile]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, label, provider, model_name, base_url, is_active,
               config_version, updated_at, api_key_ciphertext
        FROM model_provider_profiles
        ORDER BY updated_at DESC
        """
    )
    profiles = []
    for row in rows:
        hint = "••••"
        try:
            from app.services.admin.crypto import decrypt_api_key

            hint = mask_api_key(decrypt_api_key(row["api_key_ciphertext"]))
        except Exception:
            pass
        profiles.append(_row_to_profile(row, hint=hint))
    return profiles


async def create_profile(body: CreateModelProviderRequest) -> ModelProviderProfile:
    pool = await get_pool()
    ciphertext = encrypt_api_key(body.api_key)
    async with pool.acquire() as conn:
        async with conn.transaction():
            if body.activate:
                await conn.execute(
                    "UPDATE model_provider_profiles SET is_active = false WHERE is_active = true"
                )
            row = await conn.fetchrow(
                """
                INSERT INTO model_provider_profiles (
                    label, provider, model_name, api_key_ciphertext, base_url, is_active
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, label, provider, model_name, base_url, is_active,
                          config_version, updated_at
                """,
                body.label,
                body.provider,
                body.model_name,
                ciphertext,
                body.base_url,
                body.activate,
            )
            if row is not None:
                await _notify_provider_config(conn, row["id"])
    return _row_to_profile(row, hint=mask_api_key(body.api_key))


async def _notify_provider_config(conn, profile_id: UUID) -> None:
    await conn.execute(
        "SELECT pg_notify('provider_config_channel', $1)",
        str(profile_id),
    )


async def update_profile(
    profile_id: UUID,
    body: UpdateModelProviderRequest,
) -> ModelProviderProfile | None:
    pool = await get_pool()
    fields: list[str] = []
    values: list[object] = []
    hint = "••••"

    if body.label is not None:
        fields.append(f"label = ${len(values) + 1}")
        values.append(body.label)
    if body.provider is not None:
        fields.append(f"provider = ${len(values) + 1}")
        values.append(body.provider)
    if body.model_name is not None:
        fields.append(f"model_name = ${len(values) + 1}")
        values.append(body.model_name)
    if body.base_url is not None:
        fields.append(f"base_url = ${len(values) + 1}")
        values.append(body.base_url)
    if body.api_key is not None:
        fields.append(f"api_key_ciphertext = ${len(values) + 1}")
        values.append(encrypt_api_key(body.api_key))
        hint = mask_api_key(body.api_key)

    if not fields:
        row = await pool.fetchrow(
            """
            SELECT id, label, provider, model_name, base_url, is_active,
                   config_version, updated_at, api_key_ciphertext
            FROM model_provider_profiles WHERE id = $1
            """,
            profile_id,
        )
        if row is None:
            return None
        try:
            from app.services.admin.crypto import decrypt_api_key

            hint = mask_api_key(decrypt_api_key(row["api_key_ciphertext"]))
        except Exception:
            pass
        return _row_to_profile(row, hint=hint)

    fields.append("config_version = config_version + 1")
    fields.append("updated_at = now()")
    values.append(profile_id)
    sql = f"""
        UPDATE model_provider_profiles
        SET {", ".join(fields)}
        WHERE id = ${len(values)}
        RETURNING id, label, provider, model_name, base_url, is_active,
                  config_version, updated_at, api_key_ciphertext
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(sql, *values)
            if row is not None:
                await _notify_provider_config(conn, profile_id)
    if row is None:
        return None
    if body.api_key is None:
        try:
            from app.services.admin.crypto import decrypt_api_key

            hint = mask_api_key(decrypt_api_key(row["api_key_ciphertext"]))
        except Exception:
            pass
    return _row_to_profile(row, hint=hint)


async def activate_profile(profile_id: UUID) -> ModelProviderProfile | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE model_provider_profiles SET is_active = false WHERE is_active = true"
            )
            row = await conn.fetchrow(
                """
                UPDATE model_provider_profiles
                SET is_active = true, config_version = config_version + 1, updated_at = now()
                WHERE id = $1
                RETURNING id, label, provider, model_name, base_url, is_active,
                          config_version, updated_at, api_key_ciphertext
                """,
                profile_id,
            )
            if row is not None:
                await _notify_provider_config(conn, profile_id)
    if row is None:
        return None
    try:
        from app.services.admin.crypto import decrypt_api_key

        hint = mask_api_key(decrypt_api_key(row["api_key_ciphertext"]))
    except Exception:
        hint = "••••"
    return _row_to_profile(row, hint=hint)


async def delete_profile(profile_id: UUID) -> bool:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT is_active FROM model_provider_profiles WHERE id = $1",
        profile_id,
    )
    if row is None:
        return False
    if row["is_active"]:
        raise ValueError("Cannot delete active profile")
    result = await pool.execute(
        "DELETE FROM model_provider_profiles WHERE id = $1",
        profile_id,
    )
    return result.endswith("1")
