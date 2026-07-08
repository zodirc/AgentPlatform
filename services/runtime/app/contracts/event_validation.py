from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_DOCKER_CONTRACTS = Path("/app/packages/contracts")


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


def maybe_validate_event_payload(event_type: str, payload: dict[str, Any]) -> None:
    from app.settings import settings

    if not settings.event_payload_validation:
        return
    validate_event_payload(event_type, payload)
