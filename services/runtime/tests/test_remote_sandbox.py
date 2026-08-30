"""Remote sandbox routing helpers."""

from __future__ import annotations

import pytest

from app.tools.core import remote_sandbox


def test_should_use_remote_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remote_sandbox.settings, "sandbox_plane_url", "http://sandbox:8004")
    monkeypatch.setattr(remote_sandbox.settings, "service_role", "orchestrator")
    assert remote_sandbox.should_use_remote_sandbox() is True
    monkeypatch.setattr(remote_sandbox.settings, "service_role", "sandbox")
    assert remote_sandbox.should_use_remote_sandbox() is False
    monkeypatch.setattr(remote_sandbox.settings, "service_role", "monolith")
    assert remote_sandbox.should_use_remote_sandbox() is False
