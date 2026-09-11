from __future__ import annotations

from pathlib import Path

from app.writing.ops_snapshot import regime_ops_snapshot, work_alignment_curve
from app.writing.taste import append_taste_mark


def test_alignment_not_ready_under_four_samples(tmp_path: Path) -> None:
    curve = work_alignment_curve(workspace_root=tmp_path)
    assert curve["ready"] is False
    assert curve["points"] == []


def test_regime_snapshot_lists_current_default(tmp_path: Path, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    snap = regime_ops_snapshot(workspace_root=tmp_path)
    assert snap["ok"] is True
    assert snap["regime"]["value"] in {"author", "strict"}
    assert "alignment" in snap
    assert "reports" in snap
    assert "metrics" in snap
    assert snap["metrics"]["taste"]["n"] == 0


def test_offline_metrics_counts_taste(tmp_path: Path) -> None:
    from app.writing.ops_snapshot import collect_offline_metrics

    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "manuscript.md").write_text(
        "# 第一章\n" + ("码头。" * 50),
        encoding="utf-8",
    )
    append_taste_mark(
        section_id="ch1",
        kind="ai",
        excerpt="码头。码头。码头。",
        workspace_root=tmp_path,
    )
    metrics = collect_offline_metrics(workspace_root=tmp_path)
    assert metrics["chapter_count"] == 1
    assert metrics["taste"]["counts"]["ai"] == 1
    assert metrics["taste"]["per_1k_chars"]["ai"] > 0


def test_alignment_ready_after_four_yes_marks(tmp_path: Path) -> None:
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "manuscript.md").write_text(
        "# 第一章\n她没接话，把秤砣放回去。河风从门缝进来。\n",
        encoding="utf-8",
    )
    for i in range(4):
        append_taste_mark(
            section_id="ch1",
            kind="yes",
            excerpt=f"正例{i} 秤砣放回去。河风从门缝进来。",
            workspace_root=tmp_path,
        )
    curve = work_alignment_curve(workspace_root=tmp_path)
    assert curve["ready"] is True
    assert curve["points"]
