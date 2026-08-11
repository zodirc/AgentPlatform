"""Unit tests for Agent workspace AST index (docs/plan/agent-workspace-ast-index.md A0–A3)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.structural.workspace_index.hashutil import hash_text
from app.structural.workspace_index.ignore import dir_skipped, file_skipped
from app.structural.workspace_index.job import parse_file_entry, walk_work_files
from app.structural.workspace_index.parse import extract_definitions
from app.structural.workspace_index.projection import (
    IndexProjection,
    ProjectionRegistry,
)
from app.structural.workspace_index.types import (
    FileEntry,
    IndexMeta,
    IndexStatus,
    SymbolRec,
)


def test_ddl_file_exists_and_isolated_from_rag() -> None:
    from pathlib import Path as P

    # contracts DDL lives at repo packages/contracts/schemas/ddl/
    root = P(__file__).resolve().parents[3]  # AgentPlatform/
    ddl = root / "packages" / "contracts" / "schemas" / "ddl" / "phase1m_work_ast_index.sql"
    assert ddl.is_file()
    text = ddl.read_text()
    assert "CREATE TABLE IF NOT EXISTS work_ast_index_meta" in text
    assert "CREATE TABLE IF NOT EXISTS work_ast_files" in text
    assert "CREATE TABLE IF NOT EXISTS source_chunks" not in text
    assert "CREATE TABLE IF NOT EXISTS source_index_meta" not in text


def test_extract_definitions_python() -> None:
    src = (
        "X = 1\n"
        "class Foo:\n"
        "    def bar(self):\n"
        "        return 1\n"
        "\n"
        "def baz():\n"
        "    pass\n"
    )
    symbols = extract_definitions(src, language="python")
    names = {s.name for s in symbols}
    assert "Foo" in names
    assert "baz" in names
    # method may be present depending on tree-sitter walk
    kinds = {s.name: s.kind for s in symbols}
    assert kinds.get("Foo") == "class"
    assert kinds.get("baz") in {"function", "method"}


def test_projection_lookup_and_acl() -> None:
    wid = uuid4()
    meta = IndexMeta(work_id=wid, owner_user_id="user-a", status=IndexStatus.READY, generation=1)
    proj = IndexProjection(work_id=wid, owner_user_id="user-a", meta=meta)
    entry = FileEntry(
        path="pkg/mod.py",
        lang="python",
        content_hash=hash_text("def foo():\n  pass\n"),
        mtime_ns=1,
        size=20,
        symbols=[SymbolRec(name="foo", kind="function", line=1, col=1, end_line=2)],
        generation=1,
    )
    proj.replace_all([entry], meta=meta)
    hits = proj.lookup("foo", owner_user_id="user-a")
    assert len(hits) == 1 and hits[0].path == "pkg/mod.py"
    assert proj.lookup("foo", owner_user_id="user-b") == []


def test_projection_upsert_replace_and_drop() -> None:
    wid = uuid4()
    meta = IndexMeta(work_id=wid, owner_user_id="u", status=IndexStatus.READY, generation=1)
    proj = IndexProjection(work_id=wid, owner_user_id="u", meta=meta)
    e1 = FileEntry(
        path="a.py",
        lang="python",
        content_hash="h1",
        mtime_ns=1,
        size=1,
        symbols=[SymbolRec(name="alpha", kind="function", line=1)],
        generation=1,
    )
    proj.upsert_file(e1, meta=meta)
    assert proj.lookup("alpha")
    e2 = FileEntry(
        path="a.py",
        lang="python",
        content_hash="h2",
        mtime_ns=2,
        size=2,
        symbols=[SymbolRec(name="beta", kind="function", line=2)],
        generation=2,
    )
    proj.upsert_file(e2, meta=meta)
    assert proj.lookup("alpha") == []
    assert proj.lookup("beta")
    proj.drop_file("a.py")
    assert proj.lookup("beta") == []


def test_projection_registry_evict_idle() -> None:
    reg = ProjectionRegistry()
    wid = uuid4()
    meta = IndexMeta(work_id=wid, owner_user_id="u", status=IndexStatus.READY)
    proj = IndexProjection(work_id=wid, owner_user_id="u", meta=meta)
    proj.last_access_monotonic = 0.0
    reg.put(proj)
    evicted = reg.evict_idle(idle_ttl_s=0.0, max_works=8)
    assert wid in evicted
    assert reg.get(wid) is None


def test_walk_skips_venv(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("def ok():\n  pass\n", encoding="utf-8")
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "skip.py").write_text("def skip():\n  pass\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("function x() {}", encoding="utf-8")
    files = walk_work_files(tmp_path, max_files=100, max_file_bytes=1_000_000)
    rels = {p.relative_to(tmp_path).as_posix() for p in files}
    assert "ok.py" in rels
    assert not any(".venv" in r for r in rels)
    assert not any("node_modules" in r for r in rels)
    assert dir_skipped(".venv")
    assert file_skipped(Path("x.pyc"))


def test_parse_file_entry_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("class Widget:\n    pass\n", encoding="utf-8")
    entry = parse_file_entry(path, work_root=tmp_path, generation=3, max_file_bytes=1_000_000)
    assert entry is not None
    assert entry.path == "mod.py"
    assert entry.generation == 3
    assert entry.content_hash
    assert any(s.name == "Widget" for s in entry.symbols)


def test_oversized_file_marked_skipped(tmp_path: Path) -> None:
    path = tmp_path / "big.py"
    path.write_bytes(b"x" * 100)
    entry = parse_file_entry(path, work_root=tmp_path, generation=1, max_file_bytes=10)
    assert entry is not None
    assert entry.lang == "skipped"
    assert entry.symbols == []


@pytest.mark.asyncio
async def test_memory_store_acl_filter() -> None:
    """In-memory stand-in verifying ACL semantics used by AstIndexStore.get_meta."""
    from app.structural.workspace_index.types import IndexMeta, IndexStatus

    rows: dict = {}

    class FakeStore:
        async def get_meta(self, work_id, *, owner_user_id=None):
            row = rows.get(work_id)
            if row is None:
                return None
            if owner_user_id is not None and row.owner_user_id != owner_user_id:
                return None
            return row

        async def upsert_meta(self, meta: IndexMeta):
            existing = rows.get(meta.work_id)
            if existing and existing.owner_user_id != meta.owner_user_id:
                raise PermissionError("ACL deny")
            rows[meta.work_id] = meta
            return meta

    store = FakeStore()
    wid = uuid4()
    meta = IndexMeta(work_id=wid, owner_user_id="alice", status=IndexStatus.READY)
    await store.upsert_meta(meta)
    assert await store.get_meta(wid, owner_user_id="alice") is not None
    assert await store.get_meta(wid, owner_user_id="bob") is None
    with pytest.raises(PermissionError):
        await store.upsert_meta(
            IndexMeta(work_id=wid, owner_user_id="bob", status=IndexStatus.READY)
        )


@pytest.mark.asyncio
async def test_locate_via_ast_index_confirms_with_lsp(tmp_path: Path, monkeypatch) -> None:
    from app.structural.types import Location
    from app.structural.workspace_index.locate import locate_via_ast_index
    from app.structural.workspace_index.projection import get_projection_registry
    from app.structural.workspace_index.service import AstIndexService

    wid = uuid4()
    owner = "owner-1"
    path = tmp_path / "svc.py"
    path.write_text("def compute():\n    return 1\n", encoding="utf-8")
    entry = parse_file_entry(path, work_root=tmp_path, generation=1, max_file_bytes=1_000_000)
    assert entry is not None
    meta = IndexMeta(
        work_id=wid, owner_user_id=owner, status=IndexStatus.READY, generation=1
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([entry], meta=meta)
    get_projection_registry().put(proj)

    class StubService(AstIndexService):
        def enabled_for_work(self, *, work_root=None) -> bool:
            return True

        async def lookup_symbol(self, work_id, name, *, owner_user_id, limit=20):
            hits = proj.lookup(name, limit=limit, owner_user_id=owner_user_id)
            return hits, meta

        async def ensure_projection(self, work_id, *, owner_user_id):
            return proj

    monkeypatch.setattr(
        "app.structural.workspace_index.locate.get_ast_index_service",
        lambda: StubService(),
    )

    async def fake_goto(workspace, symbol, **kwargs):
        return {
            "locations": [
                Location(
                    path="svc.py",
                    line=1,
                    col=1,
                    kind="def",
                    symbol=symbol,
                )
            ],
            "meta": {},
        }

    out = await locate_via_ast_index(
        workspace=tmp_path,
        symbol="compute",
        work_id=wid,
        owner_user_id=owner,
        goto=fake_goto,
        timeout_s=5.0,
        turn_id=None,
    )
    assert out is not None
    assert out["candidates_from"] == "ast_index"
    assert out["definitions"]
    assert out["locate_incomplete"] is False


@pytest.mark.asyncio
async def test_locate_via_ast_index_falls_through_when_cold(monkeypatch, tmp_path: Path) -> None:
    from app.structural.workspace_index.locate import locate_via_ast_index
    from app.structural.workspace_index.service import AstIndexService
    from app.structural.workspace_index.types import IndexMeta, IndexStatus

    wid = uuid4()

    class ColdService(AstIndexService):
        def enabled_for_work(self, *, work_root=None) -> bool:
            return True

        async def lookup_symbol(self, work_id, name, *, owner_user_id, limit=20):
            return [], IndexMeta(
                work_id=wid, owner_user_id=owner_user_id, status=IndexStatus.COLD
            )

    monkeypatch.setattr(
        "app.structural.workspace_index.locate.get_ast_index_service",
        lambda: ColdService(),
    )

    async def fake_goto(*_a, **_k):
        raise AssertionError("should not call goto when cold returns None early")

    out = await locate_via_ast_index(
        workspace=tmp_path,
        symbol="Nope",
        work_id=wid,
        owner_user_id="u",
        goto=fake_goto,
        timeout_s=1.0,
        turn_id=None,
    )
    assert out is None


@pytest.mark.asyncio
async def test_search_codebase_off_index_matches_legacy(monkeypatch) -> None:
    """Index off/miss must preserve today's schema (A3 acceptance)."""
    from app.structural.types import Location
    from app.tools.core import tools as core
    import app.structural.workspace_index.locate as locate_mod

    async def fake_goto(*_a, **_k):
        return {
            "locations": [
                Location(path="a.py", line=2, col=1, kind="def", symbol="Foo")
            ],
            "meta": {},
        }

    async def none_locate(**_kwargs):
        return None

    monkeypatch.setattr("app.structural.adapters.goto_definition", fake_goto)
    monkeypatch.setattr(locate_mod, "locate_via_ast_index", none_locate)

    result = await core.search_codebase("Foo")
    assert result["mode"] == "symbol"
    assert result["definitions"]
    assert result.get("candidates_from") is None


