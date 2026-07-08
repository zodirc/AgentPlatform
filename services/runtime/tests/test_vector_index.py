from __future__ import annotations

from pathlib import Path

from app.retrieval.embedder import HashEmbedder, cosine_similarity, get_embedder
from app.retrieval.vector_index import SourceVectorIndex


def test_hash_embedder_produces_unit_vector() -> None:
    embedder = HashEmbedder(dimensions=64)
    vec = embedder.embed("phase2-unique-term retrieval")
    assert len(vec) == 64
    norm = sum(value * value for value in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6 or norm == 0.0


def test_cosine_similarity_identical_vectors() -> None:
    vec = [1.0, 0.0, 0.0]
    assert cosine_similarity(vec, vec) == 1.0


def test_source_vector_index_sync_and_search(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    (sources / "new-chunk.md").write_text(
        "New material with phase2-unique-term for vector recall.\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "vectorstore" / "sources.json"
    index = SourceVectorIndex(index_path)
    stats = index.sync(sources, workspace_root=workspace)
    assert stats["indexed_files"] == 1
    assert stats["chunks"] >= 1

    hits = index.search("phase2-unique-term", limit=3)
    assert hits
    assert any("phase2-unique-term" in hit.excerpt for hit in hits)
    assert hits[0].score > 0.0


def test_get_embedder_defaults_to_hash(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "hash")
    embedder = get_embedder()
    assert isinstance(embedder, HashEmbedder)


def test_get_embedder_sentence_transformers_requires_extra(monkeypatch) -> None:
    import pytest

    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "sentence_transformers")

    class BrokenEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            raise ImportError("sentence_transformers not installed")

    monkeypatch.setattr("app.retrieval.embedder.SentenceTransformerEmbedder", BrokenEmbedder)
    with pytest.raises(RuntimeError, match="retrieval extra"):
        get_embedder()
