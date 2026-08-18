from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.structural.pool import get_session, reap_idle, reset_pool_for_tests, shutdown_pool


class _FakeLsp:
    def __init__(self) -> None:
        self.healthy = True
        self.shutdown_calls = 0

    async def start(self, *, timeout_s: float) -> None:
        del timeout_s

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.healthy = False


@pytest.mark.asyncio
async def test_reap_idle_drops_stale_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reset_pool_for_tests()
    fake = _FakeLsp()

    async def _start(self, *, timeout_s: float) -> None:  # noqa: ANN001
        del timeout_s

    monkeypatch.setattr(
        "app.structural.pool.discover_python_provider",
        lambda: MagicMock(name="jedi"),
    )
    monkeypatch.setattr("app.structural.pool.LspSession", lambda **kwargs: fake)
    session, cold, reason = await get_session(tmp_path, timeout_s=1.0)
    assert session is fake
    assert cold is True
    assert reason is None
    dropped = await reap_idle(ttl_s=-1.0)
    assert dropped == 1
    assert fake.shutdown_calls == 1
    reset_pool_for_tests()


@pytest.mark.asyncio
async def test_shutdown_pool_drops_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reset_pool_for_tests()
    fake = _FakeLsp()
    monkeypatch.setattr(
        "app.structural.pool.discover_python_provider",
        lambda: MagicMock(name="jedi"),
    )
    monkeypatch.setattr("app.structural.pool.LspSession", lambda **kwargs: fake)
    await get_session(tmp_path, timeout_s=1.0)
    dropped = await shutdown_pool()
    assert dropped == 1
    assert fake.shutdown_calls == 1
