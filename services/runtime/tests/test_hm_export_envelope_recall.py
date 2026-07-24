"""HM4 / HM7 / HM9 unit coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.controller.input_compiler import InputCompiler
from app.controller.verify_pass import scan_text_citations
from app.observability.model_envelope import envelope_content_hash, should_store_full_envelope
from app.settings import settings
from app.tools.core import tools as core


def test_envelope_hash_stable() -> None:
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    tools = [{"name": "read_file", "description": "x"}]
    a = envelope_content_hash(messages, tools)
    b = envelope_content_hash(messages, tools)
    assert a == b
    assert len(a) == 64


def test_envelope_full_on_high_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.observability.model_envelope.settings.model_envelope_debug", False)
    monkeypatch.setattr(
        "app.observability.model_envelope.settings.model_envelope_on_high_fill", True
    )
    monkeypatch.setattr(
        "app.observability.model_envelope.settings.context_fill_autocompact", 0.95
    )
    monkeypatch.setattr(
        "app.observability.model_envelope.settings.model_envelope_sample_rate", 0.0
    )
    assert should_store_full_envelope(fill_ratio=0.99) is True
    assert should_store_full_envelope(fill_ratio=0.1) is False


def test_recall_hint_triggers_and_skips() -> None:
    compiler = InputCompiler()
    hit = compiler.compile("还记得上次说的大纲吗？")
    assert hit.metadata.get("recall_hint") is True
    miss = compiler.compile("请继续写下一章")
    assert not miss.metadata.get("recall_hint")


@pytest.mark.asyncio
async def test_export_verify_block(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "writing_export_verify_mode", "block")
    sections = workspace / "sections"
    sections.mkdir(parents=True, exist_ok=True)
    (sections / "01.md").write_text(
        "# One\n\nSee sources/missing_fact.md\n",
        encoding="utf-8",
    )
    (workspace / "outline.md").write_text("# Outline\n", encoding="utf-8")
    result = await core.export_document(
        output_path="exports/out.md",
        section_ids=["01"],
        source="confirmed",
        profile="none",
    )
    assert result.get("delivery_status") == "failed", result
    assert result.get("delivery_issues")
    assert any("missing_path" in str(i) for i in (result.get("delivery_issues") or []))
    assert not (workspace / "exports" / "out.md").exists()


@pytest.mark.asyncio
async def test_export_verify_warn_marks(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "writing_export_verify_mode", "warn")
    sections = workspace / "sections"
    sections.mkdir(parents=True, exist_ok=True)
    (sections / "01.md").write_text(
        "# One\n\nPath sources/nope.md is missing.\n",
        encoding="utf-8",
    )
    (workspace / "outline.md").write_text("# Outline\n", encoding="utf-8")
    result = await core.export_document(
        output_path="exports/out.md",
        section_ids=["01"],
        source="confirmed",
        profile="none",
    )
    assert (workspace / "exports" / "out.md").exists(), result
    assert result.get("delivery_status") == "warning", result
    issues = result.get("delivery_issues") or []
    assert any("missing_path" in str(i) for i in issues)


def test_scan_text_citations_reports_missing(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.controller.verify_pass.settings.workspace_root", str(workspace))
    issues = scan_text_citations("see sources/ghost.md")
    assert any("missing_path" in i for i in issues)
