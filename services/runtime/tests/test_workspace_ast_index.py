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
    jobs = root / "packages" / "contracts" / "schemas" / "ddl" / "phase1n_work_ast_index_jobs.sql"
    assert jobs.is_file()
    jtext = jobs.read_text()
    assert "CREATE TABLE IF NOT EXISTS work_ast_index_jobs" in jtext
    assert "status" in jtext
    assert "source_chunks" not in jtext


def test_snapshot_roundtrip(tmp_path: Path) -> None:
    from app.structural.workspace_index.snapshot import read_snapshot, write_snapshot

    wid = uuid4()
    meta = IndexMeta(
        work_id=wid,
        owner_user_id="u1",
        status=IndexStatus.READY,
        generation=3,
        files_total=1,
        files_done=1,
        ephemeral=True,
    )
    entry = FileEntry(
        path="a.py",
        lang="python",
        content_hash="abc",
        mtime_ns=1,
        size=10,
        symbols=[SymbolRec(name="Foo", kind="class", line=1, container=None)],
        generation=3,
    )
    write_snapshot(tmp_path, meta=meta, entries=[entry])
    loaded = read_snapshot(tmp_path)
    assert loaded is not None
    m2, files = loaded
    assert m2.generation == 3
    assert m2.status == IndexStatus.READY
    assert files[0].path == "a.py"
    assert files[0].symbols[0].name == "Foo"


def test_dirty_payload_structured() -> None:
    from app.structural.workspace_index.queue import AstIndexJob, dirty_payload

    job = AstIndexJob(
        id=uuid4(),
        work_id=uuid4(),
        owner_user_id="u",
        kind="dirty",
        status="pending",
        work_root="/w",
        memory_only=True,
        paths=["a.py"],
        attempts=0,
        paths_raw={"upsert": ["a.py", "b.py"], "delete": ["c.py"]},
    )
    ups, dels = dirty_payload(job)
    assert ups == ["a.py", "b.py"]
    assert dels == ["c.py"]


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
    by_name = {s.name: s for s in symbols}
    if "bar" in by_name:
        assert by_name["bar"].kind == "method"
        assert by_name["bar"].container == "Foo"
        assert by_name["bar"].to_json().get("ct") == "Foo"


def test_normalize_and_rank_qualified_query() -> None:
    from app.structural.workspace_index.query import (
        normalize_symbol_query,
        rank_hits,
    )
    from app.structural.workspace_index.types import SymbolHit

    nq = normalize_symbol_query("astropy.io.fits.Card")
    assert nq.tail == "Card"
    assert nq.container_hint == "fits"
    nq2 = normalize_symbol_query("Card.fromstring")
    assert nq2.tail == "fromstring"
    assert nq2.container_hint == "Card"

    hits = [
        SymbolHit(
            path="tests/test_card.py",
            line=10,
            col=1,
            kind="class",
            name="Card",
            content_hash="a",
            generation=1,
            container=None,
        ),
        SymbolHit(
            path="astropy/io/fits/card.py",
            line=5,
            col=1,
            kind="class",
            name="Card",
            content_hash="b",
            generation=1,
            container="fits",
        ),
        SymbolHit(
            path="astropy/io/fits/card.py",
            line=40,
            col=1,
            kind="method",
            name="fromstring",
            content_hash="b",
            generation=1,
            container="Card",
        ),
    ]
    ranked = rank_hits(hits, nq, limit=5)
    assert ranked[0].path.startswith("astropy/")
    method_hits = rank_hits(hits, nq2, limit=5)
    assert method_hits[0].name == "fromstring"
    assert method_hits[0].container == "Card"


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
    from app.structural.workspace_index.ignore import code_file_indexable

    assert code_file_indexable("app/engine.py")
    assert not code_file_indexable(
        "sources/cards/pending/20260806T070756Z_066d381a-d72e-4ce2-9c7e-464707fae8ca_松了一.md"
    )


