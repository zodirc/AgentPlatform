"""One approval covers one call: tool, arguments, and the pinned policy version."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

# P0 has no policy service yet. Bumping this constant invalidates in-flight grants.
POLICY_VERSION = "p1"


def canonical_args_hash(arguments: dict[str, Any] | None) -> str:
    """Stable sha256 of the arguments the user is being asked to approve."""
    from app.policy.snapshot import canonicalize_arguments

    payload = json.dumps(
        canonicalize_arguments(arguments),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalGrant:
    """Proof that this exact call was approved under the current policy version."""

    tool_name: str
    tool_call_id: str
    args_hash: str
    policy_version: str
    approval_id: str = ""
    expires_at: float | None = None
    approver_user_id: str = ""
    window_taint: str = ""


def grant_matches(
    grant: ApprovalGrant | None,
    *,
    tool_name: str,
    tool_call_id: str,
    arguments: dict[str, Any] | None,
) -> bool:
    """True only when the grant is for this call, these arguments, and this policy."""
    if grant is None:
        return False
    pinned = str(getattr(grant, "policy_version", "") or "")
    if pinned != POLICY_VERSION:
        return False
    expires_at = getattr(grant, "expires_at", None)
    if expires_at is not None and time.time() > float(expires_at):
        return False
    if grant.tool_name != tool_name or grant.tool_call_id != tool_call_id:
        return False
    if not grant.args_hash:
        return False
    return grant.args_hash == canonical_args_hash(arguments)
