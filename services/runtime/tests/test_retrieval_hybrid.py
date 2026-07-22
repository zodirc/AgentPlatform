from __future__ import annotations

from pathlib import Path

import pytest

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.chunking import (
    build_embed_text,
    chunk_source_text,
    should_index_source,
    split_markdown_sections,
)
from app.retrieval.embedder import HashEmbedder
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.rerank import lexical_rerank
from app.retrieval.store import get_sources_store
from app.retrieval.vector_index import ChunkHit, SourceVectorIndex
from app.settings import settings


@pytest.fixture(autouse=True)
def _hash_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)


def test_split_markdown_sections_by_headers() -> None:
    text = """# Title

## 李云龙
主角段落。

### 张白鹿（主要配角）
张白鹿相关内容。
"""
    sections = split_markdown_sections(text)
    titles = [section.title for section in sections if section.title]
    assert "李云龙" in titles
    assert "张白鹿（主要配角）" in titles


def test_should_skip_debug_source_files() -> None:
    assert should_index_source(Path("sources/paste-debug.md")) is False
    assert should_index_source(Path("sources/亮剑.md")) is True


def test_bm25_prefers_rare_entity_name() -> None:
    chunks = [
        {"chunk_id": "a", "text": "李云龙 李云龙 李云龙 主角 战役"},
        {"chunk_id": "b", "text": "张白鹿（主要配角） 张白鹿 独立团相关人物"},
    ]
    ranked = BM25Scorer(chunks).search("张白鹿", limit=2)
    assert ranked
    assert ranked[0][0] == "b"


def test_rrf_merges_vector_and_bm25_rankings() -> None:
    fused = reciprocal_rank_fusion(
        [
            [("chunk-a", 0.9), ("chunk-b", 0.4)],
            [("chunk-b", 3.1), ("chunk-c", 1.2)],
        ],
        limit=2,
        k=60,
    )
    ids = [chunk_id for chunk_id, _score in fused]
    assert ids[0] == "chunk-b"
    assert len(ids) == 2


def test_rrf_lane_weights_prefer_vector() -> None:
    """RQ1e: weighted RRF can elevate the vector lane (bm25 weight → 0)."""
    equal = reciprocal_rank_fusion(
        [[("v-only", 1.0), ("both", 0.5)], [("b-only", 1.0), ("both", 0.5)]],
        limit=3,
        k=60,
        weights=[1.0, 1.0],
    )
    vector_only = reciprocal_rank_fusion(
        [[("v-only", 1.0), ("both", 0.5)], [("b-only", 1.0), ("both", 0.5)]],
        limit=3,
        k=60,
        weights=[1.0, 0.0],
    )
    assert equal[0][0] == "both"
    assert vector_only[0][0] == "v-only"
    assert "b-only" not in {cid for cid, _ in vector_only}


def test_default_profile_matches_legacy_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.retrieval.profile import active_retrieval_profile

    monkeypatch.setattr(settings, "retrieval_profile", "default")
    monkeypatch.setattr(settings, "retrieval_rrf_vector_weight", 1.0)
    monkeypatch.setattr(settings, "retrieval_rrf_bm25_weight", 1.0)
    monkeypatch.setattr(settings, "retrieval_doc_boost", 0.35)
    profile = active_retrieval_profile()
    assert profile.name == "default"
    assert profile.vector_weight == 1.0
    assert profile.bm25_weight == 1.0
    assert profile.doc_boost == 0.35


def test_vector_heavy_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.retrieval.profile import active_retrieval_profile

    monkeypatch.setattr(settings, "retrieval_profile", "vector_heavy")
    profile = active_retrieval_profile()
    assert profile.name == "vector_heavy"
    assert profile.vector_weight > profile.bm25_weight


def test_extract_source_tags_from_path_and_meta() -> None:
    from app.retrieval.chunking import extract_source_tags

    text = (
        "# 亮剑\n\n"
        "> 类型: drama\n"
        "> 别名: 亮劍, Liang Jian\n"
        "> tags: military, ww2\n"
        "\n## 概要\n正文\n"
    )
    tags = extract_source_tags("sources/seed/writing/dramas/liangjian.md", text)
    assert "dramas" in tags
    assert "drama" in tags
    assert "military" in tags
    assert "ww2" in tags
    # Aliases are not auto-tagged (noise); use explicit tags: instead.
    assert "liang-jian" not in tags
    assert "亮劍" not in tags


