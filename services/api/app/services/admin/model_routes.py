"""用户级窄角色模型路由；没有配置时继承当前 active profile。"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.db.pool import get_pool

_ROUTES = {("writing", "book_candidates")}


class UpdateModelRouteRequest(BaseModel):
    profile_id: UUID | None


class ModelRoutePreference(BaseModel):
    scenario_id: str
    role: str
    profile_id: UUID | None


def _validate_route(scenario_id: str, role: str) -> tuple[str, str]:
    key = ((scenario_id or "").strip(), (role or "").strip())
    if key not in _ROUTES:
        raise ValueError("unsupported_model_route")
    return key


async def get_route(
    *,
    owner_user_id: UUID,
    scenario_id: str,
    role: str,
) -> ModelRoutePreference:
    scenario_id, role = _validate_route(scenario_id, role)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT profile_id
        FROM model_route_preferences
        WHERE owner_user_id = $1 AND scenario_id = $2 AND role = $3
        """,
        owner_user_id,
        scenario_id,
        role,
    )
    return ModelRoutePreference(
        scenario_id=scenario_id,
        role=role,
        profile_id=row["profile_id"] if row is not None else None,
    )


async def set_route(
    *,
    owner_user_id: UUID,
    scenario_id: str,
    role: str,
    profile_id: UUID | None,
) -> ModelRoutePreference:
    scenario_id, role = _validate_route(scenario_id, role)
    pool = await get_pool()
    if profile_id is None:
        await pool.execute(
            """
            DELETE FROM model_route_preferences
            WHERE owner_user_id = $1 AND scenario_id = $2 AND role = $3
            """,
            owner_user_id,
            scenario_id,
            role,
        )
        return ModelRoutePreference(
            scenario_id=scenario_id,
            role=role,
            profile_id=None,
        )
    row = await pool.fetchrow(
        """
        INSERT INTO model_route_preferences (
            owner_user_id, scenario_id, role, profile_id, updated_at
        )
        SELECT $1, $2, $3, p.id, now()
        FROM model_provider_profiles p
        WHERE p.id = $4 AND p.owner_user_id = $1
        ON CONFLICT (owner_user_id, scenario_id, role)
        DO UPDATE SET profile_id = EXCLUDED.profile_id, updated_at = now()
        RETURNING profile_id
        """,
        owner_user_id,
        scenario_id,
        role,
        profile_id,
    )
    if row is None:
        raise ValueError("model_profile_not_found")
    return ModelRoutePreference(
        scenario_id=scenario_id,
        role=role,
        profile_id=row["profile_id"],
    )
