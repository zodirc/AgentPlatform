"""Internal HTTP for the Ops writing-signal lab (not model-facing)."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.settings import settings
from app.writing.signals.assemble import WritingLabError, score_writing_lab
from app.writing.signals.bank import exemplar_lab_payload, iter_platform_exemplars

router = APIRouter(prefix="/internal/writing", tags=["writing-lab"])


def verify_internal_token(x_internal_token: str = Header(...)) -> None:
    if not hmac.compare_digest(x_internal_token, settings.internal_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


class ScoreBody(BaseModel):
    text: str | None = Field(default=None, max_length=50_000)
    fragment: str | None = None
    slug: str | None = Field(default=None, max_length=200)
    prefs: dict[str, Any] | None = None


@router.get("/exemplars")
async def list_writing_exemplars(_: None = Depends(verify_internal_token)) -> dict[str, Any]:
    items = [exemplar_lab_payload(sample) for sample in iter_platform_exemplars()]
    from app.writing.signals.prefs_store import platform_prefs_payload

    return {
        "exemplars": items,
        "count": len(items),
        "prefs": platform_prefs_payload(),
    }


@router.post("/score")
async def score_writing_text(
    body: ScoreBody,
    _: None = Depends(verify_internal_token),
) -> dict[str, Any]:
    try:
        return await score_writing_lab(
            text=body.text,
            fragment=body.fragment,
            slug=body.slug,
            prefs_overlay=body.prefs,
        )
    except WritingLabError as exc:
        code = status.HTTP_404_NOT_FOUND if exc.code == "exemplar_not_found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message}) from exc
