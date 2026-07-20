from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.settings import settings
from app.tools.core import tools as core


@pytest.mark.asyncio
async def test_read_file_and_list_dir(workspace: Path) -> None:
    (workspace / "a.txt").write_text("content", encoding="utf-8")
    (workspace / "sub").mkdir()

    missing = await core.read_file("missing.txt")
    assert missing["error"]

    read = await core.read_file("a.txt")
    assert read["content"] == "content"

    listed = await core.list_dir(".")
    assert "a.txt" in listed["entries"]
    assert "sub/" in listed["entries"]


@pytest.mark.asyncio
async def test_read_file_truncates_large_content(workspace: Path) -> None:
    (workspace / "big.txt").write_text("x" * 40_000, encoding="utf-8")
    result = await core.read_file("big.txt")
    assert "truncated" in result["content"]


@pytest.mark.asyncio
async def test_resolve_path_rejects_escape(workspace: Path) -> None:
    with pytest.raises(PermissionError):
        await core.read_file("/etc/passwd")


@pytest.mark.asyncio
async def test_propose_and_apply_patch(workspace: Path) -> None:
    proposed = await core.propose_patch("f.md", "old", "new", summary="s")
    assert proposed["status"] == "pending"
    assert proposed["patch_id"].startswith("patch-")

    (workspace / "f.md").write_text("hello", encoding="utf-8")
    applied = await core.apply_patch("f.md", "hello-world", force_full_replace=True)
    assert applied["status"] == "applied"
    assert (workspace / "f.md").read_text(encoding="utf-8") == "hello-world"


@pytest.mark.asyncio
async def test_apply_patch_surgical_replace(workspace: Path) -> None:
    (workspace / "outline.md").write_text(
        "# Vol1\nAAA\n# Vol2\nBBB\n# Vol3\nCCC\n",
        encoding="utf-8",
    )
    applied = await core.apply_patch(
        "outline.md",
        new_text="# Vol2\nBBB-fixed\n",
        old_text="# Vol2\nBBB\n",
    )
    assert applied["status"] == "applied"
    assert applied["mode"] == "surgical"
    text = (workspace / "outline.md").read_text(encoding="utf-8")
    assert text == "# Vol1\nAAA\n# Vol2\nBBB-fixed\n# Vol3\nCCC\n"


@pytest.mark.asyncio
async def test_apply_patch_refuses_span_as_full_file(workspace: Path) -> None:
    (workspace / "big.md").write_text("x" * 2000, encoding="utf-8")
    refused = await core.apply_patch("big.md", "tiny fragment")
    assert refused["status"] == "error"
    assert "shrinks" in refused["error"]
    assert (workspace / "big.md").read_text(encoding="utf-8") == "x" * 2000


@pytest.mark.asyncio
async def test_update_plan_and_outline(workspace: Path) -> None:
    plan = await core.update_plan([{"title": "task"}], summary="plan")
    assert plan["items"][0]["title"] == "task"

    outline = await core.update_outline("# Doc")
    assert (workspace / "outline.md").read_text(encoding="utf-8") == "# Doc"
    assert outline["outline_path"] == "outline.md"


@pytest.mark.asyncio
async def test_update_outline_append_and_shrink_guard(workspace: Path) -> None:
    (workspace / "outline.md").write_text("# Part1\n" + ("body\n" * 200), encoding="utf-8")
    before = (workspace / "outline.md").read_text(encoding="utf-8")

    refused = await core.update_outline("oops")
    assert refused["status"] == "error"
    assert (workspace / "outline.md").read_text(encoding="utf-8") == before

    appended = await core.update_outline("# Part2\nmore", mode="append")
    assert appended["mode"] == "append"
    text = (workspace / "outline.md").read_text(encoding="utf-8")
    assert text.startswith("# Part1\n")
    assert text.rstrip().endswith("# Part2\nmore")
    assert "body" in text


@pytest.mark.asyncio
async def test_grep_and_search_codebase(workspace: Path) -> None:
    (workspace / "code.py").write_text("def hello():\n    pass\n", encoding="utf-8")

    grep_result = await core.grep("hello", path=".")
    assert grep_result["match_count"] == 1

    search = await core.search_codebase("hello")
    assert search["hits"]


