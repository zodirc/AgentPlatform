from __future__ import annotations

from pathlib import Path

import pytest

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.chunking import chunk_source_text, should_index_source, split_markdown_sections
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

