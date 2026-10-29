"""Orphan shadow commits, revert window, and mark-only work_gc."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.policy.revert_window import RevertRefused, restore_turn_if_in_window
from app.policy.shadow_git import (
    _git,
    ensure_turn_baseline,
    restore_turn,
    snapshot_preimage,
)
from app.policy.work_gc import candidates_from_snapshot, list_turn_tags, mark_work


class _Conn:
    def __init__(self, *, row=None, rows=None, locked=True, fresh=False):
        self.row = row
        self.rows = rows or []
        self.locked = locked
        self.fresh = fresh
        self.sql: list[str] = []

    async def execute(self, sql: str, *_args):
        self.sql.append(" ".join(sql.split()))

    async def fetchrow(self, sql: str, *_args):
        self.sql.append(" ".join(sql.split()))
        return self.row

    async def fetch(self, sql: str, *_args):
        self.sql.append(" ".join(sql.split()))
        return self.rows

    async def fetchval(self, sql: str, *_args):
        self.sql.append(" ".join(sql.split()))
        if "pg_try_advisory_lock" in sql:
            return self.locked
        return self.fresh


def _parents(work: Path, sha: str) -> list[str]:
    proc = _git(work, "rev-list", "--parents", "-1", sha)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.split()


def test_turns_are_orphan_commits_and_gc_auto_is_off(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    first = ensure_turn_baseline(work, turn_id="t-1")
    assert first
    (work / "b.txt").write_text("b", encoding="utf-8")
    second = ensure_turn_baseline(work, turn_id="t-2")
    assert second
    assert _parents(work, first) == [first]
    assert _parents(work, second) == [second]
    auto = _git(work, "config", "--get", "gc.auto")
    assert auto.stdout.strip() == "0"
    head = _git(work, "rev-parse", "HEAD")
    assert head.returncode != 0 or head.stdout.strip() not in {first, second}


def test_cas_failure_leaves_the_moved_tag(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    original = ensure_turn_baseline(work, turn_id="t-1")
    assert original
    moved = ensure_turn_baseline(work, turn_id="other")
    assert moved
    from app.policy import shadow_git as sg

    real = sg._tag_sha

    def move_after_read(root: Path, turn_id: str) -> str | None:
        sha = real(root, turn_id)
        if turn_id == "t-1" and sha == original and not getattr(move_after_read, "done", False):
            move_after_read.done = True
            sg._git(root, "update-ref", "refs/tags/turn/t-1", moved, original)
        return sha

    (work / "c.txt").write_text("c", encoding="utf-8")
    with patch.object(sg, "_tag_sha", side_effect=move_after_read):
        assert snapshot_preimage(work, "c.txt", turn_id="t-1") is None
    stayed = _git(work, "rev-parse", "refs/tags/turn/t-1")
    assert stayed.stdout.strip() == moved


def test_mark_keeps_a_tag_created_after_the_list(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    ensure_turn_baseline(work, turn_id="old")
    listed = list_turn_tags(work)
    assert listed is not None
    ensure_turn_baseline(work, turn_id="new")
    names = candidates_from_snapshot(listed, live_turn_ids=set())
    assert "new" not in names
    assert "old" in names
    still = _git(work, "rev-parse", "--verify", "refs/tags/turn/new")
    assert still.returncode == 0
    restored = restore_turn(work, turn_id="old")
    assert "a.txt" in restored


@pytest.mark.asyncio
async def test_revert_outside_window_does_not_restore(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("kept", encoding="utf-8")
    turn_id = uuid4()
    work_id = uuid4()
    conn = _Conn(row={"scenario_id": "writing"}, rows=[])
    with patch("app.policy.shadow_git.restore_turn", side_effect=AssertionError("restored")):
        with pytest.raises(RevertRefused):
            await restore_turn_if_in_window(
                conn, work_id=work_id, turn_id=turn_id, work_root=work
            )
    assert (work / "a.txt").read_text(encoding="utf-8") == "kept"
    assert conn.sql[0].startswith("SELECT pg_advisory_xact_lock_shared")
    assert "LIMIT" in conn.sql[-1]


@pytest.mark.asyncio
async def test_coding_turn_outside_days_is_refused() -> None:
    conn = _Conn(row={"scenario_id": "agent"}, fresh=False)
    with patch("app.policy.shadow_git.restore_turn", side_effect=AssertionError("restored")):
        with pytest.raises(RevertRefused):
            await restore_turn_if_in_window(
                conn, work_id=uuid4(), turn_id=uuid4(), work_root=Path("/tmp")
            )


@pytest.mark.asyncio
async def test_mark_skips_when_exclusive_lock_is_held(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    ensure_turn_baseline(work, turn_id="t-1")
    report = await mark_work(
        _Conn(locked=False),
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids=set(),
    )
    assert report.skipped is True
    assert report.candidates == 0
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/t-1").returncode == 0


@pytest.mark.asyncio
async def test_mark_aborts_with_zero_candidates_when_the_root_is_unreadable(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    report = await mark_work(
        _Conn(locked=True),
        work_id=str(uuid4()),
        work_root=missing,
        live_turn_ids=set(),
    )
    assert report.aborted == "work_unreadable"
    assert report.candidates == 0


@pytest.mark.asyncio
async def test_mark_aborts_with_zero_candidates_when_listing_fails(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    conn = _Conn(locked=True)
    with patch("app.policy.work_gc.list_turn_tags", return_value=None):
        report = await mark_work(
            conn,
            work_id=str(uuid4()),
            work_root=work,
            live_turn_ids=set(),
        )
    assert report.aborted == "git_list_failed"
    assert report.candidates == 0
    assert any("INSERT INTO gc_runs" in sql for sql in conn.sql)


def test_tag_inside_grace_is_not_a_candidate() -> None:
    from datetime import datetime, timedelta, timezone

    from app.policy.work_gc import tag_is_candidate

    now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    assert tag_is_candidate(
        exists=False,
        terminal=True,
        in_window=False,
        updated_at=None,
        now=now,
    )
    assert not tag_is_candidate(
        exists=True,
        terminal=False,
        in_window=False,
        updated_at=now - timedelta(days=10),
        now=now,
    )
    assert not tag_is_candidate(
        exists=True,
        terminal=True,
        in_window=False,
        updated_at=now - timedelta(minutes=30),
        now=now,
    )
    assert tag_is_candidate(
        exists=True,
        terminal=True,
        in_window=False,
        updated_at=now - timedelta(hours=2),
        now=now,
    )


def test_roots_keep_grace_and_window_apart() -> None:
    from datetime import datetime, timedelta, timezone

    from app.policy.work_gc import roots_from_rows

    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    rows = [
        {
            "id": "new",
            "scenario_id": "writing",
            "updated_at": now - timedelta(days=2),
            "created_at": now,
            "busy": False,
        },
        {
            "id": "old",
            "scenario_id": "writing",
            "updated_at": now,
            "created_at": now - timedelta(days=3),
            "busy": False,
        },
        {
            "id": "stale",
            "scenario_id": "agent",
            "updated_at": now - timedelta(days=30),
            "created_at": now - timedelta(days=30),
            "busy": False,
        },
        {
            "id": "busy",
            "scenario_id": "agent",
            "updated_at": now - timedelta(days=30),
            "created_at": now - timedelta(days=30),
            "busy": True,
        },
    ]
    window, keep = roots_from_rows(rows, now=now, keep_turns=1, keep_days=7)
    assert window == {"new"}
    assert "old" in keep and "old" not in window
    assert "stale" not in keep
    assert "busy" in keep and "busy" not in window


def test_legacy_in_window_tag_becomes_an_orphan_and_keeps_its_tree(tmp_path: Path) -> None:
    from app.policy.shadow_git import _commit_tree, _ensure_repo
    from app.policy.work_gc import migrate_legacy_shadow

    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    _ensure_repo(work)
    base = ensure_turn_baseline(work, turn_id="keep")
    assert base
    tree = _git(work, "rev-parse", f"{base}^{{tree}}")
    child = _commit_tree(work, tree.stdout.strip(), "child", parent=base)
    assert child
    _git(work, "update-ref", "refs/tags/turn/keep", child)
    outside = ensure_turn_baseline(work, turn_id="outside")
    assert outside
    outside_tree = _git(work, "rev-parse", f"{outside}^{{tree}}")
    outside_child = _commit_tree(work, outside_tree.stdout.strip(), "out", parent=outside)
    assert outside_child
    _git(work, "update-ref", "refs/tags/turn/outside", outside_child)
    _git(work, "update-ref", "refs/heads/master", base)
    reason = migrate_legacy_shadow(work, in_window={"keep"})
    assert reason is None
    kept = _git(work, "rev-parse", "refs/tags/turn/keep")
    assert _parents(work, kept.stdout.strip()) == [kept.stdout.strip()]
    assert _git(work, "rev-parse", f"{kept.stdout.strip()}^{{tree}}").stdout.strip() == tree.stdout.strip()
    stayed = _git(work, "rev-parse", "refs/tags/turn/outside")
    assert _parents(work, stayed.stdout.strip()) == [stayed.stdout.strip(), outside]
    assert _git(work, "show-ref", "--verify", "refs/heads/master").returncode != 0
    from app.policy.work_gc import _EMPTY_TREE

    assert _git(work, "rev-parse", "HEAD^{tree}").stdout.strip() == _EMPTY_TREE


def test_disk_low_does_not_drop_the_tag(tmp_path: Path) -> None:
    from app.policy.shadow_git import _commit_tree, _ensure_repo
    from app.policy.work_gc import migrate_legacy_shadow

    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    _ensure_repo(work)
    base = ensure_turn_baseline(work, turn_id="keep")
    assert base
    tree = _git(work, "rev-parse", f"{base}^{{tree}}")
    child = _commit_tree(work, tree.stdout.strip(), "child", parent=base)
    assert child
    _git(work, "update-ref", "refs/tags/turn/keep", child)
    usage = shutil_usage()
    with patch("app.policy.work_gc.shutil.disk_usage", return_value=usage):
        reason = migrate_legacy_shadow(work, in_window={"keep"})
    assert reason == "disk_low"
    stayed = _git(work, "rev-parse", "--verify", "refs/tags/turn/keep")
    assert stayed.returncode == 0


def shutil_usage():
    from collections import namedtuple

    return namedtuple("Usage", "total used free")(1, 1, 0)


@pytest.mark.asyncio
async def test_non_terminal_run_does_not_rewrite_legacy_tags(tmp_path: Path) -> None:
    from app.policy.shadow_git import _commit_tree, _ensure_repo

    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    _ensure_repo(work)
    base = ensure_turn_baseline(work, turn_id="keep")
    assert base
    tree = _git(work, "rev-parse", f"{base}^{{tree}}")
    child = _commit_tree(work, tree.stdout.strip(), "child", parent=base)
    assert child
    _git(work, "update-ref", "refs/tags/turn/keep", child)
    report = await mark_work(
        _Conn(locked=True, fresh=True),
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids={"keep"},
    )
    assert report.aborted is None
    assert _parents(work, _git(work, "rev-parse", "refs/tags/turn/keep").stdout.strip()) == [
        _git(work, "rev-parse", "refs/tags/turn/keep").stdout.strip(),
        base,
    ]


def test_claim_sql_uses_skip_locked_for_work_gc() -> None:
    from app.policy.work_gc import CLAIM_SQL

    assert "FOR UPDATE SKIP LOCKED" in CLAIM_SQL
    assert "job_type = 'work_gc'" in CLAIM_SQL
    assert "update-ref -d refs/tags" not in CLAIM_SQL


@pytest.mark.asyncio
async def test_side_directory_failure_is_zero_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    ensure_turn_baseline(work, turn_id="t-1")
    from app.policy.shadow_git import shadow_dir

    recorded = shadow_dir(work) / "recorded"
    recorded.mkdir(exist_ok=True)
    real_iter = Path.iterdir

    def boom(self: Path):
        if self == recorded:
            raise OSError("denied")
        return real_iter(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    report = await mark_work(
        _Conn(locked=True, fresh=True),
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids={"t-1"},
    )
    assert report.aborted == "side_list_failed"
    assert report.candidates == 0
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/t-1").returncode == 0


@pytest.mark.asyncio
async def test_root_query_failure_is_zero_candidates(tmp_path: Path) -> None:
    work = tmp_path / "book"
    work.mkdir()
    (work / "a.txt").write_text("a", encoding="utf-8")
    ensure_turn_baseline(work, turn_id="t-1")

    class _Down(_Conn):
        async def fetchval(self, sql: str, *_args):
            self.sql.append(" ".join(sql.split()))
            if "pg_try_advisory_lock" in sql:
                return True
            raise RuntimeError("db down")

    report = await mark_work(
        _Down(locked=True),
        work_id=str(uuid4()),
        work_root=work,
        live_turn_ids={"t-1"},
    )
    assert report.aborted == "db"
    assert report.candidates == 0
    assert _git(work, "rev-parse", "--verify", "refs/tags/turn/t-1").returncode == 0