@pytest.mark.asyncio
async def test_write_file_and_edit_errors(workspace: Path) -> None:
    written = await core.write_file("out.txt", "data")
    assert written["status"] == "written"

    missing = await core.edit_file("nope.txt", "a", "b")
    assert missing["error"]

    bad = await core.edit_file("out.txt", "missing", "b")
    assert bad["error"] == "old_text not found"


@pytest.mark.asyncio
async def test_check_citation_and_stub_echo(workspace: Path) -> None:
    (workspace / "src.md").write_text("cite:abc content", encoding="utf-8")

    valid = await core.check_citation("cite:abc", "src.md")
    assert valid["valid"] is True

    invalid = await core.check_citation("cite:zzz", "src.md")
    assert invalid["valid"] is False

    echo = await core.stub_echo("ping")
    assert "ping" in echo["echo"]


@pytest.mark.asyncio
async def test_search_sources_keyword_mode(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = workspace / "sources"
    sources.mkdir()
    (sources / "note.md").write_text("alpha beta gamma", encoding="utf-8")
    monkeypatch.setattr(settings, "retrieval_mode", "keyword")

    result = await core.search_sources("alpha beta")
    assert result["retrieval"] == "keyword"
    assert len(result["hits"]) == 1


@pytest.mark.asyncio
async def test_search_sources_hybrid_mode(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = workspace / "sources"
    sources.mkdir()
    (sources / "note.md").write_text(
        "### 张白鹿\n张白鹿 张白鹿段落。\n\n## 李云龙\n李云龙段落。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "data_dir", str(workspace))

    # Index is built off the query path (A9).
    await core.sync_sources_index()
    result = await core.search_sources("张白鹿", limit=3)
    assert result["retrieval"] == "hybrid"
    assert result["hits"]
    assert result.get("index", {}).get("synced_on_query") is False
    assert any("张白鹿" in hit.get("excerpt", "") for hit in result["hits"])


@pytest.mark.asyncio
async def test_search_sources_never_syncs_inline(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = workspace / "sources"
    sources.mkdir()
    (sources / "note.md").write_text("unique-term-xyz appears here", encoding="utf-8")
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "data_dir", str(workspace))
    monkeypatch.setattr(settings, "index_via_worker", True)

    called = {"sync": 0}

    class FakeStore:
        def load(self) -> None:
            return None

        def sync(self, *_args, **_kwargs):
            called["sync"] += 1
            return {"indexed_files": 1}

        def search(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr("app.retrieval.store.get_sources_store", lambda **_kwargs: FakeStore())
    result = await core.search_sources("unique-term-xyz")
    assert called["sync"] == 0
    assert result.get("index", {}).get("synced_on_query") is False
    assert result.get("index", {}).get("index_lag") is True
    # Keyword fallback still finds the file without rebuilding the vector index.
    assert result["retrieval"] == "keyword-fallback"
    assert result["hits"]


@pytest.mark.asyncio
async def test_search_sources_path_prefix_keyword(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = workspace / "sources"
    (sources / "hr").mkdir(parents=True)
    (sources / "legal").mkdir(parents=True)
    (sources / "hr" / "leave.md").write_text("annual leave days policy", encoding="utf-8")
    (sources / "legal" / "nda.md").write_text("confidential information definition", encoding="utf-8")
    monkeypatch.setattr(settings, "retrieval_mode", "keyword")

    all_hits = await core.search_sources("leave")
    assert any("hr" in h["path"] for h in all_hits["hits"])

    filtered = await core.search_sources("leave", path_prefix="hr")
    assert filtered["filters"]["applied"] is True
    assert filtered["filters"]["path_prefix"] == "sources/hr"
    assert filtered["hits"]
    assert all(h["path"].startswith("sources/hr") for h in filtered["hits"])

    blocked = await core.search_sources("confidential", path_prefix="sources/hr")
    assert all(not h["path"].startswith("sources/legal") for h in blocked["hits"])

    bad = await core.search_sources("leave", path_prefix="../etc")
    assert bad["hits"] == []
    assert bad["filters"]["applied"] is False
    assert "hint" in bad


@pytest.mark.asyncio
async def test_search_sources_path_prefix_hybrid(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = workspace / "sources"
    (sources / "hr").mkdir(parents=True)
    (sources / "legal").mkdir(parents=True)
    (sources / "hr" / "leave.md").write_text(
        "## Leave\nannual leave days for staff.\n", encoding="utf-8"
    )
    (sources / "legal" / "nda.md").write_text(
        "## Confidential Information\nconfidential information definition.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "data_dir", str(workspace))
    await core.sync_sources_index()

    result = await core.search_sources("annual leave", path_prefix="hr", limit=5)
    assert result["retrieval"] == "hybrid"
    assert result["filters"]["path_prefix"] == "sources/hr"
    assert result["hits"]
    assert all(h["path"].startswith("sources/hr") for h in result["hits"])
    assert not any("legal" in h["path"] for h in result["hits"])


@pytest.mark.asyncio
async def test_search_sources_path_prefix_empty_ann_falls_back_keyword(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale ANN hits outside the prefix must not suppress on-disk keyword recall."""
    sources = workspace / "sources"
    (sources / "writing").mkdir(parents=True)
    (sources / "legal").mkdir(parents=True)
    (sources / "writing" / "liangjian.md").write_text(
        "## 张白鹿\n张白鹿性格独立，与李云龙相识。\n",
        encoding="utf-8",
    )
    (sources / "legal" / "nda.md").write_text(
        "## Noise\n张白鹿 must not be the only recall path.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "data_dir", str(workspace))

    class FakeStore:
        def load(self) -> None:
            return None

        def search(self, query: str, limit: int = 10, mode: str = "hybrid"):
            # Pretend shared index only knows the legal path.
            return [
                {
                    "path": "sources/legal/nda.md",
                    "excerpt": "张白鹿 must not be the only recall path.",
                    "score": 0.9,
                    "citation_id": "cite:nda",
                }
            ]

    monkeypatch.setattr("app.retrieval.store.get_sources_store", lambda: FakeStore())
    result = await core.search_sources("张白鹿", path_prefix="writing", limit=5)
    assert result["retrieval"] == "keyword-fallback"
    assert result["index"].get("prefix_empty_after_filter") is True
    assert result["filters"]["path_prefix"] == "sources/writing"
    assert result["hits"]
    assert all(h["path"].startswith("sources/writing") for h in result["hits"])
    assert "张白鹿" in result["hits"][0]["excerpt"]


@pytest.mark.asyncio
async def test_search_sources_keyword_section_fields(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = workspace / "sources"
    sources.mkdir()
    (sources / "doc.md").write_text(
        "## First\nnoise alpha.\n\n## Target Section\nunique-keyword beta gamma.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "retrieval_mode", "keyword")
    result = await core.search_sources("unique-keyword beta")
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit.get("section_title") == "Target Section"
    assert "unique-keyword" in hit["excerpt"]
    assert hit.get("chunk_id")


@pytest.mark.asyncio
async def test_search_sources_no_sources_dir(workspace: Path) -> None:
    result = await core.search_sources("query")
    assert result["hits"] == []


@pytest.mark.asyncio
async def test_sync_sources_index_empty(workspace: Path) -> None:
    result = await core.sync_sources_index()
    assert result["indexed_files"] == 0


@pytest.mark.asyncio
async def test_run_tests_simulate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "run_command_mode", "simulate")
    result = await core.run_tests()
    assert result["status"] == "passed"


@pytest.mark.asyncio
async def test_read_lints_fallback_scan(workspace: Path) -> None:
    (workspace / "mod.py").write_text("x=1\n", encoding="utf-8")
    with patch(
        "app.tools.core.shell.run_shell_command",
        AsyncMock(return_value={"status": "failed", "stdout": "", "stderr": ""}),
    ):
        result = await core.read_lints(".")
    assert result["issue_count"] == 0
    assert result["issues"]


@pytest.mark.asyncio
async def test_read_lints_reports_issues(workspace: Path) -> None:
    with patch(
        "app.tools.core.shell.run_shell_command",
        AsyncMock(return_value={"status": "failed", "stdout": "mod.py:1:1: E001 error", "stderr": ""}),
    ):
        result = await core.read_lints(".")
    assert result["issue_count"] == 1


@pytest.mark.asyncio
async def test_run_command_shell_mode(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "run_command_mode", "shell")
    with patch(
        "app.tools.core.shell.run_shell_command",
        AsyncMock(return_value={"status": "executed", "stdout": "ok", "exit_code": 0, "summary": "done"}),
    ):
        result = await core.run_command("echo ok")
    assert result["stdout"] == "ok"


@pytest.mark.asyncio
async def test_glob_missing_path(workspace: Path) -> None:
    result = await core.glob("*.md", path="missing")
    assert result["matches"] == []
