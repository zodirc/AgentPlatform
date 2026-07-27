"""In-process idempotency replay for turn commands (review I11).

Runtime-side double execution is already guarded by the per-turn command
claim in the runtime turn_controller (review B3). This cache additionally
absorbs client/network retries at the API edge: a replayed
``(turn_id, client_request_id)`` returns the original response instead of
re-dispatching the command to runtime — which matters when the turn has
re-entered ``waiting_approval`` for a *different* tool call and a stale
retry would otherwise approve it.

The cache is per-replica by design; cross-replica retries still land on the
runtime claim + turn status checks.
"""
from __future__ import annotations

from uuid import UUID

from cachetools import TTLCache

_TTL_SECONDS = 600.0
_MAX_ENTRIES = 4096

_responses: TTLCache = TTLCache(maxsize=_MAX_ENTRIES, ttl=_TTL_SECONDS)


def replay(turn_id: UUID, client_request_id: UUID | None) -> dict | None:
    """Return the recorded response for a duplicate command, if any."""
    if client_request_id is None:
        return None
    return _responses.get((turn_id, client_request_id))


def remember(turn_id: UUID, client_request_id: UUID | None, response: dict) -> None:
    if client_request_id is None:
        return
    _responses[(turn_id, client_request_id)] = response
