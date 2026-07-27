from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_DOCKER_CONTRACTS = Path("/app/packages/contracts")

# High-frequency streaming events: full jsonschema on every token burns CPU on the
# hot path (R3). Default = light structural check; set
# EVENT_PAYLOAD_VALIDATION_STRICT_DELTAS=true for CI / debug.
_HIGH_FREQ_EVENT_TYPES = frozenset(
    {
        "turn.token",
        "tool.delta",
        "turn.thinking.delta",
        "section.draft.delta",
    }
)


def _discover_repo_contracts_dir() -> Path | None:
    current = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = current / "packages" / "contracts"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _ensure_validate_payload_importable() -> None:
    for contracts_dir in (_DOCKER_CONTRACTS, _discover_repo_contracts_dir()):
        if contracts_dir is not None and contracts_dir.is_dir():
            path = str(contracts_dir)
            if path not in sys.path:
                sys.path.insert(0, path)
            return


_ensure_validate_payload_importable()

from validate_payload import (  # noqa: E402
    EventPayloadValidationError,
    validate_event_payload,
)

__all__ = ["EventPayloadValidationError", "validate_event_payload", "maybe_validate_event_payload"]


def _light_validate_high_freq(event_type: str, payload: dict[str, Any]) -> None:
    """Cheap shape check for streaming deltas — never run full jsonschema here."""
    if not isinstance(payload, dict):
        raise EventPayloadValidationError(event_type, ["payload must be an object"])
    if "delta" not in payload and "text" not in payload:
        raise EventPayloadValidationError(
            event_type,
            ["expected delta or text field for streaming payload"],
        )


def maybe_validate_event_payload(event_type: str, payload: dict[str, Any]) -> None:
    from app.settings import settings

    if not settings.event_payload_validation:
        return
    if (
        event_type in _HIGH_FREQ_EVENT_TYPES
        and not settings.event_payload_validation_strict_deltas
    ):
        _light_validate_high_freq(event_type, payload)
        return
    validate_event_payload(event_type, payload)
