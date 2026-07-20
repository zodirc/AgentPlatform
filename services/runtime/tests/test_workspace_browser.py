import pytest

from app.services.workspace_browser import (
    delete_workspace_paths,
    safe_source_filename,
    source_rel_path,
    sources_index_status,
    sync_sources_index_safe,
    upload_source_file,
)


def test_safe_source_filename_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        safe_source_filename("../evil.md")
    assert safe_source_filename("ref-a.md") == "ref-a.md"


def test_source_rel_path() -> None:
    assert source_rel_path("notes.md") == "sources/notes.md"


@pytest.mark.asyncio
async def test_delete_workspace_paths_removes_files_and_dirs(workspace) -> None:
    nested = workspace / "exports" / "drafts"
    nested.mkdir(parents=True)
    (nested / "one.md").write_text("one", encoding="utf-8")
    (workspace / "notes.md").write_text("note", encoding="utf-8")

    result = await delete_workspace_paths(["exports/drafts/one.md", "notes.md"])

    assert set(result["deleted"]) == {"exports/drafts/one.md", "notes.md"}
    assert result["failed"] == []
    assert not (nested / "one.md").exists()
    assert not (workspace / "notes.md").exists()


@pytest.mark.asyncio
async def test_delete_workspace_paths_skips_nested_when_parent_deleted(workspace) -> None:
    folder = workspace / "sections" / "ch1"
    folder.mkdir(parents=True)
    (folder / "body.md").write_text("body", encoding="utf-8")

    result = await delete_workspace_paths(["sections/ch1", "sections/ch1/body.md"])

    assert result["deleted"] == ["sections/ch1"]
    assert not folder.exists()


@pytest.mark.asyncio
async def test_delete_workspace_paths_rejects_workspace_root(workspace) -> None:
    with pytest.raises(ValueError, match="workspace root"):
        await delete_workspace_paths(["."])


@pytest.mark.asyncio
async def test_upload_source_file_writes_pending_index(workspace, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(workspace / "data"))
    result = await upload_source_file(
        filename="my-ref.md",
        content="# Title\nSome reference content.\n",
    )
    assert result["path"] == "sources/my-ref.md"
    assert (workspace / "sources" / "my-ref.md").is_file()
    assert result.get("index", {}).get("status") == "pending"
    status = sources_index_status(path="sources/my-ref.md")
    assert status["status"] == "building"
    assert status["plane"] == "ingestion"
    assert status["effect_ready"] is False
    assert "retrieval-bench-prod" in (status.get("hint") or "")


@pytest.mark.asyncio
async def test_upload_source_file_can_sync_inline(workspace, monkeypatch) -> None:
    from app.retrieval.embedder import reset_embedder_cache
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(workspace / "data"))
    monkeypatch.setattr(settings, "retrieval_backend", "json")
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    reset_embedder_cache()
    result = await upload_source_file(
        filename="my-ref-sync.md",
        content="# Title\nSome reference content.\n",
        sync_index=True,
    )
    assert result["path"] == "sources/my-ref-sync.md"
    assert result.get("index", {}).get("chunks", 0) >= 1
    assert result.get("index", {}).get("status") == "ready"
    status = sources_index_status(path="sources/my-ref-sync.md")
    assert status["status"] == "ready"
    assert status["path_current"] is True
    assert status["plane"] == "ingestion"
    assert status["ingestion_ready"] is True
    assert status["effect_ready"] is False


@pytest.mark.asyncio
async def test_sync_sources_index_safe_marks_ready(workspace, monkeypatch) -> None:
    from app.retrieval.embedder import reset_embedder_cache
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(workspace / "data"))
    monkeypatch.setattr(settings, "retrieval_backend", "json")
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    reset_embedder_cache()
    await upload_source_file(filename="bg.md", content="background index\n")
    result = await sync_sources_index_safe(path="sources/bg.md")
    assert result["status"] == "ready"
    status = sources_index_status(path="sources/bg.md")
    assert status["path_current"] is True
    assert status["chunks"] >= 1


@pytest.mark.asyncio
async def test_sync_sources_index_safe_marks_error(workspace, monkeypatch) -> None:
    from app.settings import settings
    from app.tools.core import tools

    async def fail_sync() -> dict:
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(settings, "data_dir", str(workspace / "data"))
    monkeypatch.setattr(tools, "sync_sources_index", fail_sync)
    await upload_source_file(filename="failed.md", content="cannot index yet\n")

    result = await sync_sources_index_safe(path="sources/failed.md")

    assert result == {"status": "error", "error": "embedding unavailable"}
    status = sources_index_status(path="sources/failed.md")
    assert status["status"] == "error"
    assert status["error"] == "embedding unavailable"
    assert status["path_current"] is False

