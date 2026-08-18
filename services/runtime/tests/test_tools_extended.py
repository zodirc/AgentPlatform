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
async def test_list_dir_hides_work_surface_internal(workspace: Path) -> None:
    (workspace / ".agent" / "work").mkdir(parents=True)
    (workspace / "sources" / "cards" / "pending").mkdir(parents=True)
    (workspace / "sources" / "cards" / "style.md").write_text("x", encoding="utf-8")
    (workspace / "ok.md").write_text("y", encoding="utf-8")

    root = await core.list_dir(".")
    names = [e.rstrip("/") for e in root["entries"]]
    assert ".agent" not in names
    assert "ok.md" in names

    cards = await core.list_dir("sources/cards")
    card_names = [e.rstrip("/") for e in cards["entries"]]
    assert "pending" not in card_names
    assert "style.md" in card_names

    # Visible draft manuscript (work surface) + legacy harness path still readable.
    (workspace / "drafts").mkdir(parents=True)
    (workspace / "drafts" / "manuscript.md").write_text("draft", encoding="utf-8")
    read = await core.read_file("drafts/manuscript.md")
    assert read.get("content") == "draft" or "draft" in str(read.get("content", ""))
    root_listing = await core.list_dir(".")
    root_names = [e.rstrip("/") for e in root_listing["entries"]]
    assert "drafts" in root_names
    assert ".agent" not in root_names

    legacy = workspace / ".agent" / "work" / "drafts"
    legacy.mkdir(parents=True)
    (legacy / "manuscript.md").write_text("legacy-draft", encoding="utf-8")
    legacy_read = await core.read_file(".agent/work/drafts/manuscript.md")
    assert "legacy-draft" in str(legacy_read.get("content", ""))


@pytest.mark.asyncio
async def test_read_file_truncates_large_content(workspace: Path) -> None:
    (workspace / "big.txt").write_text("x" * 40_000, encoding="utf-8")
    result = await core.read_file("big.txt")
    assert result["truncated"] is True
    assert result["next_offset"] is None  # single oversized line — continue-by-offset N/A
    assert "truncated" in result["summary"]
    assert "char" in result.get("hint", "").lower() or "grep" in result.get("hint", "").lower()


