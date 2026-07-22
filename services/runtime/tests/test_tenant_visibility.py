"""Tenant visibility filter (docs/27 MT3)."""

from __future__ import annotations

from pathlib import Path

from app.retrieval.tenant_visibility import filter_hits_for_tenant, path_visible_in_current_work
from app.tenant_context import bind_tenant_context, reset_tenant_context


def test_path_visible_seed_and_work(tmp_path: Path) -> None:
    work = tmp_path / "w1"
    work.mkdir()
    (work / "sources").mkdir()
    (work / "sources" / "note.md").write_text("x", encoding="utf-8")

    tokens = bind_tenant_context(work_root=str(work))
    try:
        assert path_visible_in_current_work("sources/note.md")
        assert path_visible_in_current_work("sources/seed/writing/a.md")
        assert not path_visible_in_current_work("../escape/secret.md")
        hits = [
            {"path": "sources/note.md", "score": 1.0},
            {"path": "../escape/secret.md", "score": 1.0},
            {"path": "sources/seed/x.md", "score": 0.5},
        ]
        kept = filter_hits_for_tenant(hits)
        assert [h["path"] for h in kept] == ["sources/note.md", "sources/seed/x.md"]
    finally:
        reset_tenant_context(tokens)
