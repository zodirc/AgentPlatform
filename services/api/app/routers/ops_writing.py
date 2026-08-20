"""Ops writing-signal lab — heuristic sandbox behind OPS_TEST_SECRET.

Not model-facing. Proxies runtime platform exemplars + persist=False scoring.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.services.command.runtime_client import RuntimeClient
from app.services.ops.auth import require_ops_eval_auth

router = APIRouter(
    prefix="/ops/writing",
    tags=["ops-writing"],
    dependencies=[Depends(require_ops_eval_auth)],
)


class ScoreBody(BaseModel):
    text: str | None = Field(default=None, max_length=50_000)
    fragment: str | None = None
    slug: str | None = Field(default=None, max_length=200)
    prefs: dict[str, Any] | None = None


def _proxy_runtime_error(exc: httpx.HTTPError) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        detail: Any
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text[:300]
        return HTTPException(status_code=exc.response.status_code, detail=detail)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="runtime unavailable",
    )


@router.get("/exemplars")
async def list_writing_exemplars() -> dict[str, Any]:
    try:
        return await RuntimeClient().writing_exemplars()
    except httpx.HTTPError as exc:
        raise _proxy_runtime_error(exc) from exc


@router.post("/score")
async def score_writing_text(body: ScoreBody) -> dict[str, Any]:
    try:
        return await RuntimeClient().writing_score(
            text=body.text,
            fragment=body.fragment,
            slug=body.slug,
            prefs=body.prefs,
        )
    except httpx.HTTPError as exc:
        raise _proxy_runtime_error(exc) from exc