@pytest.mark.asyncio
async def test_read_file_line_window_char_budget(workspace: Path) -> None:
    # Many short lines so continuation uses next_offset (not a single mega-line).
    lines = [f"{i:04d} {'y' * 80}" for i in range(600)]
    (workspace / "many.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    first = await core.read_file("many.txt")
    assert first["truncated"] is True
    assert first["next_offset"] is not None
    assert first["end_line"] < first["total_lines"]
    assert "offset=" in first.get("hint", "")
    # Non-code truncated reads must not grow an outline field.
    assert "outline" not in first
    second = await core.read_file("many.txt", offset=first["next_offset"])
    assert second["offset"] == first["next_offset"]
    assert second["content"]


@pytest.mark.asyncio
async def test_read_file_truncated_code_attaches_outline(workspace: Path) -> None:
    # Force truncation via line limit so outline attaches (Wave 3 W7).
    parts = ["class Big:\n"]
    for i in range(80):
        parts.append(f"    def meth_{i}(self):\n        return {i}\n")
    (workspace / "bigmod.py").write_text("".join(parts), encoding="utf-8")
    result = await core.read_file("bigmod.py", limit=5)
    assert result["truncated"] is True
    assert result.get("outline")
    assert result["outline_count"] >= 1
    assert any("class Big" in line or "def " in line or "method " in line for line in result["outline"])
    # Complete small read: no outline.
    (workspace / "tiny.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    tiny = await core.read_file("tiny.py")
    assert tiny["truncated"] is False
    assert "outline" not in tiny


@pytest.mark.asyncio
async def test_read_file_offset_limit_and_complete_flag(workspace: Path) -> None:
    body = "\n".join(f"line-{i}" for i in range(1, 21))
    (workspace / "lines.txt").write_text(body + "\n", encoding="utf-8")

    full = await core.read_file("lines.txt")
    assert full["truncated"] is False
    assert full["whole_file_complete"] is True
    assert full["total_lines"] == 20
    assert full["next_offset"] is None
    assert "complete" in full["summary"]

    page = await core.read_file("lines.txt", offset=5, limit=3)
    assert page["offset"] == 5
    assert page["end_line"] == 7
    assert page["truncated"] is True
    assert page["next_offset"] == 8
    assert page["content"].startswith("line-5")
    assert "line-8" not in page["content"]

    rest = await core.read_file("lines.txt", offset=page["next_offset"])
    assert rest["truncated"] is False
    assert rest["whole_file_complete"] is False
    assert "eof_from_offset" in rest["summary"]
    assert rest["content"].startswith("line-8")

    full2 = await core.read_file("lines.txt", offset=1)
    assert full2["whole_file_complete"] is True
    assert "(complete)" in full2["summary"]
    assert "eof_from_offset" not in full2["summary"]

@pytest.mark.asyncio
async def test_resolve_path_rejects_escape(workspace: Path) -> None:
    with pytest.raises(PermissionError):
        await core.read_file("/etc/passwd")


@pytest.mark.asyncio
async def test_propose_and_apply_patch(workspace: Path) -> None:
    (workspace / "f.md").write_text("old content here", encoding="utf-8")
    proposed = await core.propose_patch("f.md", "old", "new", summary="s")
    assert proposed["status"] == "pending"
    assert proposed["applies"] is True
    assert proposed["patch_id"].startswith("patch-")

    applied = await core.apply_patch("f.md", "hello-world", force_full_replace=True)
    assert applied["status"] == "applied"
    assert (workspace / "f.md").read_text(encoding="utf-8") == "hello-world"


@pytest.mark.asyncio
async def test_propose_patch_rejects_missing_span(workspace: Path) -> None:
    (workspace / "f.md").write_text("hello", encoding="utf-8")
    bad = await core.propose_patch("f.md", "missing", "new", summary="s")
    assert bad["status"] == "error"
    assert bad["applies"] is False
    assert "not found" in bad["error"]


@pytest.mark.asyncio
async def test_propose_patch_rejects_ambiguous_span(workspace: Path) -> None:
    (workspace / "f.md").write_text("aa aa", encoding="utf-8")
    bad = await core.propose_patch("f.md", "aa", "bb", summary="s")
    assert bad["status"] == "error"
    assert bad["applies"] is False
    assert "matches" in bad["error"]


@pytest.mark.asyncio
async def test_propose_patch_git_apply_check_when_repo(workspace: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    (workspace / "f.md").write_text("line one\nline two\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.md"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    proposed = await core.propose_patch("f.md", "line two", "line two fixed", summary="s")
    assert proposed["status"] == "pending"
    assert proposed["applies"] is True
    assert proposed.get("apply_check") in {"git_apply_check", "span_unique"}


@pytest.mark.asyncio
async def test_write_file_patch_precheck_no_git(workspace: Path) -> None:
    patch = (
        "diff --git a/x.md b/x.md\n"
        "--- a/x.md\n"
        "+++ b/x.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    out = await core.write_file("change.patch", patch)
    assert (workspace / "change.patch").exists()
    assert out.get("apply_check") == "no_git"


@pytest.mark.asyncio
async def test_write_file_patch_precheck_with_git(workspace: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    (workspace / "x.md").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "x.md"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    patch = (
        "diff --git a/x.md b/x.md\n"
        "--- a/x.md\n"
        "+++ b/x.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    out = await core.write_file("change.patch", patch)
    assert out.get("apply_check") == "git_apply_check"
    assert "applies" in out


@pytest.mark.asyncio
async def test_write_file_truncates_old_text_preview(workspace: Path) -> None:
    (workspace / "big.md").write_text("Z" * 40_000, encoding="utf-8")
    out = await core.write_file("big.md", "tiny")
    assert out["status"] == "written"
    assert out["old_text"].endswith("...[truncated]")
    assert len(out["old_text"]) < 40_000


@pytest.mark.asyncio
async def test_propose_patch_rejects_identical_span(workspace: Path) -> None:
    (workspace / "f.md").write_text("same", encoding="utf-8")
    bad = await core.propose_patch("f.md", "same", "same", summary="s")
    assert bad["status"] == "error"
    assert bad["applies"] is False
    assert "identical" in bad["error"]


@pytest.mark.asyncio
async def test_propose_patch_missing_file(workspace: Path) -> None:
    bad = await core.propose_patch("nope.md", "a", "b", summary="s")
    assert bad["status"] == "error"
    assert bad["applies"] is False


@pytest.mark.asyncio
async def test_span_apply_precheck_git_warning_on_bad_diff(workspace: Path) -> None:
    """Git worktree + synthetic patch that fails --check still returns applies=True."""
    import subprocess

    from app.tools.core.tools import _span_apply_precheck

    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    (workspace / "f.md").write_text("alpha\nbeta\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.md"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    # Unique span — authoritative gate; git apply may warn.
    out = _span_apply_precheck("f.md", "beta", "beta-fixed")
    assert out["applies"] is True
    assert out.get("apply_check") in {"git_apply_check", "span_unique"}


def test_span_apply_precheck_oserror(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core import tools as t

    boom = MagicMock()
    boom.exists.return_value = True
    boom.read_text.side_effect = OSError("denied")
    monkeypatch.setattr(t, "_resolve_path", lambda _path: boom)
    bad = t._span_apply_precheck("locked.md", "hello", "world")
    assert bad["applies"] is False
    assert "cannot read" in bad["apply_check_error"]


def test_span_apply_precheck_git_timeout_and_warning(workspace: Path) -> None:
    import subprocess

    from app.tools.core.tools import _span_apply_precheck

    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    (workspace / "f.md").write_text("one\ntwo\n", encoding="utf-8")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=1)):
        out = _span_apply_precheck("f.md", "two", "two-b")
    assert out["applies"] is True
    assert out.get("apply_check") == "span_unique"

    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stderr="patch does not apply", stdout="")
        out2 = _span_apply_precheck("f.md", "two", "two-b")
    assert out2["applies"] is True
    assert out2.get("apply_check") == "span_unique"
    assert "apply_check_warning" in out2

    with patch("difflib.unified_diff", side_effect=RuntimeError("boom")):
        out3 = _span_apply_precheck("f.md", "two", "two-b")
    assert out3 == {"applies": True, "apply_check": "span_unique"}

    with patch("difflib.unified_diff", return_value=[]):
        out4 = _span_apply_precheck("f.md", "two", "two-b")
    assert out4 == {"applies": True, "apply_check": "span_unique"}


def test_budget_limits_settings_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.context import engine as eng
    import app.settings as settings_mod

    monkeypatch.setattr(settings_mod, "settings", SimpleNamespace())
    default_b, read_b, protect = eng._budget_limits()
    assert default_b == eng.TOOL_RESULT_CHAR_BUDGET
    assert read_b == eng.TOOL_RESULT_LATEST_READ_CHAR_BUDGET
    assert protect is True


def test_unified_patch_precheck_timeout(workspace: Path) -> None:
    import subprocess

    from app.tools.core.tools import _unified_patch_apply_precheck

    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    body = "diff --git a/x.md b/x.md\n--- a/x.md\n+++ b/x.md\n@@ -1 +1 @@\n-a\n+b\n"
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=1)):
        out = _unified_patch_apply_precheck(body)
    assert out.get("apply_check") == "unavailable"


@pytest.mark.asyncio
async def test_apply_patch_missing_and_ambiguous(workspace: Path) -> None:
    missing = await core.apply_patch("gone.md", "new", old_text="old")
    assert missing["status"] == "error"

    (workspace / "f.md").write_text("aa aa", encoding="utf-8")
    amb = await core.apply_patch("f.md", "bb", old_text="aa")
    assert amb["status"] == "error"
    assert "matches" in amb["error"]


@pytest.mark.asyncio
async def test_unified_patch_precheck_empty_and_fail(workspace: Path) -> None:
    from app.tools.core.tools import _unified_patch_apply_precheck
    import subprocess

    assert _unified_patch_apply_precheck("") == {}
    assert _unified_patch_apply_precheck("not a patch") == {}

    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    bad = _unified_patch_apply_precheck(
        "diff --git a/missing.md b/missing.md\n"
        "--- a/missing.md\n"
        "+++ b/missing.md\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )
    assert bad.get("applies") is False
    assert bad.get("apply_check") == "git_apply_check"


@pytest.mark.asyncio
async def test_write_file_patch_surfaces_apply_failure(workspace: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    patch = (
        "diff --git a/ghost.md b/ghost.md\n"
        "--- a/ghost.md\n"
        "+++ b/ghost.md\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )
    out = await core.write_file("bad.patch", patch)
    assert out.get("applies") is False
    assert "does not apply" in out.get("summary", "")


@pytest.mark.asyncio
async def test_edit_file_rejects_ambiguous_span(workspace: Path) -> None:
    (workspace / "f.md").write_text("aa aa", encoding="utf-8")
    bad = await core.edit_file("f.md", "aa", "bb")
    assert bad.get("applies") is False
    assert "matches" in bad.get("error", "")


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
async def test_update_outline_thin_unless_toc_ask(workspace: Path) -> None:
    thin = await core.update_outline(
        "# 第一章\n一句。\n# 第二章\n两句。",
        turn_user_text="写一版章纲",
    )
    assert thin["outline_thin"] is True
    assert "第一章" in thin["thin_chapters"]
    assert (workspace / "outline.md").read_text(encoding="utf-8").startswith("# 第一章")

    fat_body = "目标阻力场面信息变化章末落点。" * 20
    ok = await core.update_outline(
        f"# 第一章\n{fat_body}",
        turn_user_text="写一版章纲",
    )
    assert ok["outline_thin"] is False

    toc = await core.update_outline(
        "# 卷一\n# 卷二\n",
        turn_user_text="只要目录",
    )
    assert toc["outline_thin"] is False
    assert "thin_chapters" not in toc


@pytest.mark.asyncio
async def test_update_outline_append_scores_new_chunk_only(workspace: Path) -> None:
    (workspace / "outline.md").write_text("# 旧章\n", encoding="utf-8")
    fat = "目标阻力场面变化落点。" * 20
    appended = await core.update_outline(
        f"# 新章\n{fat}",
        mode="append",
        turn_user_text="继续加厚",
    )
    assert appended["mode"] == "append"
    assert appended["outline_thin"] is False
    text = (workspace / "outline.md").read_text(encoding="utf-8")
    assert "# 旧章" in text and "# 新章" in text


@pytest.mark.asyncio
async def test_grep_and_search_codebase(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (workspace / "code.py").write_text("def hello():\n    pass\n", encoding="utf-8")

    async def fake_goto(*_a, **_k):
        from app.structural.types import Location

        return {
            "locations": [
                Location(
                    path="code.py",
                    line=1,
                    col=5,
                    kind="def",
                    symbol="hello",
                )
            ],
            "meta": {"provider": "jedi"},
        }

    monkeypatch.setattr("app.structural.adapters.goto_definition", fake_goto)

    # Bare symbol → Locate redirect (definitions), not pure lexical.
    grep_result = await core.grep("hello", path=".")
    assert grep_result.get("redirected_from") == "grep"
    assert grep_result["definitions"]

    search = await core.search_codebase("hello")
    assert search["definitions"]
    assert search["locate_incomplete"] is False

    # Phrase / error-like → lexical path unchanged.
    lexical = await core.search_codebase("def hello")
    assert lexical["mode"] == "lexical"
    assert lexical["hits"]


@pytest.mark.asyncio
async def test_lexical_search_skips_venv_noise_and_stays_off_loop(
    workspace: Path,
) -> None:
    """Regression: .local/site-packages must not enter hits; scan is threaded."""
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("findme_lexical_token = 1\n", encoding="utf-8")
    junk = workspace / ".local" / "lib" / "python3.11" / "site-packages" / "erfa"
    junk.mkdir(parents=True)
    (junk / "__init__.py").write_text("findme_lexical_token = 'pollute'\n", encoding="utf-8")
    (workspace / ".venv" / "lib").mkdir(parents=True)
    (workspace / ".venv" / "lib" / "x.py").write_text("findme_lexical_token\n", encoding="utf-8")

    result = await core.search_codebase("findme_lexical_token =")
    assert result["mode"] == "lexical"
    paths = [h["path"] for h in result["hits"]]
    assert any(p.endswith("src/app.py") or p.endswith("app.py") for p in paths)
    assert not any(".local" in p or "site-packages" in p or ".venv" in p for p in paths)

    grep = await core.grep(r"findme_lexical_token\s*=", path=".")
    gpaths = [m["path"] for m in grep["matches"]]
    assert any("app.py" in p for p in gpaths)
    assert not any(".local" in p or ".venv" in p for p in gpaths)


@pytest.mark.asyncio
async def test_write_file_and_edit_errors(workspace: Path) -> None:
    written = await core.write_file("out.txt", "data")
    assert written["status"] == "written"

    missing = await core.edit_file("nope.txt", "a", "b")
    assert missing["error"]

    bad = await core.edit_file("out.txt", "missing", "b")
    assert bad["error"] == "old_text not found"


@pytest.mark.asyncio
async def test_rename_file_moves_and_guards(workspace: Path) -> None:
    await core.write_file("exports/old.md", "body")
    ok = await core.rename_file("exports/old.md", "exports/新书名.md")
    assert ok["status"] == "renamed"
    assert (workspace / "exports" / "新书名.md").read_text(encoding="utf-8") == "body"
    assert not (workspace / "exports" / "old.md").exists()

    clash = await core.rename_file("exports/新书名.md", "exports/新书名.md")
    assert clash["status"] == "ok"

    await core.write_file("exports/other.md", "x")
    blocked = await core.rename_file("exports/other.md", "exports/新书名.md")
    assert blocked["status"] == "error"
    assert "exists" in blocked["error"]

    over = await core.rename_file(
        "exports/other.md", "exports/新书名.md", overwrite=True
    )
    assert over["status"] == "renamed"
    assert (workspace / "exports" / "新书名.md").read_text(encoding="utf-8") == "x"

    seed = workspace / "sources" / "seed"
    seed.mkdir(parents=True)
    (seed / "ro.md").write_text("seed", encoding="utf-8")
    denied = await core.rename_file("sources/seed/ro.md", "exports/stolen.md")
    assert denied["status"] == "error"


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
    monkeypatch.setattr(settings, "retrieval_backend", "json")
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    from app.retrieval.embedder import reset_embedder_cache

    reset_embedder_cache()
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
    monkeypatch.setattr(settings, "retrieval_backend", "json")
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    from app.retrieval.embedder import reset_embedder_cache

    reset_embedder_cache()
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

    monkeypatch.setattr("app.retrieval.store.get_sources_store", lambda **_kwargs: FakeStore())
    result = await core.search_sources("张白鹿", path_prefix="writing", limit=5)
    assert result["retrieval"] == "keyword-fallback"
    assert result["index"].get("prefix_empty_after_filter") is True
    assert result["filters"]["path_prefix"] == "sources/writing"
    assert result["hits"]
    assert all(h["path"].startswith("sources/writing") for h in result["hits"])
    assert "张白鹿" in result["hits"][0]["excerpt"]


@pytest.mark.asyncio
async def test_search_sources_ann_without_query_terms_falls_back_keyword(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hash/ANN neighbors that omit query tokens must not suppress on-disk keyword."""
    sources = workspace / "sources"
    sources.mkdir()
    (sources / "new-chunk.md").write_text(
        "New material with phase2-unique-term for vector recall.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "data_dir", str(workspace))

    class FakeStore:
        def load(self) -> None:
            return None

        def search(self, query: str, limit: int = 10, mode: str = "hybrid"):
            return [
                {
                    "path": "sources/seed/writing/noise.md",
                    "excerpt": "unrelated seed neighbor from hash ANN",
                    "score": 0.4,
                    "citation_id": "cite:noise",
                    "visibility": "seed",
                }
            ]

    monkeypatch.setattr("app.retrieval.store.get_sources_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        "app.retrieval.tenant_visibility.filter_hits_for_tenant",
        lambda hits: hits,
    )
    result = await core.search_sources("phase2-unique-term", limit=5)
    assert result["retrieval"] == "keyword-fallback"
    assert result["index"].get("ann_missed_query_terms") is True
    assert result["hits"]
    assert "phase2-unique-term" in result["hits"][0]["excerpt"]


def test_hits_cover_query_terms_ignores_runtime_noise() -> None:
    from app.tools.core.tools import _hits_cover_query_terms

    seed_hit = {"path": "sources/seed/writing/noise.md", "excerpt": "unrelated"}
    assert _hits_cover_query_terms([seed_hit], "writing search_sources TENANT_OWN_MARKER_WAVE_A") is False
    own = {"path": "sources/tenant-own.md", "excerpt": "TENANT_OWN_MARKER_WAVE_A present"}
    assert _hits_cover_query_terms([own], "TENANT_OWN_MARKER_WAVE_A") is True


def test_distinctive_query_terms_keeps_short_scientific_entities() -> None:
    from app.tools.core.tools import _distinctive_query_terms

    terms = _distinctive_query_terms("ADAR1 binds to Dicer to cleave pre-miRNA")
    assert "adar1" in terms
    assert "dicer" in terms
    assert "cleave" in terms
    # Short stop-ish verbs stay out.
    assert "binds" not in terms
    assert "to" not in terms


@pytest.mark.asyncio
async def test_search_sources_keeps_ann_when_cover_miss_and_keyword_empty(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claim tokens absent from abstract must not wipe rank-1 ANN (SciFact pattern)."""
    sources = workspace / "sources"
    sources.mkdir()
    # No on-disk lexical overlap with the claim verb "cleave" / "pre-miRNA".
    (sources / "5953485.txt").write_text(
        "ADAR1 Forms a Complex with Dicer to Promote MicroRNA Processing\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "data_dir", str(workspace))

    class FakeStore:
        def load(self) -> None:
            return None

        def search(self, query: str, limit: int = 10, mode: str = "hybrid"):
            return [
                {
                    "path": "sources/5953485.txt",
                    "excerpt": (
                        "ADAR1 Forms a Complex with Dicer to Promote "
                        "MicroRNA Processing and RNA-Induced Gene Silencing"
                    ),
                    "score": 1.69,
                    "citation_id": "cite:5953485",
                    "visibility": "private",
                }
            ]

    monkeypatch.setattr("app.retrieval.store.get_sources_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        "app.retrieval.tenant_visibility.filter_hits_for_tenant",
        lambda hits: hits,
    )
    # Force cover miss + empty keyword so we exercise ANN retention (not seed OR-noise).
    monkeypatch.setattr(
        "app.tools.core.tools._distinctive_query_terms",
        lambda _q: ["cleave", "pre-mirna"],
    )
    monkeypatch.setattr(
        "app.tools.core.tools._search_sources_keyword",
        lambda *_a, **_k: ([], {}),
    )
    result = await core.search_sources(
        "ADAR1 binds to Dicer to cleave pre-miRNA", limit=5
    )
    assert result["retrieval"] == "hybrid"
    assert result["hits"]
    assert "5953485" in result["hits"][0]["path"]
    assert result["index"].get("ann_missed_query_terms") is True
    assert result["index"].get("kept_ann_despite_cover_miss") is True
    assert result["index"].get("index_lag") is not True


def test_prefer_excerpt_covering_hits_promotes_visible_term() -> None:
    from app.tools.core.tools import _prefer_excerpt_covering_hits

    late = {
        "path": "sources/seed/writing/dramas/drama1.md",
        "excerpt": "情节改编\n- 亮剑精神的出处：原著…",
    }
    early = {
        "path": "sources/seed/writing/dramas/drama1.md",
        "excerpt": "建国后至授衔\n- 情感风波：张白鹿对李云龙产生好感。",
    }
    ordered = _prefer_excerpt_covering_hits([late, early], "张白鹿")
    assert ordered[0] is early
    assert ordered[1] is late
    assert ordered[0].get("_excerpt_promote_reorder") is True


def test_tier_search_hits_for_model_ret12() -> None:
    from app.tools.core.tools import _search_hit_presentation_note, _tier_search_hits_for_model

    hits = [
        {
            "path": f"sources/{i}.md",
            "chunk_id": f"c{i}",
            "excerpt": f"body-{i}-" + ("x" * 50),
            "section_title": f"Title {i}",
            "score": 1.0 - i * 0.01,
            "citation_id": f"cite:{i}",
        }
        for i in range(12)
    ]
    tiered = _tier_search_hits_for_model(hits, detail_n=5)
    assert len(tiered) == 12
    for i in range(5):
        assert "excerpt" in tiered[i]
        assert tiered[i]["path"] == f"sources/{i}.md"
    for i in range(5, 12):
        assert "excerpt" not in tiered[i]
        assert "citation_id" not in tiered[i]
        assert tiered[i]["path"] == f"sources/{i}.md"
        assert tiered[i]["title"] == f"Title {i}"
        assert "chunk_id" in tiered[i]
        assert "score" in tiered[i]
    note = _search_hit_presentation_note(tiered)
    assert note is not None
    assert "top 5" in note
    assert _search_hit_presentation_note(tiered[:5]) is None
    assert _tier_search_hits_for_model(hits[:3], detail_n=5) == hits[:3]


def test_prefer_excerpt_covering_hits_no_flag_when_order_unchanged() -> None:
    from app.tools.core.tools import _prefer_excerpt_covering_hits

    early = {
        "path": "sources/a.md",
        "excerpt": "alpha marker here",
    }
    late = {
        "path": "sources/b.md",
        "excerpt": "unrelated",
    }
    ordered = _prefer_excerpt_covering_hits([early, late], "alpha marker")
    assert ordered[0] is early
    assert "_excerpt_promote_reorder" not in ordered[0]


def test_ret7_excerpt_promote_settings_default_and_enable(monkeypatch) -> None:
    """RET-7: default off after ablation; settings flag can re-enable silent promote."""
    from app.settings import Settings
    from app.tools.core import tools as tools_mod

    assert Settings().search_sources_excerpt_promote is False
    monkeypatch.setattr(tools_mod.settings, "search_sources_excerpt_promote", True)
    assert tools_mod.settings.search_sources_excerpt_promote is True
    # Function itself still promotes when called directly (switch lives at call site).
    late = {
        "path": "sources/seed/writing/dramas/drama1.md",
        "excerpt": "情节改编\n- 亮剑精神的出处：原著…",
    }
    early = {
        "path": "sources/seed/writing/dramas/drama1.md",
        "excerpt": "建国后至授衔\n- 情感风波：张白鹿对李云龙产生好感。",
    }
    ordered = tools_mod._prefer_excerpt_covering_hits([late, early], "张白鹿")
    assert ordered[0] is early


def test_ret18_two_level_settings_default_on(monkeypatch) -> None:
    """RET-18: two-level default on; ablation sets RETRIEVAL_TWO_LEVEL_ENABLED=false."""
    from app.retrieval.profile import active_retrieval_profile
    from app.settings import Settings, settings as live

    # Host / ablation shells may export RETRIEVAL_TWO_LEVEL_ENABLED=false;
    # isolate when asserting the code default.
    monkeypatch.delenv("RETRIEVAL_TWO_LEVEL_ENABLED", raising=False)
    assert Settings(_env_file=None).retrieval_two_level_enabled is True
    monkeypatch.setattr(live, "retrieval_two_level_enabled", False)
    assert active_retrieval_profile().two_level_enabled is False
    monkeypatch.setattr(live, "retrieval_two_level_enabled", True)
    assert active_retrieval_profile().two_level_enabled is True


def test_ret15_score_rel_and_low_score_uses_raw(monkeypatch) -> None:
    """RET-15-2: model sees 0–100 rel scores; low_score compares raw fusion score."""
    from app.settings import Settings
    from app.tools.core import tools as tools_mod

    assert Settings().search_sources_score_rel is True
    assert Settings().search_sources_low_score_hint == 1.0

    monkeypatch.setattr(tools_mod.settings, "search_sources_score_rel", True)
    monkeypatch.setattr(tools_mod.settings, "search_sources_low_score_hint", 1.0)
    monkeypatch.setattr(tools_mod.settings, "search_sources_detail_hits", 5)

    strong = [
        {"path": "a.md", "excerpt": "x", "score": 2.0},
        {"path": "b.md", "excerpt": "y", "score": 1.0},
    ]
    hits, hint = tools_mod._finalize_search_hits_for_model(strong)
    assert hits[0]["score"] == 100
    assert hits[1]["score"] == 50
    assert hits[0]["score_raw"] == 2.0
    assert hits[1]["score_raw"] == 1.0
    assert hint is None or "Low relevance" not in hint

    weak = [
        {"path": "weak.md", "excerpt": "z", "score": 0.5},
        {"path": "weaker.md", "excerpt": "w", "score": 0.25},
    ]
    whits, whint = tools_mod._finalize_search_hits_for_model(weak)
    assert whits[0]["score"] == 100
    assert whits[0]["score_raw"] == 0.5
    assert whint is not None and "Low relevance" in whint


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
    """When ruff is down but LSP is not required-failed, list files as info issues."""
    (workspace / "mod.py").write_text("x=1\n", encoding="utf-8")
    with (
        patch(
            "app.tools.core.shell.run_shell_command",
            AsyncMock(return_value={"status": "failed", "stdout": "", "stderr": ""}),
        ),
        patch(
            "app.structural.adapters.get_diagnostics",
            AsyncMock(
                return_value={
                    "issues": [],
                    "meta": {
                        "provider": None,
                        "cold_start": False,
                        "truncated": False,
                        "unsupported": False,
                        "degraded_reason": None,
                    },
                }
            ),
        ),
    ):
        result = await core.read_lints(".")
    assert result["issue_count"] == 0
    assert result["issues"]
    assert any("ruff unavailable" in str(i.get("message") or "") for i in result["issues"])


@pytest.mark.asyncio
async def test_read_lints_lsp_infra_failed_is_explicit(workspace: Path) -> None:
    """LSP infrastructure failure must not silently look like a clean scan."""
    (workspace / "mod.py").write_text("x=1\n", encoding="utf-8")
    with (
        patch(
            "app.tools.core.shell.run_shell_command",
            AsyncMock(return_value={"status": "failed", "stdout": "", "stderr": ""}),
        ),
        patch(
            "app.structural.adapters.get_diagnostics",
            AsyncMock(
                return_value={
                    "issues": [],
                    "meta": {
                        "provider": None,
                        "cold_start": False,
                        "truncated": False,
                        "unsupported": False,
                        "degraded_reason": "lsp_unavailable",
                    },
                }
            ),
        ),
    ):
        result = await core.read_lints(".")
    assert result.get("status") == "failed"
    assert result["issue_count"] == 0
    assert result["issues"] == []
    assert "language server" in str(result.get("summary") or "").lower()


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
