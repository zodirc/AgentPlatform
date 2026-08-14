"""Inspect AST index outline (Settings)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.structural.workspace_index.inspect import (
    format_symbol_tree,
    inspect_ast_index,
    nest_symbols,
)
from app.structural.workspace_index.projection import (
    IndexProjection,
    get_projection_registry,
)
from app.structural.workspace_index.service import get_ast_index_service
from app.structural.workspace_index.types import (
    FileEntry,
    IndexMeta,
    IndexStatus,
    SymbolRec,
)


def test_nest_and_format_symbol_tree() -> None:
    symbols = [
        SymbolRec(name="Engine", kind="class", line=10, end_line=80),
        SymbolRec(name="start", kind="method", line=20, end_line=40, container="Engine"),
        SymbolRec(name="step", kind="method", line=50, container="Engine"),
        SymbolRec(name="create_app", kind="function", line=90),
    ]
    tree = nest_symbols(symbols)
    assert tree[0]["name"] == "Engine"
    assert [c["name"] for c in tree[0]["children"]] == ["start", "step"]
    assert tree[1]["name"] == "create_app"
    text = format_symbol_tree(symbols, path="engine.py")
    assert "class Engine  L10–80" in text
    assert "method start  L20–40" in text
    assert "function create_app  L90" in text


@pytest.mark.asyncio
async def test_inspect_ast_index_returns_tree_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.structural.workspace_index.service.settings.workspace_ast_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.structural.workspace_index.service.settings.workspace_ast_ops_enabled",
        True,
    )
    wid = uuid4()
    owner = "user-1"
    entry = FileEntry(
        path="app/engine.py",
        lang="python",
        content_hash="x",
        mtime_ns=1,
        size=100,
        symbols=[
            SymbolRec(name="Engine", kind="class", line=1, end_line=20),
            SymbolRec(name="run", kind="method", line=5, container="Engine"),
        ],
        generation=2,
    )
    meta = IndexMeta(
        work_id=wid,
        owner_user_id=owner,
        status=IndexStatus.READY,
        generation=2,
        files_total=1,
        files_done=1,
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([entry], meta=meta)
    get_projection_registry().put(proj)
    get_ast_index_service().mark_ephemeral(wid)

    listed = await inspect_ast_index(work_id=wid, owner_user_id=owner)
    assert listed["files"][0]["path"] == "app/engine.py"
    assert listed["files"][0]["symbol_count"] == 2

    detail = await inspect_ast_index(
        work_id=wid, owner_user_id=owner, path="app/engine.py"
    )
    file_row = detail["file"]
    assert file_row["missing"] is False
    assert "class Engine" in file_row["tree_text"]
    assert file_row["tree"][0]["children"][0]["name"] == "run"


@pytest.mark.asyncio
async def test_inspect_ast_index_drops_missing_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.structural.workspace_index.service.settings.workspace_ast_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.structural.workspace_index.service.settings.workspace_ast_ops_enabled",
        True,
    )
    wid = uuid4()
    owner = "user-1"
    live = FileEntry(
        path="app/engine.py",
        lang="python",
        content_hash="x",
        mtime_ns=1,
        size=100,
        symbols=[SymbolRec(name="Engine", kind="class", line=1, end_line=20)],
        generation=2,
    )
    ghost = FileEntry(
        path="astropy.root.backup/gone.py",
        lang="python",
        content_hash="y",
        mtime_ns=1,
        size=10,
        symbols=[SymbolRec(name="Ghost", kind="class", line=1)],
        generation=2,
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "engine.py").write_text("class Engine:\n    pass\n")
    meta = IndexMeta(
        work_id=wid,
        owner_user_id=owner,
        status=IndexStatus.READY,
        generation=2,
        files_total=2,
        files_done=2,
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([live, ghost], meta=meta)
    get_projection_registry().put(proj)
    get_ast_index_service().mark_ephemeral(wid)

    listed = await inspect_ast_index(
        work_id=wid, owner_user_id=owner, work_root=tmp_path
    )
    paths = {f["path"] for f in listed["files"]}
    assert "app/engine.py" in paths
    assert "astropy.root.backup/gone.py" not in paths


@pytest.mark.asyncio
async def test_inspect_ast_index_drops_writing_cards(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.structural.workspace_index.service.settings.workspace_ast_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.structural.workspace_index.service.settings.workspace_ast_ops_enabled",
        True,
    )
    wid = uuid4()
    owner = "user-1"
    card_rel = (
        "sources/cards/pending/"
        "20260806T070756Z_066d381a-d72e-4ce2-9c7e-464707fae8ca_松了一.md"
    )
    card = tmp_path / card_rel
    card.parent.mkdir(parents=True)
    card.write_text("# 松了一\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "engine.py").write_text("class Engine:\n    pass\n")
    live = FileEntry(
        path="app/engine.py",
        lang="python",
        content_hash="x",
        mtime_ns=1,
        size=100,
        symbols=[SymbolRec(name="Engine", kind="class", line=1)],
        generation=2,
    )
    card_entry = FileEntry(
        path=card_rel,
        lang="skipped",
        content_hash="md",
        mtime_ns=1,
        size=20,
        symbols=[],
        generation=2,
    )
    meta = IndexMeta(
        work_id=wid,
        owner_user_id=owner,
        status=IndexStatus.READY,
        generation=2,
        files_total=2,
        files_done=2,
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([live, card_entry], meta=meta)
    get_projection_registry().put(proj)
    get_ast_index_service().mark_ephemeral(wid)

    listed = await inspect_ast_index(
        work_id=wid, owner_user_id=owner, work_root=tmp_path
    )
    paths = {f["path"] for f in listed["files"]}
    assert "app/engine.py" in paths
    assert card_rel not in paths
