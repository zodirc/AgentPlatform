"""Admin UX signals HTTP API (docs/28 PX1d) — read-only, user-triggered."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.services.admin.auth import require_admin_or_end_user
from app.services.admin import ux_signals as svc
from app.services.end_user.auth import resolve_end_user

router = APIRouter(
    prefix="/admin/ux-signals",
    tags=["admin", "ux-signals"],
    dependencies=[Depends(require_admin_or_end_user)],
)


@router.get("")
async def get_ux_signals(
    request: Request,
    lookback_days: int = Query(14, ge=1, le=90),
    min_sample: int = Query(20, ge=1, le=1000),
    threshold_mult: float = Query(2.0, ge=1.0, le=10.0),
    day: str | None = Query(None, description="YYYY-MM-DD target day"),
    work_id: UUID | None = Query(None),
) -> dict:
    """Aggregate RejectRate / ReeditRate / CancelRate from turn_events.

    Scoped to the logged-in end user when present (multi-tenant isolation).
    Failures must not affect writing workbench — client treats errors as empty.
    """
    owner_id: UUID | None = None
    user = await resolve_end_user(request)
    if user is not None:
        owner_id = user.id
    return await svc.aggregate_ux_signals(
        lookback_days=lookback_days,
        min_sample=min_sample,
        threshold_mult=threshold_mult,
        work_id=work_id,
        owner_user_id=owner_id,
        target_day=day,
    )
