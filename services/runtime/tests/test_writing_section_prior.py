from __future__ import annotations

from app.retrieval.vector_index import ChunkHit
from app.retrieval.writing_section_prior import (
    BOOST,
    DOWNRANK,
    rescore_hits_for_writing,
    writing_section_multiplier,
)


def test_texture_section_outranks_plot_summary_for_writing() -> None:
    hits = [
        {"path": "drama.md", "section_title": "主线剧情", "score": 0.9},
        {"path": "period.md", "section_title": "可引用细节", "score": 0.5},
        {"path": "drama.md", "section_title": "概要", "score": 0.8},
    ]
    out = rescore_hits_for_writing(hits, scenario_id="writing")
    assert out[0]["section_title"] == "可引用细节"
    assert out[0]["score"] == round(0.5 * BOOST, 4)
    titles = [hit["section_title"] for hit in out]
    assert titles.index("可引用细节") < titles.index("主线剧情")
    assert titles.index("可引用细节") < titles.index("概要")


def test_intel_hits_are_unchanged() -> None:
    hits = [
        {"path": "a.md", "section_title": "主线剧情", "score": 0.9},
        {"path": "b.md", "section_title": "可引用细节", "score": 0.5},
    ]
    out = rescore_hits_for_writing(hits, scenario_id="intel")
    assert out[0]["section_title"] == "主线剧情"
    assert out[0]["score"] == 0.9
    assert out[1]["score"] == 0.5


def test_chunk_hit_dataclass_is_rescored() -> None:
    hits = [
        ChunkHit(
            path="a.md",
            chunk_id="a#1",
            excerpt="plot",
            citation_id="cite:a",
            score=0.9,
            section_title="主线剧情",
        ),
        ChunkHit(
            path="b.md",
            chunk_id="b#1",
            excerpt="texture",
            citation_id="cite:b",
            score=0.5,
            section_title="世界观与背景",
        ),
    ]
    out = rescore_hits_for_writing(hits, scenario_id="writing")
    assert out[0].section_title == "世界观与背景"
    assert out[0].score == round(0.5 * BOOST, 4)
    assert out[1].score == round(0.9 * DOWNRANK, 4)


def test_section_multiplier_is_title_based() -> None:
    assert writing_section_multiplier("可引用细节") == BOOST
    assert writing_section_multiplier("主线剧情") == DOWNRANK
    assert writing_section_multiplier("人物关系") == 1.0
