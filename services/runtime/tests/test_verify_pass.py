from __future__ import annotations

from pathlib import Path

from app.controller.input_compiler import should_query
from app.controller.verify_pass import run_verify_pass


def test_should_query_verify_short_circuits() -> None:
    result = should_query("/verify", has_model_key=True)
    assert result.should_query is False
    assert result.slash_command == "verify"


def test_run_verify_pass_writes_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.controller.verify_pass.settings.workspace_root", str(tmp_path))
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "a.md").write_text("See cite:missing-source here.\n", encoding="utf-8")
    (tmp_path / "sources").mkdir()
    result = run_verify_pass(session_id="s1")
    assert result["mutated_draft"] is False
    assert result["checked"] >= 1
    assert result["invalid"] >= 1
    report = tmp_path / result["report_path"]
    assert report.is_file()
