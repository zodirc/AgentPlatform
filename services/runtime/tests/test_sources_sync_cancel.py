"""Sources sync cancel + ops-l1 full-tenant skip."""

from __future__ import annotations

from pathlib import Path

from app.retrieval import index_scheduler as sched


def test_bump_sync_cancel_invalidates_token() -> None:
    token = sched.sync_cancel_token()
    sched.bind_sync_cancel_token(token)
    try:
        sched.check_sync_cancelled()  # same gen — ok
        sched.bump_sync_cancel()
        try:
            sched.check_sync_cancelled()
            raise AssertionError("expected SourcesSyncCancelled")
        except sched.SourcesSyncCancelled:
            pass
    finally:
        sched.clear_sync_cancel_token()
        # Restore a clean gen baseline for other tests by bumping once more is fine.
        sched.bump_sync_cancel()


def test_ephemeral_ops_l1_root_skip(tmp_path: Path) -> None:
    ephemeral = tmp_path / "ops-l1" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" / "retrieval" / "scifact"
    ephemeral.mkdir(parents=True)
    cache = tmp_path / "ops-l1" / "beir-index" / "scifact"
    cache.mkdir(parents=True)
    other = tmp_path / "data" / "works" / "w1"
    other.mkdir(parents=True)

    assert sched._is_ephemeral_ops_l1_root(ephemeral) is True
    assert sched._is_ephemeral_ops_l1_root(cache) is False
    assert sched._is_ephemeral_ops_l1_root(other) is False


def test_full_tenant_sync_skips_all_ops_l1_including_beir_index(tmp_path: Path) -> None:
    """Global reason=api must not chew beir-index; L1 uses api-work only."""
    ephemeral = tmp_path / "ops-l1" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" / "retrieval" / "scifact"
    ephemeral.mkdir(parents=True)
    cache = tmp_path / "ops-l1" / "beir-index" / "fiqa"
    cache.mkdir(parents=True)
    other = tmp_path / "data" / "works" / "w1"
    other.mkdir(parents=True)

    assert sched._is_ops_l1_root(ephemeral) is True
    assert sched._is_ops_l1_root(cache) is True
    assert sched._is_ops_l1_root(other) is False
