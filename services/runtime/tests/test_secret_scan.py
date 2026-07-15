from __future__ import annotations

from pathlib import Path

import pytest

from app.privacy.secret_scan import gate_write_content, scan_text_for_secrets
from app.tools.core import tools as core


def test_scan_detects_aws_and_private_key() -> None:
    text = "key AKIAIOSFODNN7EXAMPLE and -----BEGIN RSA PRIVATE KEY-----"
    result = scan_text_for_secrets(text, timeout_ms=50.0)
    assert not result.timed_out
    assert "aws_access_key" in result.findings
    assert "private_key" in result.findings
    assert result.blocked


def test_scan_allows_normal_prose_under_budget() -> None:
    text = "张白鹿在写调研报告，引用公开论文 DOI:10.1000/xyz。" * 200
    result = scan_text_for_secrets(text, timeout_ms=50.0)
    assert not result.timed_out
    assert result.findings == ()
    assert result.elapsed_ms < 50.0


def test_scan_timeout_yields_allow_signal() -> None:
    # Zero budget forces timeout path without needing huge payload.
    result = scan_text_for_secrets("AKIAIOSFODNN7EXAMPLE", timeout_ms=0.0)
    assert result.timed_out


@pytest.mark.asyncio
async def test_write_file_blocks_secret(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.settings.settings.secret_scan_enabled", True)
    monkeypatch.setattr("app.settings.settings.secret_scan_timeout_ms", 50.0)
    result = await core.write_file("leak.txt", "token=AKIAIOSFODNN7EXAMPLE")
    assert result["status"] == "blocked"
    assert "aws_access_key" in result["secret_findings"]
    assert not (workspace / "leak.txt").exists()


@pytest.mark.asyncio
async def test_write_file_allows_clean(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.settings.settings.secret_scan_enabled", True)
    result = await core.write_file("ok.txt", "hello draft")
    assert result["status"] == "written"
    assert (workspace / "ok.txt").read_text() == "hello draft"


def test_gate_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.settings.settings.secret_scan_enabled", False)
    assert gate_write_content("AKIAIOSFODNN7EXAMPLE", path="x") is None