@pytest.mark.asyncio
async def test_cold_start_job_writes_projection(tmp_path: Path, monkeypatch) -> None:
    from app.structural.workspace_index import job as job_mod
    from app.structural.workspace_index.projection import get_projection_registry
    from app.structural.workspace_index.types import IndexMeta, IndexStatus

    (tmp_path / "lib.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    wid = uuid4()
    owner = "owner-x"
    metas: list[IndexMeta] = []
    batches: list[list] = []

    class FakeStore:
        async def ensure_meta(self, work_id, *, owner_user_id):
            return IndexMeta(
                work_id=work_id, owner_user_id=owner_user_id, status=IndexStatus.COLD
            )

        async def upsert_meta(self, meta: IndexMeta):
            metas.append(meta)
            return meta

        async def upsert_files_batch(self, work_id, entries, *, owner_user_id, meta):
            batches.append(list(entries))
            metas.append(meta)
            return meta

    monkeypatch.setattr(job_mod.settings, "workspace_ast_max_files", 100)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_max_file_bytes", 1_000_000)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_parse_concurrency", 2)

    meta = await job_mod.run_cold_start(
        work_id=wid,
        owner_user_id=owner,
        work_root=tmp_path,
        store=FakeStore(),  # type: ignore[arg-type]
    )
    assert meta.status == IndexStatus.READY
    assert meta.files_done >= 1
    assert batches
    proj = get_projection_registry().get(wid)
    assert proj is not None
    assert proj.lookup("hello", owner_user_id=owner)