def test_chunk_includes_auto_tags(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sources = workspace / "sources" / "seed" / "writing" / "persons"
    sources.mkdir(parents=True)
    path = sources / "yuefei.md"
    path.write_text("# 岳飞\n\n> 类型: person\n\n## 概要\n抗金名将。\n", encoding="utf-8")
    rel = str(path.relative_to(workspace))
    chunks = chunk_source_text(
        path, rel, path.read_text(encoding="utf-8"), embedder=HashEmbedder(dimensions=64)
    )
    assert chunks
    assert "persons" in chunks[0].get("tags", [])
    assert "person" in chunks[0].get("tags", [])
    composed = build_embed_text(rel, chunks[0]["text"], tags=chunks[0]["tags"])
    assert "tags:" in composed
    assert "persons" in composed


def test_structure_chunking_keeps_section_title(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    path = sources / "亮剑.md"
    path.write_text(
        "# 人物\n\n## 主角\n李云龙内容。\n\n### 张白鹿\n张白鹿细节。\n",
        encoding="utf-8",
    )
    embedder = HashEmbedder(dimensions=64)
    rel = str(path.relative_to(workspace))
    chunks = chunk_source_text(path, rel, path.read_text(encoding="utf-8"), embedder=embedder)
    zhang = next(chunk for chunk in chunks if "张白鹿" in chunk["text"])
    assert zhang["section_title"] == "张白鹿"


def test_path_embed_clue_and_build_embed_text() -> None:
    from app.retrieval.chunking import build_embed_text, path_embed_clue

    assert path_embed_clue("sources/seed/writing/persons/yuefei.md") == (
        "path: seed/writing/persons/yuefei"
    )
    composed = build_embed_text(
        "sources/seed/writing/dramas/liangjian.md",
        "张白鹿细节",
        tags=["drama", "liangjian"],
    )
    assert composed.startswith("path: seed/writing/dramas/liangjian")
    assert "tags: drama liangjian" in composed
    assert composed.endswith("张白鹿细节")


def test_chunk_embed_uses_path_clue_not_excerpt(tmp_path: Path) -> None:
    """RQ1a: vector input includes path; text/excerpt stays body-only."""
    workspace = tmp_path / "workspace"
    sources = workspace / "sources" / "seed" / "writing" / "persons"
    sources.mkdir(parents=True)
    path = sources / "hero.md"
    path.write_text("## 概要\n专名召回正文。\n", encoding="utf-8")
    embedder = HashEmbedder(dimensions=64)
    rel = str(path.relative_to(workspace))
    chunks = chunk_source_text(path, rel, path.read_text(encoding="utf-8"), embedder=embedder)
    assert chunks
    body_only = chunks[0]["text"]
    assert "path:" not in body_only
    assert "专名召回正文" in body_only
    body_vec = embedder.embed(body_only)
    path_vec = chunks[0]["vector"]
    assert path_vec != body_vec


def test_leaf_under_budget_stays_one_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "retrieval_chunk_max_chars", 4000)
    monkeypatch.setattr(settings, "retrieval_chunk_overlap_chars", 400)
    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    path = sources / "note.md"
    body = "专名段落。" * 50  # well under 4000
    path.write_text(f"## 概要\n{body}\n", encoding="utf-8")
    chunks = chunk_source_text(
        path, "sources/note.md", path.read_text(encoding="utf-8"), embedder=HashEmbedder(dimensions=64)
    )
    assert len(chunks) == 1
    assert "专名段落" in chunks[0]["text"]


def test_oversized_leaf_uses_sliding_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "retrieval_chunk_max_chars", 200)
    monkeypatch.setattr(settings, "retrieval_chunk_overlap_chars", 40)
    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    path = sources / "long.md"
    body = "字" * 500
    path.write_text(f"## 长节\n{body}\n", encoding="utf-8")
    chunks = chunk_source_text(
        path, "sources/long.md", path.read_text(encoding="utf-8"), embedder=HashEmbedder(dimensions=64)
    )
    assert len(chunks) >= 3
    assert all(len(c["text"]) <= 200 for c in chunks)


