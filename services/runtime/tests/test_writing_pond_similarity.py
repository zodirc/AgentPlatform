from __future__ import annotations

from pathlib import Path

from app.writing.opening_ponds import (
    MORE_PONDS_MESSAGE,
    normalize_pond_items,
    ponds_reject_reason,
)


def _snap(
    *,
    intra: float = 0.2,
    against: float = 0.1,
    usable: bool = True,
    shadow: bool = True,
    left: str = "夜行证失效",
    right: str = "执契",
    new: str = "灵籍",
    old: str = "人间有灵",
) -> dict:
    return {
        "intra_max": intra,
        "intra_hit": {"left": left, "right": right, "cos": intra},
        "against_rejected_max": against,
        "against_hit": {"new": new, "old": old, "cos": against},
        "usable": usable,
        "shadow": shadow,
        "embedder": "sentence-transformer",
    }


def _two() -> list[dict[str, str]]:
    return normalize_pond_items(
        [
            {
                "title": "夜行证",
                "opening": (
                    "夜行证就搁在他手边，灯管滋了一声。他没有抬头，把杯垫转了半圈。"
                    "对面那人把筷子放下，雨还在打窗沿。他按着杯沿，没把话接下去。"
                    "店里的钟走得很慢，他知道今晚不会因为这一句就结束。"
                ),
            },
            {
                "title": "人间有灵",
                "opening": (
                    "人间有灵四个字印在塑料袋上，他提着袋子进门。猫从沙发底下探出头。"
                    "他蹲下去，袋子口还没扎紧。窗外有人按了两下电铃。他没去开门，先把袋子放到灶台上。"
                    "水还开着，他先把米洗了，这件事明天还会再来找他。"
                ),
            },
        ]
    )


def test_same_book_shadow_does_not_reject() -> None:
    items = _two()
    snap = _snap(intra=0.95, shadow=True)
    assert (
        ponds_reject_reason(items, similarity=snap, shadow=True) is None
    )


def test_same_book_enforce_rejects(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "ponds_similarity_intra", 0.88)
    items = _two()
    snap = _snap(intra=0.95, shadow=False)
    code, detail = ponds_reject_reason(items, similarity=snap, shadow=False) or ("", "")
    assert code == "ponds_same_book"
    assert "不要修补" in detail
    assert "夜行证失效" not in detail
    assert "执契" not in detail
    assert "轴" not in detail


def test_near_rejected_only_on_more_path(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "ponds_similarity_against", 0.88)
    items = _two()
    snap = _snap(intra=0.2, against=0.96, shadow=False)
    browse = ponds_reject_reason(
        items, message="写一篇都市修真，我看看", similarity=snap, shadow=False
    )
    assert browse is None
    code, detail = ponds_reject_reason(
        items,
        message=MORE_PONDS_MESSAGE,
        against=[{"title": "人间有灵", "flavor": "x", "opening": "y"}],
        similarity=snap,
        shadow=False,
    ) or ("", "")
    assert code == "ponds_near_rejected"
    assert "不要修补" in detail
    assert "灵籍" not in detail
    assert "人间有灵" not in detail


def test_lexical_embedder_never_rejects(workspace: Path, monkeypatch) -> None:
    from app.settings import settings
    from app.writing.pond_similarity import compute_pond_similarity

    monkeypatch.setattr(settings, "ponds_similarity_shadow", False)
    snap = compute_pond_similarity(_two(), against=[], shadow=False)
    assert snap["embedder"] == "hash"
    assert snap["usable"] is False
    assert ponds_reject_reason(_two(), similarity=snap, shadow=False) is None


def test_same_book_helpers_read_only_titles() -> None:
    from app.writing.pond_similarity import near_rejected_reject, same_book_reject

    assert same_book_reject(_snap(intra=0.5, usable=True)) is None
    hit = same_book_reject(_snap(intra=0.99, usable=True))
    assert hit is not None and hit[0] == "ponds_same_book"
    assert near_rejected_reject(_snap(against=0.99, usable=True))[0] == "ponds_near_rejected"
    assert near_rejected_reject(_snap(against=0.99, usable=False)) is None


def test_embed_text_opening_only_when_no_flavor() -> None:
    from app.writing.pond_similarity import pond_embed_text

    text = pond_embed_text({"title": "末班车", "opening": "末班车出总站。", "flavor": ""})
    assert text == "末班车出总站。"
    both = pond_embed_text({"flavor": "简介", "opening": "末班车出总站。"})
    assert both == "简介\n末班车出总站。"


def test_default_threshold_skips_engine_apart_band() -> None:
    from app.writing.pond_similarity import same_book_reject

    # 2026-09-11 RemoteEmbedder prior: 肉身 vs 仙人 ≈ 0.89, 夜行证 vs 执契 ≈ 0.87.
    assert same_book_reject(_snap(intra=0.89, usable=True)) is None
