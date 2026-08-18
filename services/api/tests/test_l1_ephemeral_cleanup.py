"""Ephemeral ops-l1 run dirs must GC; shared index caches must not."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.services.ops.l1 import common


@pytest.fixture
def l1_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "ops-l1"
    root.mkdir()
    monkeypatch.setattr(common, "L1_ROOT", root)
    common._LIVE_L1_RUN_IDS.clear()
    yield root
    common._LIVE_L1_RUN_IDS.clear()


def test_cleanup_refuses_index_caches(l1_root: Path) -> None:
    (l1_root / "beir-index").mkdir()
    (l1_root / "cmteb-index").mkdir()
    assert common.cleanup_ephemeral_l1_run("beir-index") is False
    assert common.cleanup_ephemeral_l1_run("cmteb-index") is False
    assert (l1_root / "beir-index").is_dir()
    assert (l1_root / "cmteb-index").is_dir()


def test_cleanup_removes_uuid_run(l1_root: Path) -> None:
    rid = str(uuid4())
    work = l1_root / rid / "coding" / "astropy__astropy-12907"
    work.mkdir(parents=True)
    git = work / ".git" / "objects"
    git.mkdir(parents=True)
    blob = git / "pack"
    blob.write_bytes(b"x" * 16)
    blob.chmod(0o444)
    assert common.cleanup_ephemeral_l1_run(rid) is True
    assert not (l1_root / rid).exists()


def test_sweep_skips_live_and_caches(l1_root: Path) -> None:
    live = str(uuid4())
    orphan = str(uuid4())
    (l1_root / "beir-index").mkdir()
    (l1_root / live / "coding").mkdir(parents=True)
    (l1_root / orphan / "coding").mkdir(parents=True)
    common._LIVE_L1_RUN_IDS.add(live)
    dropped = common.sweep_orphaned_l1_runs()
    assert orphan in dropped
    assert live not in dropped
    assert (l1_root / live).is_dir()
    assert (l1_root / "beir-index").is_dir()
    assert not (l1_root / orphan).exists()


@pytest.mark.asyncio
async def test_start_finish_roundtrip(l1_root: Path) -> None:
    rid = str(uuid4())
    stale = str(uuid4())
    (l1_root / stale / "coding").mkdir(parents=True)
    logs: list[str] = []

    async def on_progress(ev: dict) -> None:
        logs.append(str(ev.get("message") or ""))

    await common.start_ephemeral_l1_run(rid, on_progress=on_progress)
    (l1_root / rid / "coding").mkdir(parents=True)
    assert rid in common._LIVE_L1_RUN_IDS
    assert not (l1_root / stale).exists()
    assert any("orphaned ops-l1" in m for m in logs)
    common.finish_ephemeral_l1_run(rid)
    assert rid not in common._LIVE_L1_RUN_IDS
    assert not (l1_root / rid).exists()