def test_wide_table_detached_from_chunk_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.retrieval.chunking import detach_wide_tables

    monkeypatch.setattr(settings, "retrieval_table_detach_min_rows", 4)
    monkeypatch.setattr(settings, "retrieval_table_detach_min_chars", 200)
    table = (
        "| 年 | 事件 |\n"
        "|----|------|\n"
        "| 1937 | A |\n"
        "| 1938 | B |\n"
        "| 1939 | C |\n"
        "| 1940 | D |\n"
        "| 1941 | E |\n"
    )
    detached = detach_wide_tables(f"## 时间线\n\n{table}\n尾注。\n")
    assert "table detached" in detached
    assert "| 1937 | A |" not in detached
    assert "尾注" in detached

    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    path = sources / "drama.md"
    path.write_text(f"## 时间线\n\n{table}\n", encoding="utf-8")
    # Disk unchanged for read_file consumers.
    assert "| 1937 | A |" in path.read_text(encoding="utf-8")
    chunks = chunk_source_text(
        path, "sources/drama.md", path.read_text(encoding="utf-8"), embedder=HashEmbedder(dimensions=64)
    )
    assert chunks
    joined = "\n".join(c["text"] for c in chunks)
    assert "table detached" in joined
    assert "| 1937 | A |" not in joined


def test_index_version_bump_forces_reindex(tmp_path: Path) -> None:
    from app.retrieval import vector_index as vi

    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    (sources / "note.md").write_text("unique-reindex-term alpha", encoding="utf-8")
    index_path = tmp_path / "vectorstore" / "sources.json"
    index = SourceVectorIndex(index_path)
    first = index.sync(sources, workspace_root=workspace)
    assert first["indexed_files"] == 1
    assert first.get("reindexed") is True or first["added"] == 1

    second = index.sync(sources, workspace_root=workspace)
    assert second["skipped"] == 1
    assert second.get("reindexed") is False

    # Simulate older on-disk version → full rebuild without mtime change.
    index.load()
    index._data["version"] = int(vi.INDEX_VERSION) - 1
    index.save()
    third = index.sync(sources, workspace_root=workspace)
    assert third.get("reindexed") is True
    assert third["skipped"] == 0
    assert int(index._data["version"]) == vi.INDEX_VERSION


def test_hybrid_search_recalls_named_character(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    (sources / "亮剑.md").write_text(
        "# 亮剑人物\n\n"
        "## 李云龙\n李云龙是主角，作战勇猛，战役频繁。\n\n"
        "### 张白鹿（主要配角）\n张白鹿与李云龙相识，性格独立。\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "vectorstore" / "sources.json"
    index = SourceVectorIndex(index_path)
    index.sync(sources, workspace_root=workspace)

    hits = index.search_hybrid("张白鹿", limit=3)
    assert hits
    assert any("张白鹿" in hit.excerpt for hit in hits)


def test_lexical_rerank_prefers_section_title_match() -> None:
    hits = [
        ChunkHit(
            path="sources/a.md",
            chunk_id="a",
            excerpt="李云龙 战役 作战",
            citation_id="cite:a",
            score=0.4,
            section_title="李云龙",
        ),
        ChunkHit(
            path="sources/a.md",
            chunk_id="b",
            excerpt="张白鹿 性格独立",
            citation_id="cite:a",
            score=0.2,
            section_title="张白鹿（主要配角）",
        ),
    ]
    reranked = lexical_rerank("张白鹿", hits, limit=1)
    assert reranked[0].chunk_id == "b"


def test_json_source_retrieval_store_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    (sources / "note.md").write_text("alpha beta unique-term", encoding="utf-8")
    store = get_sources_store(data_dir=str(tmp_path / "data"))
    stats = store.sync(sources, workspace_root=workspace)
    assert stats["indexed_files"] == 1
    hits = store.search("unique-term", limit=2, mode="hybrid")
    assert hits
    assert any("unique-term" in hit.excerpt for hit in hits)

