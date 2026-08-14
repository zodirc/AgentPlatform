"""Inspect RAG chunks (Settings) — JSON backend, tenant-filtered."""

from __future__ import annotations

from uuid import uuid4

from app.retrieval.inspect_chunks import inspect_chunk_files, inspect_chunks_for_path
from app.retrieval.store import JsonSourceRetrievalStore
from app.services.workspace_scope import workspace_tenant_scope


def _store_with_chunks(tmp_path, chunks: list[dict]) -> JsonSourceRetrievalStore:
    path = tmp_path / "sources.json"
    store = JsonSourceRetrievalStore(path)
    store._index._data = {"version": 1, "files": {}, "chunks": chunks}
    store._loaded = True
    store._index._rebuild_chunk_lookup()
    return store


def test_inspect_chunks_separates_seed_and_local(tmp_path) -> None:
    wid = uuid4()
    store = _store_with_chunks(
        tmp_path,
        [
            {
                "chunk_id": "s1",
                "path": "sources/seed/legal.md",
                "text": "SEED CHUNK BODY",
                "section_title": "雇佣",
                "citation_id": "s1",
                "line_start": 1,
                "line_end": 8,
                "visibility": "seed",
            },
            {
                "chunk_id": "p1",
                "path": "sources/notes.md",
                "text": "LOCAL CHUNK BODY",
                "section_title": "笔记",
                "citation_id": "p1",
                "line_start": 3,
                "line_end": 12,
                "visibility": "private",
                "work_id": str(wid),
            },
            {
                "chunk_id": "other",
                "path": "sources/other.md",
                "text": "OTHER WORK",
                "visibility": "private",
                "work_id": str(uuid4()),
            },
        ],
    )
    with workspace_tenant_scope(
        work_id=str(wid),
        work_root=str(tmp_path),
        owner_user_id=str(uuid4()),
        visibility_seed=True,
    ):
        all_files = inspect_chunk_files(store=store)
        paths = {(f["path"], f["visibility"]) for f in all_files["files"]}
        assert ("sources/seed/legal.md", "seed") in paths
        assert ("sources/notes.md", "private") in paths
        assert all(f["path"] != "sources/other.md" for f in all_files["files"])

        seed_only = inspect_chunk_files(visibility="seed", store=store)
        assert [f["path"] for f in seed_only["files"]] == ["sources/seed/legal.md"]

        local_only = inspect_chunk_files(visibility="local", store=store)
        assert [f["path"] for f in local_only["files"]] == ["sources/notes.md"]

        detail = inspect_chunks_for_path("sources/seed/legal.md", store=store)
        assert detail["chunks"][0]["text"] == "SEED CHUNK BODY"
        assert detail["chunks"][0]["section_title"] == "雇佣"
        assert detail["chunks"][0]["line_start"] == 1


def test_inspect_chunks_hides_seed_when_visibility_off(tmp_path) -> None:
    wid = uuid4()
    store = _store_with_chunks(
        tmp_path,
        [
            {
                "chunk_id": "s1",
                "path": "sources/seed/legal.md",
                "text": "SEED",
                "visibility": "seed",
            },
            {
                "chunk_id": "p1",
                "path": "sources/notes.md",
                "text": "LOCAL",
                "visibility": "private",
                "work_id": str(wid),
            },
        ],
    )
    with workspace_tenant_scope(
        work_id=str(wid),
        work_root=str(tmp_path),
        owner_user_id=str(uuid4()),
        visibility_seed=False,
    ):
        files = inspect_chunk_files(store=store)
        assert [f["path"] for f in files["files"]] == ["sources/notes.md"]
        hidden = inspect_chunks_for_path("sources/seed/legal.md", store=store)
        assert hidden["chunks"] == []
