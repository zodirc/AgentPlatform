"""Step write bytes and sampled canonical duplication."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.observability import step_write_measure as measure
from app.observability.metrics import metrics
from app.observability.model_envelope import maybe_persist_model_envelope
from app.settings import Settings


def _counter(name: str) -> float:
    prefix = name + " "
    for line in metrics.render_prometheus().splitlines():
        if line.startswith(prefix):
            return float(line.split()[-1])
    return 0.0


def test_sample_rate_default_is_one_percent() -> None:
    assert Settings.model_fields["model_envelope_sample_rate"].default == 0.01
    assert Settings.model_fields["raw_snapshot_enabled"].default is False


def test_reordered_keys_count_as_a_hit_the_second_time() -> None:
    measure.clear_seen_hashes()
    first = {"b": 1, "a": "相同"}
    second = {"a": "相同", "b": 1}
    canonical, hit, new_hashes = measure.classify_sample([first])
    assert hit == 0
    assert canonical > 0
    measure.commit_seen(new_hashes)
    again, hit_again, newer = measure.classify_sample([second])
    assert again == canonical
    assert hit_again == canonical
    assert newer == []


def test_new_message_is_not_a_hit() -> None:
    measure.clear_seen_hashes()
    _, hit, new_hashes = measure.classify_sample([{"role": "user", "text": "一"}])
    measure.commit_seen(new_hashes)
    _, hit_again, _ = measure.classify_sample([{"role": "user", "text": "二"}])
    assert hit == 0
    assert hit_again == 0


def test_duplicate_inside_one_sample_counts_the_second_copy() -> None:
    measure.clear_seen_hashes()
    message = {"role": "system", "text": "提示"}
    canonical, hit, new_hashes = measure.classify_sample([message, message])
    assert len(new_hashes) == 1
    assert hit == canonical // 2


def test_full_seen_set_does_not_count_a_new_message_as_a_hit(monkeypatch) -> None:
    measure.clear_seen_hashes()
    monkeypatch.setattr(measure, "_SEEN_CAP", 1)
    _, _, first = measure.classify_sample([{"n": 1}])
    measure.commit_seen(first)
    canonical, hit, newer = measure.classify_sample([{"n": 2}])
    assert canonical > 0
    assert hit == 0
    assert newer == []


@pytest.mark.asyncio
async def test_hash_is_written_when_body_is_not_sampled() -> None:
    measure.clear_seen_hashes()
    before_write = _counter("storage_step_write_bytes")
    before_canonical = _counter("storage_canonical_bytes")
    pool = MagicMock()
    pool.execute = AsyncMock(return_value="INSERT 0 1")
    with (
        patch("app.observability.model_envelope.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.observability.model_envelope.settings.model_envelope_enabled", True),
        patch("app.observability.model_envelope.settings.model_envelope_debug", False),
        patch("app.observability.model_envelope.settings.model_envelope_on_high_fill", False),
        patch("app.observability.model_envelope.settings.model_envelope_sample_rate", 0.0),
    ):
        await maybe_persist_model_envelope(
            turn_id=uuid4(),
            session_id=uuid4(),
            step_index=1,
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
    args = pool.execute.await_args.args
    assert len(args[4]) == 64
    assert args[6] is None
    assert _counter("storage_step_write_bytes") == before_write
    assert _counter("storage_canonical_bytes") == before_canonical


@pytest.mark.asyncio
async def test_failed_insert_does_not_commit_seen_hash() -> None:
    measure.clear_seen_hashes()
    pool = MagicMock()
    pool.execute = AsyncMock(side_effect=RuntimeError("db down"))
    message = {"role": "user", "content": "仅此一条"}
    with (
        patch("app.observability.model_envelope.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.observability.model_envelope.settings.model_envelope_enabled", True),
        patch("app.observability.model_envelope.settings.model_envelope_debug", True),
    ):
        await maybe_persist_model_envelope(
            turn_id=uuid4(),
            session_id=None,
            step_index=0,
            messages=[message],
            tools=None,
        )
    _, hit, _ = measure.classify_sample([message])
    assert hit == 0
