import pytest

from app.services.workspace_browser import (
    safe_source_filename,
    source_rel_path,
    upload_source_file,
)


def test_safe_source_filename_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        safe_source_filename("../evil.md")
    assert safe_source_filename("ref-a.md") == "ref-a.md"


def test_source_rel_path() -> None:
    assert source_rel_path("notes.md") == "sources/notes.md"


@pytest.mark.asyncio
async def test_upload_source_file_writes_and_indexes(workspace, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(workspace / "data"))
    result = await upload_source_file(
        filename="my-ref.md",
        content="# Title\nSome reference content.\n",
    )
    assert result["path"] == "sources/my-ref.md"
    assert (workspace / "sources" / "my-ref.md").is_file()
    assert result.get("index", {}).get("chunks", 0) >= 1