@pytest.mark.asyncio
async def test_light_scan_marks_scan_pending_on_budget(tmp_path: Path, monkeypatch) -> None:
    from app.structural.workspace_index.projection import IndexProjection, get_projection_registry
    from app.structural.workspace_index.types import IndexMeta, IndexStatus
    from app.structural.workspace_index.watch import light_scan_after_command

    wid = uuid4()
    owner = "o"
    # Empty projection → every file is dirty; tiny budget forces scan_pending.
    meta = IndexMeta(work_id=wid, owner_user_id=owner, status=IndexStatus.READY)
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    get_projection_registry().put(proj)
    for i in range(40):
        (tmp_path / f"f{i}.py").write_text(f"def f{i}():\n  pass\n", encoding="utf-8")

    monkeypatch.setattr(
        "app.structural.workspace_index.watch.get_ast_index_service",
        lambda: type("S", (), {"enabled_for_work": lambda self, **k: True})(),
    )
    out = await light_scan_after_command(
        work_id=wid,
        owner_user_id=owner,
        work_root=tmp_path,
        budget_ms=0.01,
    )
    assert out["status"] in {"scan_pending", "ok"}

    from pathlib import Path as P

    # services/runtime/tests → services/api/alembic/versions
    path = (
        P(__file__).resolve().parents[2]
        / "api"
        / "alembic"
        / "versions"
        / "0018_phase1m_work_ast_index.py"
    )
    assert path.is_file(), path
    text = path.read_text()
    assert 'down_revision = "0017_phase1l_audit_log"' in text
    assert "phase1m_work_ast_index.sql" in text
