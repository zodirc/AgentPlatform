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
                "title": "夜行证失效",
                "flavor": "跑腿、死人留下的证、三分钟确认，否则整车被带走。",
                "opening": "公共屏幕倒计时开始，地铁里三分钟确认，否则整车被带走。",
            },
            {
                "title": "人间有灵",
                "flavor": "异能已融入日常、直播事故、母亲的修士名号被叫出来。",
                "opening": "直播事故里术法回声叫出母亲已注销的修士名号。",
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
    assert "夜行证失效" in detail
    assert "执契" in detail
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
    assert "灵籍" in detail
    assert "人间有灵" in detail


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


def test_default_threshold_skips_engine_apart_band() -> None:
    from app.writing.pond_similarity import same_book_reject

    # 2026-09-11 RemoteEmbedder prior: 肉身 vs 仙人 ≈ 0.89, 夜行证 vs 执契 ≈ 0.87.
    assert same_book_reject(_snap(intra=0.89, usable=True)) is None
