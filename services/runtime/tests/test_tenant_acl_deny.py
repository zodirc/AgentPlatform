"""Cross-Work retrieval deny (docs/27 MT5c)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.retrieval.tenant_visibility import (
    display_path_from_index,
    filter_hits_for_tenant,
    hit_visible_for_tenant,
    index_storage_path,
    path_visible_in_current_work,
)
from app.tenant_context import (
    bind_tenant_context,
    current_tenant_context,
    current_visibility_seed,
    reset_tenant_context,
)


def test_index_storage_path_scopes_private() -> None:
    wid = str(uuid4())
    assert index_storage_path("sources/a.md", work_id=wid, visibility="private") == (
        f"__work__/{wid}/sources/a.md"
    )
    assert index_storage_path("sources/seed/x.md", work_id=None, visibility="seed") == (
        "sources/seed/x.md"
    )
    assert (
        display_path_from_index(f"__work__/{wid}/sources/a.md") == "sources/a.md"
    )


def test_tenant_context_personal_defaults(tmp_path: Path) -> None:
    owner = uuid4()
    work = uuid4()
    tokens = bind_tenant_context(
        work_root=str(tmp_path),
        work_id=work,
        owner_user_id=owner,
    )
    try:
        ctx = current_tenant_context()
        assert ctx.tenant_id == owner
        assert ctx.principal_id == owner
        assert ctx.work_id == work
        assert ctx.visibility_seed is True
        assert ctx.resolved_at
        assert current_visibility_seed() is True
    finally:
        reset_tenant_context(tokens)


def test_filter_denies_other_work_metadata(tmp_path: Path) -> None:
    work_a = tmp_path / "a"
    work_a.mkdir()
    (work_a / "sources").mkdir()
    (work_a / "sources" / "note.md").write_text("own", encoding="utf-8")

    wid_a = uuid4()
    wid_b = uuid4()
    tokens = bind_tenant_context(
        work_root=str(work_a),
        work_id=wid_a,
        owner_user_id=uuid4(),
    )
    try:
        assert path_visible_in_current_work("sources/note.md")
        own = {
            "path": "sources/note.md",
            "work_id": str(wid_a),
            "visibility": "private",
        }
        other = {
            "path": "sources/note.md",
            "work_id": str(wid_b),
            "visibility": "private",
            "excerpt": "TENANT_DENY_SECRET_OTHER_WORK",
        }
        seed = {
            "path": "sources/seed/x.md",
            "visibility": "seed",
        }
        orphan_null = {
            "path": "sources/note.md",
            "work_id": None,
            "visibility": "private",
            "excerpt": "ORPHAN_NULL_WORK",
        }
        assert hit_visible_for_tenant(own)
        assert not hit_visible_for_tenant(other)
        assert hit_visible_for_tenant(seed)
        # Path alone is not enough when metadata says another / missing work.
        assert not hit_visible_for_tenant(other)
        kept = filter_hits_for_tenant([own, other, seed, orphan_null])
        assert own in kept
        assert seed in kept
        assert other not in kept
        assert orphan_null not in kept
        assert all(h.get("excerpt") != "TENANT_DENY_SECRET_OTHER_WORK" for h in kept)
        assert all(h.get("excerpt") != "ORPHAN_NULL_WORK" for h in kept)
    finally:
        reset_tenant_context(tokens)


def test_visibility_seed_off_hides_seed(tmp_path: Path) -> None:
    tokens = bind_tenant_context(
        work_root=str(tmp_path),
        work_id=uuid4(),
        visibility_seed=False,
    )
    try:
        assert not path_visible_in_current_work("sources/seed/a.md")
        assert not hit_visible_for_tenant(
            {"path": "sources/seed/a.md", "visibility": "seed"}
        )
    finally:
        reset_tenant_context(tokens)


def test_bm25_cache_filters_by_work() -> None:
    """Pgvector BM25 lane must not rank other Work chunks (MT5c)."""
    from uuid import UUID

    from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

    store = PgvectorSourceRetrievalStore.__new__(PgvectorSourceRetrievalStore)
    wid_a = uuid4()
    wid_b = uuid4()
    store._chunk_cache = [
        {
            "chunk_id": "a1",
            "path": "sources/a.md",
            "text": "alpha secret-a",
            "citation_id": "c1",
            "section_title": "",
            "line_start": 1,
            "line_end": 1,
            "work_id": str(wid_a),
            "visibility": "private",
        },
        {
            "chunk_id": "b1",
            "path": "sources/b.md",
            "text": "beta secret-b TENANT_DENY_SECRET_B",
            "citation_id": "c2",
            "section_title": "",
            "line_start": 1,
            "line_end": 1,
            "work_id": str(wid_b),
            "visibility": "private",
        },
        {
            "chunk_id": "s1",
            "path": "sources/seed/s.md",
            "text": "seed shared",
            "citation_id": "c3",
            "section_title": "",
            "line_start": 1,
            "line_end": 1,
            "work_id": None,
            "visibility": "seed",
        },
    ]
    tokens = bind_tenant_context(
        work_root="/tmp/work-a",
        work_id=wid_a,
        owner_user_id=uuid4(),
    )
    try:
        visible = store._bm25_visible_chunks()
        ids = {c["chunk_id"] for c in visible}
        assert ids == {"a1", "s1"}
        hits = store.search_bm25("TENANT_DENY_SECRET_B", limit=10)
        assert all("TENANT_DENY_SECRET_B" not in h.excerpt for h in hits)
    finally:
        reset_tenant_context(tokens)
