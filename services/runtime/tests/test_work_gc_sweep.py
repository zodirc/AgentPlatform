"""清扫、比较并交换、复活和墓碑。断言的是零删除和 deleted 不重复计数。"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.policy.shadow_git import _git, ensure_turn_baseline, restore_turn, shadow_dir
from app.policy.work_gc import _compress, mark_work


class _Conn:
    def __init__(self, *, locked=True, fresh=False):
        self.locked = locked
        self.fresh = fresh
        self.args: list[tuple] = []

    async def execute(self, sql: str, *args):
        self.args.append(args)

    async def fetchrow(self, sql: str, *_args):
        return None

    async def fetch(self, sql: str, *_args):
        return []

    async def fetchval(self, sql: str, *_args):
        if "pg_try_advisory_lock" in sql or "pg_advisory_unlock" in sql:
            return self.locked
        return self.fresh


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _Facts:
    def __init__(self, *, work_exists: bool, deleted_at, now: datetime):
        self.work_exists = work_exists
        self.deleted_at = deleted_at
        self.now = now
        self.sql: list[str] = []

    def transaction(self, **_kwargs):
        return _Tx()

    async def execute(self, sql: str, *_args):
        self.sql.append(" ".join(sql.split()))

    async def fetch(self, sql: str, *_args):
        return []

    async def fetchrow(self, sql: str, *_args):
        if "work_tombstones" in sql and self.deleted_at is not None:
            return {"deleted_at": self.deleted_at}
        return None

    async def fetchval(self, sql: str, *_args):
        if "pg_try_advisory_lock" in sql or "pg_advisory_unlock" in sql:
            return True
        if "now()" in sql:
            return self.now
        if "FROM works" in sql:
            return self.work_exists
        if "FROM runs" in sql:
            return False
        return False


def _age_objects(work: Path) -> None:
    objects = shadow_dir(work) / "objects"
    old = time.time() - 7200
    if not objects.is_dir():
        return
    for path in objects.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))


def _reachable(work: Path) -> int:
    proc = _git(work, "rev-list", "--objects", "--all")
    assert proc.returncode == 0, proc.stderr
    return len([line for line in proc.stdout.splitlines() if line.strip()])


def _old(path: Path) -> None:
    stamp = time.time() - 7200
    os.utime(path, (stamp, stamp))


@pytest.mark.asyncio
async def test_out_of_window_tag_gc_drops_objects_and_in_window_restore_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "old.txt").write_text("old-only", encoding="utf-8")
    assert ensure_turn_baseline(work, turn_id="old")
    (work / "old.txt").unlink()
    (work / "keep.txt").write_text("keep-only", encoding="utf-8")
    assert ensure_turn_baseline(work, turn_id="keep")
    before = _reachable(work)
    real = _compress

    def aged(root: Path):
        _age_objects(root)
        return real(root)

    monkeypatch.setattr("app.policy.work_gc._compress", aged)
    report = await mark_work(
        _Conn(fresh=False),
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids={"keep"},
    )
    assert report.aborted in (None, "")
    assert report.deleted >= 1
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/old").returncode != 0
    assert _reachable(work) < before
    restored = restore_turn(work, turn_id="keep")
    assert "keep.txt" in restored
    assert (work / "keep.txt").read_text(encoding="utf-8") == "keep-only"


@pytest.mark.asyncio
async def test_tag_created_after_the_list_is_not_deleted(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    assert ensure_turn_baseline(work, turn_id="old")
    from app.policy import work_gc as wg

    real = wg.list_turn_tags

    def late(root: Path):
        listed = real(root)
        (root / "b.txt").write_text("b", encoding="utf-8")
        assert ensure_turn_baseline(root, turn_id="new")
        return listed

    wg.list_turn_tags = late
    try:
        report = await mark_work(
            _Conn(fresh=True),
            work_id=str(uuid4()),
            work_root=work,
            live_turn_ids=set(),
        )
    finally:
        wg.list_turn_tags = real
    assert report.deleted >= 1
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/new").returncode == 0
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/old").returncode != 0


@pytest.mark.asyncio
async def test_cas_delete_failure_keeps_the_tag_and_recorded(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    assert ensure_turn_baseline(work, turn_id="old")
    recorded = shadow_dir(work) / "recorded" / "old"
    recorded.write_text("pre", encoding="utf-8")
    _old(recorded)
    monkeypatch.setattr("app.policy.work_gc.cas_delete_tag", lambda *_a, **_k: False)
    report = await mark_work(
        _Conn(fresh=True),
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids=set(),
    )
    assert report.deleted == 0
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/old").returncode == 0
    assert recorded.read_text(encoding="utf-8") == "pre"


@pytest.mark.asyncio
async def test_non_terminal_run_sweeps_outside_the_window_and_skips_compress(
    tmp_path: Path, monkeypatch
) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    assert ensure_turn_baseline(work, turn_id="keep")
    (work / "b.txt").write_text("b", encoding="utf-8")
    assert ensure_turn_baseline(work, turn_id="old")

    def fail_compress(_root: Path) -> str:
        raise AssertionError("compress")

    monkeypatch.setattr("app.policy.work_gc._compress", fail_compress)
    report = await mark_work(
        _Conn(fresh=True),
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids={"keep"},
    )
    assert report.aborted is None
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/keep").returncode == 0
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/old").returncode != 0


def test_rewritten_blob_survives_prune(tmp_path: Path) -> None:
    from app.policy.shadow_git import _ensure_repo

    work = tmp_path / "book"
    work.mkdir()
    _ensure_repo(work)
    blob = work / "same.txt"
    blob.write_text("same-bytes", encoding="utf-8")
    first = _git(work, "hash-object", "-w", "--", str(blob))
    assert first.returncode == 0
    sha = first.stdout.strip()
    _age_objects(work)
    again = _git(work, "hash-object", "-w", "--", str(blob))
    assert again.stdout.strip() == sha
    assert _compress(work) is None
    kind = _git(work, "cat-file", "-t", sha)
    assert kind.stdout.strip() == "blob"


@pytest.mark.asyncio
async def test_rerun_does_not_count_deleted_again(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    assert ensure_turn_baseline(work, turn_id="old")
    conn = _Conn(fresh=True)
    first = await mark_work(
        conn,
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids=set(),
    )
    assert first.deleted == 1
    second = await mark_work(
        conn,
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids=set(),
    )
    assert second.deleted == 0
    deleted_counts = [args[3] for args in conn.args if len(args) == 4]
    assert deleted_counts == [1, 0]


@pytest.mark.asyncio
async def test_tombstone_past_grace_removes_the_directory_and_the_row(tmp_path: Path) -> None:
    from app.policy.shadow_git import _ensure_repo

    work = tmp_path / "book"
    work.mkdir()
    _ensure_repo(work)
    (work / "a.txt").write_text("a", encoding="utf-8")
    now = datetime.now(timezone.utc)
    conn = _Facts(work_exists=False, deleted_at=now - timedelta(hours=2), now=now)
    report = await mark_work(
        conn,
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids=set(),
        load_roots=True,
    )
    assert not work.exists()
    assert any("DELETE FROM work_tombstones" in sql for sql in conn.sql)
    assert report.aborted in (None, "")


@pytest.mark.asyncio
async def test_directory_without_tombstone_or_work_row_stays(tmp_path: Path) -> None:
    from app.policy.shadow_git import _ensure_repo

    work = tmp_path / "book"
    work.mkdir()
    _ensure_repo(work)
    (work / "a.txt").write_text("a", encoding="utf-8")
    now = datetime.now(timezone.utc)
    conn = _Facts(work_exists=False, deleted_at=None, now=now)
    await mark_work(
        conn,
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids=set(),
        load_roots=True,
    )
    assert work.is_dir()
    assert not any("DELETE FROM work_tombstones" in sql for sql in conn.sql)


@pytest.mark.asyncio
async def test_quarantine_ttl_or_missing_owner_deletes_and_fresh_mtime_stays(tmp_path: Path) -> None:
    from app.policy.shadow_git import _ensure_repo

    work = tmp_path / "book"
    work.mkdir()
    _ensure_repo(work)
    (work / "a.txt").write_text("a", encoding="utf-8")
    root = tmp_path / "quarantine"
    root.mkdir()
    now = datetime.now(timezone.utc)
    expired = root / "gone.json"
    expired.write_text(
        json.dumps({"turn_id": "t-old", "expires_at": time.time() - 10}),
        encoding="utf-8",
    )
    blob = root / "gone.bin"
    blob.write_text("x", encoding="utf-8")
    _old(expired)
    _old(blob)
    fresh = root / "fresh.json"
    fresh.write_text(
        json.dumps({"turn_id": "t-new", "expires_at": time.time() - 10}),
        encoding="utf-8",
    )
    missing = root / "miss.json"
    missing.write_text(
        json.dumps({"turn_id": "t-missing", "expires_at": time.time() + 86400}),
        encoding="utf-8",
    )
    miss_bin = root / "miss.bin"
    miss_bin.write_text("y", encoding="utf-8")
    _old(missing)
    _old(miss_bin)

    class _Owners(_Facts):
        async def fetchval(self, sql: str, *args):
            if "FROM turns" in sql:
                return args[0] == "t-live"
            return await _Facts.fetchval(self, sql, *args)

    await mark_work(
        _Owners(work_exists=True, deleted_at=None, now=now),
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids=set(),
        load_roots=True,
        quarantine_root=root,
    )
    assert not expired.exists()
    assert not blob.exists()
    assert fresh.exists()
    assert not missing.exists()
    assert not miss_bin.exists()
