"""Shared API test fixtures.

Local `.env` often sets ``OPS_TEST_SECRET``, which makes ``app.main.lifespan``
run ops orphan reclaim on startup. Those paths call ``get_pool()`` / real asyncpg
even when tests patch ``app.main.init_pool``, so unit suites blow up with
``socket.gaierror: postgres`` on the host. Stub them for every test.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _stub_ops_startup_reconcile():
    with (
        patch(
            "app.services.ops.runs.reconcile_orphaned_runs",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "app.services.ops.official_runner.reclaim_official_orphans_from_db",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        yield
