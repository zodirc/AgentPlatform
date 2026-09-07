"""Single durable ``turn.cancelling`` payload — observed stop site, not a playbook."""

from __future__ import annotations

from typing import Any


def note_cancel(state: Any, *, force: bool = False, phase: str | None = None) -> None:
    """Mark TurnState cancelled; keep the first observed ``cancelled_at_phase``."""
    state.cancelled = True
    if force:
        state.cancel_force = True
    current = str(getattr(state, "cancelled_at_phase", None) or "").strip()
    if phase and not current:
        state.cancelled_at_phase = phase


def cancelling_payload(*, force: bool, cancelled_at_phase: str | None = None) -> dict[str, Any]:
    """One ``turn.cancelling`` body. Omit phase when the stop site was not observed."""
    out: dict[str, Any] = {"force": bool(force)}
    phase = (cancelled_at_phase or "").strip()
    if phase:
        out["cancelled_at_phase"] = phase
    return out
