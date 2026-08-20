from __future__ import annotations

import asyncio

from app.writing.signals.assemble import score_writing_lab
from app.writing.signals.bank import find_platform_exemplar, iter_platform_exemplars


def test_iter_platform_exemplars_round_trip() -> None:
    rows = iter_platform_exemplars()
    assert len(rows) >= 24
    sample = rows[0]
    found = find_platform_exemplar(slug=sample.slug, fragment=sample.fragment)
    assert found is not None
    assert found.text == sample.text
    assert find_platform_exemplar(slug="not-a-real-slug") is None


def test_score_writing_lab_does_not_persist() -> None:
    sample = next(s for s in iter_platform_exemplars() if s.fragment == "dialogue_dyad")

    async def _run() -> None:
        by_slug = await score_writing_lab(slug=sample.slug)
        assert by_slug["persisted"] is False
        assert by_slug["source"]["kind"] == "exemplar"
        assert by_slug["source"]["slug"] == sample.slug
        assert by_slug["writing_signals"]["persisted"] is False
        assert 0.0 <= by_slug["writing_signals"]["net_signal"] <= 1.0

        uploaded = await score_writing_lab(
            text=sample.text,
            fragment="dialogue_dyad",
        )
        assert uploaded["source"]["kind"] == "upload"
        assert uploaded["writing_signals"]["fragment"]["declared"] == "dialogue_dyad"

    asyncio.run(_run())
