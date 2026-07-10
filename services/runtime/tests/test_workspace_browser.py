import pytest

from app.services.workspace_browser import (
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


@pytest.mark.asyncio
async def test_upload_source_file_can_sync_inline(workspace, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(workspace / "data"))
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


@pytest.mark.asyncio
async def test_sync_sources_index_safe_marks_ready(workspace, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(workspace / "data"))
    await upload_source_file(filename="bg.md", content="background index\n")
    result = await sync_sources_index_safe(path="sources/bg.md")
    assert result["status"] == "ready"
    status = sources_index_status(path="sources/bg.md")
    assert status["path_current"] is True
    assert status["chunks"] >= 1

