"""Admin model-provider routes must accept session actor (eval Basic bypass)."""

from __future__ import annotations

from pathlib import Path

from app.routers.admin import model_providers as routes
from app.services.end_user.auth import require_session_actor


def test_model_provider_routes_use_require_session_actor() -> None:
    """shared.10 / CI: admin Basic + ADMIN_SESSION_BYPASS must create providers.

    require_end_user alone rejects eval with ``End-user login required``.
    """
    assert routes.require_session_actor is require_session_actor
    source = Path(routes.__file__).read_text(encoding="utf-8")
    assert "require_session_actor" in source
    assert "require_end_user" not in source