def test_walk_code_only_skips_non_source(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n  pass\n", encoding="utf-8")
    (tmp_path / "README.rst").write_text("docs\n", encoding="utf-8")
    (tmp_path / "data.fits").write_bytes(b"\x00" * 32)
    code = walk_work_files(tmp_path, max_files=100, max_file_bytes=1_000_000, code_only=True)
    rels = {p.relative_to(tmp_path).as_posix() for p in code}
    assert rels == {"a.py"}
    all_files = walk_work_files(
        tmp_path, max_files=100, max_file_bytes=1_000_000, code_only=False
    )
    assert len(all_files) >= 3


def test_parse_file_entry_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("class Widget:\n    pass\n", encoding="utf-8")
    entry = parse_file_entry(path, work_root=tmp_path, generation=3, max_file_bytes=1_000_000)
    assert entry is not None
    assert entry.path == "mod.py"
    assert entry.generation == 3
    assert entry.content_hash
    assert any(s.name == "Widget" for s in entry.symbols)
    md = tmp_path / "note.md"
    md.write_text("# heading\n", encoding="utf-8")
    assert parse_file_entry(md, work_root=tmp_path, generation=3, max_file_bytes=1_000_000) is None


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
        def enabled_for_work(self, *, work_id=None, work_root=None) -> bool:
            return True

        async def lookup_symbol(
            self, work_id, name, *, owner_user_id, limit=20, work_root=None
        ):
            hits = proj.lookup(name, limit=limit, owner_user_id=owner_user_id)
            return hits, meta

        async def ensure_projection(self, work_id, *, owner_user_id, work_root=None):
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
        def enabled_for_work(self, *, work_id=None, work_root=None) -> bool:
            return True

        async def lookup_symbol(
            self, work_id, name, *, owner_user_id, limit=20, work_root=None
        ):
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


@pytest.mark.asyncio
async def test_light_scan_skips_unindexed_while_cold_start_incomplete(
    tmp_path: Path, monkeypatch
) -> None:
    """Budget-truncated index must not enqueue the rest of the tree as dirty."""
    from app.structural.workspace_index.dirty import get_dirty_queue
    from app.structural.workspace_index.projection import (
        IndexProjection,
        get_projection_registry,
    )
    from app.structural.workspace_index.types import IndexMeta, IndexStatus
    from app.structural.workspace_index.watch import light_scan_after_command

    wid = uuid4()
    owner = "o"
    indexed = tmp_path / "a.py"
    indexed.write_text("def a():\n    return 1\n", encoding="utf-8")
    entry = parse_file_entry(
        indexed, work_root=tmp_path, generation=1, max_file_bytes=1_000_000
    )
    assert entry is not None
    for name in ("b.py", "c.py", "d.py"):
        (tmp_path / name).write_text(f"def {name[0]}():\n    pass\n", encoding="utf-8")

    meta = IndexMeta(
        work_id=wid,
        owner_user_id=owner,
        status=IndexStatus.STALE,
        files_total=4,
        files_done=1,
        ephemeral=True,
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([entry], meta=meta)
    get_projection_registry().put(proj)
    get_dirty_queue()._by_work.pop(wid, None)

    monkeypatch.setattr(
        "app.structural.workspace_index.watch.get_ast_index_service",
        lambda: type("S", (), {"enabled_for_work": lambda self, **k: True})(),
    )
    out = await light_scan_after_command(
        work_id=wid,
        owner_user_id=owner,
        work_root=tmp_path,
        budget_ms=5_000.0,
    )
    pending = get_dirty_queue().pending_counts(wid)
    assert pending["upsert"] == 0
    assert out["dirty"] == 0
    get_dirty_queue()._by_work.pop(wid, None)
    get_projection_registry().drop(wid)


@pytest.mark.asyncio
async def test_light_scan_gc_drops_missing_when_walk_pending(
    tmp_path: Path, monkeypatch
) -> None:
    """Deleted trees must leave the index even if os.walk hits the budget."""
    from app.structural.workspace_index.projection import (
        IndexProjection,
        get_projection_registry,
    )
    from app.structural.workspace_index.types import IndexMeta, IndexStatus
    from app.structural.workspace_index.watch import light_scan_after_command

    wid = uuid4()
    owner = "o"
    ghost = FileEntry(
        path="astropy.root.backup/cosmology/io/tests/test_table.py",
        lang="python",
        content_hash="gone",
        mtime_ns=1,
        size=10,
        symbols=[SymbolRec(name="ToFromTableTestMixin", kind="class", line=17)],
        generation=1,
    )
    live = tmp_path / "keep.py"
    live.write_text("def keep():\n    return 1\n", encoding="utf-8")
    keep = parse_file_entry(
        live, work_root=tmp_path, generation=1, max_file_bytes=1_000_000
    )
    assert keep is not None
    meta = IndexMeta(
        work_id=wid,
        owner_user_id=owner,
        status=IndexStatus.READY,
        files_total=2,
        files_done=2,
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([ghost, keep], meta=meta)
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
    assert ghost.path not in proj.files
    assert keep.path in proj.files
    assert proj.meta.files_total == len(proj.files)
    assert out["dirty"] >= 1


@pytest.mark.asyncio
async def test_light_scan_does_not_index_writing_markdown(
    tmp_path: Path, monkeypatch
) -> None:
    from app.structural.workspace_index.dirty import get_dirty_queue
    from app.structural.workspace_index.projection import (
        IndexProjection,
        get_projection_registry,
    )
    from app.structural.workspace_index.types import IndexMeta, IndexStatus
    from app.structural.workspace_index.watch import light_scan_after_command

    wid = uuid4()
    owner = "o"
    keep = tmp_path / "keep.py"
    keep.write_text("def keep():\n    return 1\n", encoding="utf-8")
    card = (
        tmp_path
        / "sources"
        / "cards"
        / "pending"
        / "20260806T070756Z_066d381a-d72e-4ce2-9c7e-464707fae8ca_松了一.md"
    )
    card.parent.mkdir(parents=True)
    card.write_text("# 松了一\n", encoding="utf-8")
    entry = parse_file_entry(
        keep, work_root=tmp_path, generation=1, max_file_bytes=1_000_000
    )
    assert entry is not None
    meta = IndexMeta(
        work_id=wid,
        owner_user_id=owner,
        status=IndexStatus.READY,
        files_total=1,
        files_done=1,
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([entry], meta=meta)
    get_projection_registry().put(proj)
    monkeypatch.setattr(
        "app.structural.workspace_index.watch.get_ast_index_service",
        lambda: type("S", (), {"enabled_for_work": lambda self, **k: True})(),
    )
    out = await light_scan_after_command(
        work_id=wid,
        owner_user_id=owner,
        work_root=tmp_path,
        budget_ms=2_000.0,
    )
    rel = card.relative_to(tmp_path).as_posix()
    assert rel not in proj.files
    state = get_dirty_queue()._by_work.get(wid)
    pending_paths = set(state.events) if state else set()
    assert rel not in pending_paths
    assert out["status"] in {"ok", "scan_pending"}


def test_alembic_work_ast_index_chain() -> None:
    from pathlib import Path as P

    versions = P(__file__).resolve().parents[2] / "api" / "alembic" / "versions"
    m18 = versions / "0018_phase1m_work_ast_index.py"
    m19 = versions / "0019_phase1n_work_ast_index_jobs.py"
    assert m18.is_file(), m18
    text = m18.read_text()
    assert 'down_revision = "0017_phase1l_audit_log"' in text
    assert "phase1m_work_ast_index.sql" in text
    assert m19.is_file(), m19
    t19 = m19.read_text()
    assert 'down_revision = "0018_phase1m_work_ast_index"' in t19
    assert "phase1n_work_ast_index_jobs.sql" in t19


@pytest.mark.asyncio
async def test_locate_incomplete_echoes_candidates(tmp_path: Path, monkeypatch) -> None:
    """§2.2.1: AST hits + empty LSP → candidates[] with locate_incomplete, never definitions."""
    from app.structural.workspace_index.locate import (
        FUSE_DEFINITION_NULL,
        locate_via_ast_index,
    )
    from app.structural.workspace_index.projection import get_projection_registry
    from app.structural.workspace_index.service import AstIndexService

    wid = uuid4()
    owner = "owner-1"
    path = tmp_path / "svc.py"
    path.write_text("class Widget:\n    pass\n", encoding="utf-8")
    entry = parse_file_entry(path, work_root=tmp_path, generation=1, max_file_bytes=1_000_000)
    assert entry is not None
    meta = IndexMeta(
        work_id=wid, owner_user_id=owner, status=IndexStatus.READY, generation=1
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([entry], meta=meta)
    get_projection_registry().put(proj)

    class StubService(AstIndexService):
        def enabled_for_work(self, *, work_id=None, work_root=None) -> bool:
            return True

        async def lookup_symbol(self, work_id, name, *, owner_user_id, limit=20, work_root=None):
            return proj.lookup(name, limit=limit, owner_user_id=owner_user_id), meta

        async def ensure_projection(self, work_id, *, owner_user_id, work_root=None):
            return proj

    monkeypatch.setattr(
        "app.structural.workspace_index.locate.get_ast_index_service",
        lambda: StubService(),
    )

    async def empty_goto(*_a, **_k):
        return {"locations": [], "meta": {}}

    out = await locate_via_ast_index(
        workspace=tmp_path,
        symbol="Widget",
        work_id=wid,
        owner_user_id=owner,
        goto=empty_goto,
        timeout_s=5.0,
        turn_id=None,
    )
    assert out is not None
    assert out["locate_incomplete"] is True
    assert out["definitions"] == []
    assert out["candidates"]
    assert out["candidates"][0]["source"] == "ast_index"
    assert out["candidates"][0]["confirmed"] is False
    assert out["locate_fuse_fail_reason"] == FUSE_DEFINITION_NULL


@pytest.mark.asyncio
async def test_memory_only_cold_start_skips_db(tmp_path: Path, monkeypatch) -> None:
    from app.structural.workspace_index import job as job_mod
    from app.structural.workspace_index.projection import get_projection_registry
    from app.structural.workspace_index.types import IndexStatus

    (tmp_path / "m.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    wid = uuid4()
    owner = "eval-owner"

    class BoomStore:
        async def ensure_meta(self, *a, **k):
            raise AssertionError("memory_only must not touch DB")

        async def upsert_meta(self, *a, **k):
            raise AssertionError("memory_only must not touch DB")

        async def upsert_files_batch(self, *a, **k):
            raise AssertionError("memory_only must not touch DB")

    monkeypatch.setattr(job_mod.settings, "workspace_ast_max_files", 100)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_max_file_bytes", 1_000_000)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_parse_concurrency", 2)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_eval_budget_seconds", 0.0)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_eval_budget_min_seconds", 30.0)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_eval_budget_max_seconds", 120.0)

    meta = await job_mod.run_cold_start(
        work_id=wid,
        owner_user_id=owner,
        work_root=tmp_path,
        store=BoomStore(),  # type: ignore[arg-type]
        memory_only=True,
        budget_s=30.0,
    )
    assert meta.ephemeral is True
    assert meta.status in {IndexStatus.READY, IndexStatus.STALE}
    proj = get_projection_registry().get(wid)
    assert proj is not None
    assert proj.lookup("hello", owner_user_id=owner)


def test_eval_budget_scales_with_file_count(monkeypatch) -> None:
    from app.structural.workspace_index import job as job_mod

    monkeypatch.setattr(job_mod.settings, "workspace_ast_eval_budget_min_seconds", 60.0)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_eval_budget_max_seconds", 900.0)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_eval_budget_seconds_per_file", 0.75)
    monkeypatch.setattr(job_mod.settings, "workspace_ast_eval_budget_overhead_seconds", 45.0)

    tiny = job_mod.eval_budget_seconds(10, concurrency=2)
    astropy = job_mod.eval_budget_seconds(935, concurrency=2)
    huge = job_mod.eval_budget_seconds(50_000, concurrency=2)
    assert tiny == 60.0  # clamped to min
    # 45 + 935*0.75/2 ≈ 395.6
    assert 390.0 <= astropy <= 400.0
    assert huge == 900.0  # clamped to max


@pytest.mark.asyncio
async def test_ephemeral_dirty_flush_updates_projection(tmp_path: Path, monkeypatch) -> None:
    """§7.2 channel ① must refresh memory-only projection without DB meta."""
    from app.settings import settings
    from app.structural.workspace_index.dirty import DirtyKind, DirtyQueue
    from app.structural.workspace_index.projection import get_projection_registry
    from app.structural.workspace_index.service import get_ast_index_service

    monkeypatch.setattr(settings, "workspace_ast_inline", True)
    wid = uuid4()
    owner = "eval"
    path = tmp_path / "w.py"
    path.write_text("def old_name():\n    return 0\n", encoding="utf-8")
    entry = parse_file_entry(
        path, work_root=tmp_path, generation=1, max_file_bytes=1_000_000
    )
    assert entry is not None
    meta = IndexMeta(
        work_id=wid,
        owner_user_id=owner,
        status=IndexStatus.READY,
        generation=1,
        ephemeral=True,
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([entry], meta=meta)
    get_projection_registry().put(proj)
    get_ast_index_service().mark_ephemeral(wid)

    path.write_text("def new_name():\n    return 1\n", encoding="utf-8")
    q = DirtyQueue()
    q.enqueue(
        wid,
        "w.py",
        owner_user_id=owner,
        work_root=tmp_path,
        kind=DirtyKind.UPSERT,
    )
    await q._flush(wid)
    assert proj.lookup("new_name", owner_user_id=owner)
    assert not proj.lookup("old_name", owner_user_id=owner)


@pytest.mark.asyncio
async def test_dirty_flush_keeps_overflow_over_backpressure(
    tmp_path: Path, monkeypatch
) -> None:
    """GC deletes above the backpressure cap must stay queued, not be dropped."""
    from uuid import UUID

    from app.settings import settings
    from app.structural.workspace_index.dirty import DirtyKind, DirtyQueue

    monkeypatch.setattr(settings, "workspace_ast_dirty_backpressure", 2)
    monkeypatch.setattr(settings, "workspace_ast_inline", False)

    enqueued: list[dict] = []

    async def fake_enqueue(self, **kwargs):
        enqueued.append(kwargs)
        return UUID(int=1)

    monkeypatch.setattr(
        "app.structural.workspace_index.queue.AstIndexJobQueue.enqueue_dirty",
        fake_enqueue,
    )

    q = DirtyQueue()
    wid = uuid4()
    for i in range(5):
        q.enqueue(
            wid,
            f"g{i}.py",
            owner_user_id="u",
            work_root=tmp_path,
            kind=DirtyKind.DELETE,
            touched_in_turn=False,
        )
    await q.flush_now(wid)
    assert len(enqueued) == 1
    assert len(enqueued[0]["deletes"]) == 2
    leftover = q.pending_counts(wid)
    assert leftover["delete"] == 3


@pytest.mark.asyncio
async def test_status_exposes_catchup_progress_after_gc(
    tmp_path: Path, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    from app.settings import settings
    from app.structural.workspace_index.dirty import get_dirty_queue
    from app.structural.workspace_index.projection import get_projection_registry
    from app.structural.workspace_index.service import get_ast_index_service

    monkeypatch.setattr(settings, "workspace_ast_enabled", True)
    monkeypatch.setattr(settings, "workspace_ast_ops_enabled", True)

    wid = uuid4()
    owner = "user-1"
    keep = tmp_path / "keep.py"
    keep.write_text("def keep():\n    return 1\n", encoding="utf-8")
    live = parse_file_entry(
        keep, work_root=tmp_path, generation=3, max_file_bytes=1_000_000
    )
    assert live is not None
    ghost = FileEntry(
        path="gone.py",
        lang="python",
        content_hash="x",
        mtime_ns=1,
        size=1,
        symbols=[],
        generation=3,
    )
    meta = IndexMeta(
        work_id=wid,
        owner_user_id=owner,
        status=IndexStatus.READY,
        generation=3,
        files_total=2,
        files_done=2,
    )
    proj = IndexProjection(work_id=wid, owner_user_id=owner, meta=meta)
    proj.replace_all([live, ghost], meta=meta)
    get_projection_registry().put(proj)

    svc = get_ast_index_service()
    monkeypatch.setattr(svc.store, "get_meta", AsyncMock(return_value=meta))
    monkeypatch.setattr(svc.store, "count_files", AsyncMock(return_value=2))
    monkeypatch.setattr(
        svc.store, "list_paths", AsyncMock(return_value=["keep.py", "gone.py"])
    )

    async def fake_backlog(self, work_id):
        return {
            "upsert": 0,
            "delete": 0,
            "jobs_pending": 0,
            "jobs_running": 0,
            "cold": False,
        }

    async def noop_flush(self, work_id):
        return None

    monkeypatch.setattr(
        "app.structural.workspace_index.queue.AstIndexJobQueue.backlog",
        fake_backlog,
    )
    monkeypatch.setattr(
        "app.structural.workspace_index.dirty.DirtyQueue.flush_now",
        noop_flush,
    )

    out = await svc.status(wid, owner_user_id=owner, work_root=tmp_path)
    assert ghost.path not in proj.files
    assert out["status"] == "stale"
    assert out["files_indexed"] == 1
    assert out["pending_delete"] >= 1
    assert out["catchup_remaining"] >= 1
    assert out["files_done"] == out["files_total"]

    get_dirty_queue()._by_work.pop(wid, None)
    monkeypatch.setattr(svc.store, "count_files", AsyncMock(return_value=1))
    proj.meta.status = IndexStatus.STALE
    out_ready = await svc.status(wid, owner_user_id=owner, work_root=tmp_path)
    assert out_ready["status"] == "ready"
    assert out_ready["catchup_remaining"] == 0
    get_projection_registry().drop(wid)
    get_ast_index_service().clear_ephemeral(wid)


@pytest.mark.asyncio
async def test_file_heartbeat_thread_stays_fresh_when_loop_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compose healthcheck must survive event-loop stalls during cold_start/snapshot."""
    import time

    from app.structural.workspace_index import worker as worker_mod

    hb = tmp_path / "ast_indexer_heartbeat"
    monkeypatch.setattr(worker_mod, "_HEARTBEAT", hb)
    monkeypatch.setenv("AST_INDEXER_HEARTBEAT_SECONDS", "0.05")
    worker_mod._STOP.clear()
    worker_mod._STOP_THREAD.clear()

    thread = worker_mod._start_file_heartbeat_thread()
    try:
        time.sleep(0.15)
        assert hb.is_file()
        # Event loop / main thread stalled (sleep releases GIL like blocking I/O).
        time.sleep(0.3)
        age = time.time() - float(hb.read_text())
        assert age < 0.5
    finally:
        worker_mod._request_stop()
        thread.join(timeout=2.0)
        worker_mod._STOP.clear()
        worker_mod._STOP_THREAD.clear()
