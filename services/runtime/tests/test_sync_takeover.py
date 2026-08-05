"""Takeover: cancel prior sync_cli + terminate orphan DB backends."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.retrieval import index_scheduler as sched
from app.retrieval import sync_progress as sp


def test_terminate_orphan_sync_db_backends_kills_matching_pids(
    monkeypatch,
) -> None:
    executed: list[tuple] = []

    class _Cur:
        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._sql = sql

        def fetchall(self):
            if "pg_stat_activity" in (self._sql or ""):
                return [(101,), (202,)]
            return []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_psycopg = SimpleNamespace(
        connect=lambda *a, **k: _Conn(),
    )
    monkeypatch.setitem(__import__("sys").modules, "psycopg", fake_psycopg)
    monkeypatch.setattr(
        "app.settings.settings.database_url",
        "postgresql+asyncpg://u:p@localhost/db",
    )

    pids = sched._terminate_orphan_sync_db_backends()
    assert pids == [101, 202]
    assert any("pg_terminate_backend" in str(s[0]) for s in executed)


def test_terminate_orphan_sync_db_backends_swallows_errors(monkeypatch) -> None:
    def _boom(*a, **k):
        raise RuntimeError("no db")

    fake_psycopg = SimpleNamespace(connect=_boom)
    monkeypatch.setitem(__import__("sys").modules, "psycopg", fake_psycopg)
    assert sched._terminate_orphan_sync_db_backends() == []


def test_request_sync_takeover_bumps_cancel_and_reports(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sp.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(
        sched,
        "_cancel_gen_path",
        lambda: tmp_path / "vectorstore" / "sync_cancel_gen",
    )

    kills: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kills.append((pid, sig))

    proc = tmp_path / "proc"
    peer = proc / "4242"
    peer.mkdir(parents=True)
    (peer / "cmdline").write_bytes(b"python\x00-m\x00app.retrieval.sync_cli\x00")
    other = proc / "9999"
    other.mkdir()
    (other / "cmdline").write_bytes(b"python\x00-m\x00other\x00")
    (proc / "self").mkdir()

    import os

    monkeypatch.setattr(os, "kill", fake_kill)
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    real_path = Path

    class Entry:
        def __init__(self, path: Path):
            self._path = path
            self.name = path.name

        def __truediv__(self, other):
            return Entry(self._path / other)

        def read_bytes(self):
            return self._path.read_bytes()

        def iterdir(self):
            return (Entry(p) for p in self._path.iterdir())

    def path_factory(p="/proc"):
        if str(p) == "/proc":
            return Entry(proc)
        return real_path(p)

    monkeypatch.setattr(sched, "Path", path_factory)
    monkeypatch.setattr(sched, "_terminate_orphan_sync_db_backends", lambda: [55])

    calls = {"n": 0}

    def read_progress():
        calls["n"] += 1
        if calls["n"] == 1:
            return {"status": "building", "phase": "embed"}
        return {"status": "ready", "phase": "finished"}

    monkeypatch.setattr(
        "app.retrieval.sync_progress.read_sync_progress", read_progress
    )

    info = sched.request_sync_takeover(wait_s=0.0)
    assert info["had_building"] is True
    assert info["prior_phase"] == "embed"
    assert info["db_terminated"] == [55]
    assert 4242 in info["killed_pids"]
    assert 9999 not in info["killed_pids"]
    assert kills


def _patch_empty_proc(monkeypatch, tmp_path: Path) -> None:
    """Only fake /proc; keep real Path for cancel-gen file writes."""
    monkeypatch.setattr(
        sched,
        "_cancel_gen_path",
        lambda: tmp_path / "vectorstore" / "sync_cancel_gen",
    )
    real_path = Path
    empty = tmp_path / "empty_proc"
    empty.mkdir(exist_ok=True)

    class Entry:
        def __init__(self, path: Path):
            self._path = path
            self.name = path.name

        def __truediv__(self, other):
            return Entry(self._path / other)

        def read_bytes(self):
            return self._path.read_bytes()

        def iterdir(self):
            return (Entry(p) for p in self._path.iterdir())

    def path_factory(p="/proc"):
        if str(p) == "/proc":
            return Entry(empty)
        return real_path(p)

    monkeypatch.setattr(sched, "Path", path_factory)


def test_request_sync_takeover_handles_progress_read_errors(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.retrieval.sync_progress.read_sync_progress",
        MagicMock(side_effect=RuntimeError("io")),
    )
    monkeypatch.setattr(sched, "_terminate_orphan_sync_db_backends", lambda: [])
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    _patch_empty_proc(monkeypatch, tmp_path)
    info = sched.request_sync_takeover(wait_s=0.0)
    assert info["had_building"] is False
    assert info["killed_pids"] == []
    assert info["db_terminated"] == []


def test_request_sync_takeover_merges_second_db_pass(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.retrieval.sync_progress.read_sync_progress",
        lambda: {"status": "ready", "phase": "finished"},
    )
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def term():
        calls["n"] += 1
        return [1] if calls["n"] == 1 else [1, 2]

    monkeypatch.setattr(sched, "_terminate_orphan_sync_db_backends", term)
    _patch_empty_proc(monkeypatch, tmp_path)
    info = sched.request_sync_takeover(wait_s=0.0)
    assert info["db_terminated"] == [1, 2]


def test_request_sync_takeover_wait_break_on_cancel_error(
    tmp_path: Path, monkeypatch
) -> None:
    reads = [
        {"status": "building", "phase": "scan"},
        {"status": "building", "phase": "scan", "error": "SourcesSyncCancelled"},
    ]

    def read_progress():
        return reads.pop(0) if reads else {"status": "ready"}

    monkeypatch.setattr(
        "app.retrieval.sync_progress.read_sync_progress", read_progress
    )
    monkeypatch.setattr(sched, "_terminate_orphan_sync_db_backends", lambda: [])
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    _patch_empty_proc(monkeypatch, tmp_path)
    info = sched.request_sync_takeover(wait_s=5.0)
    assert info["had_building"] is True
