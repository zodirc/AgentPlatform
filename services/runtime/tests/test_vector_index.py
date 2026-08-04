from __future__ import annotations

from pathlib import Path

import pytest

from app.retrieval.embedder import (
    HashEmbedder,
    cosine_similarity,
    get_embedder,
    reset_embedder_cache,
    warmup_embedder,
)
from app.retrieval.vector_index import SourceVectorIndex


@pytest.fixture(autouse=True)
def _clear_embedder_cache() -> None:
    reset_embedder_cache()
    yield
    reset_embedder_cache()


def test_hash_embedder_produces_unit_vector() -> None:
    embedder = HashEmbedder(dimensions=64)
    vec = embedder.embed("phase2-unique-term retrieval")
    assert len(vec) == 64
    norm = sum(value * value for value in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6 or norm == 0.0


def test_cosine_similarity_identical_vectors() -> None:
    vec = [1.0, 0.0, 0.0]
    assert cosine_similarity(vec, vec) == 1.0


def test_source_vector_index_sync_and_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    reset_embedder_cache()
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


def test_search_vector_batched_matches_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Numpy matmul ranking should match the legacy Python loop on the same index."""
    pytest.importorskip("numpy")
    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    monkeypatch.setattr(settings, "retrieval_two_level_enabled", False)

    workspace = tmp_path / "workspace"
    sources = workspace / "sources"
    sources.mkdir(parents=True)
    for i, text in enumerate(
        [
            "alpha token unique-aaa appears here",
            "beta token unique-bbb appears here",
            "gamma filler text without markers",
            "unique-aaa again for stronger alpha",
        ]
    ):
        (sources / f"doc{i}.txt").write_text(text + "\n", encoding="utf-8")

    index = SourceVectorIndex(tmp_path / "vectorstore" / "sources.json")
    index.sync(sources, workspace_root=workspace)

    query = "unique-aaa"
    batched = index.search_vector(query, limit=3)
    # Force legacy Python loop even when numpy is installed.
    monkeypatch.setattr("app.retrieval.vector_index.np", None, raising=False)
    index._invalidate_vector_matrix()
    looped = index.search_vector(query, limit=3)

    assert [h.chunk_id for h in batched] == [h.chunk_id for h in looped]
    for a, b in zip(batched, looped, strict=True):
        assert abs(a.score - b.score) < 1e-5


def test_get_embedder_defaults_to_hash(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "hash")
    embedder = get_embedder()
    assert isinstance(embedder, HashEmbedder)


def test_get_embedder_is_process_singleton(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "hash")
    first = get_embedder()
    second = get_embedder()
    assert first is second


def test_get_embedder_rebuilds_when_settings_change(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    first = get_embedder()
    monkeypatch.setattr(settings, "embedding_dimensions", 128)
    second = get_embedder()
    assert first is not second
    assert isinstance(second, HashEmbedder)
    assert second.dimensions == 128


def test_warmup_embedder_loads_hash(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "hash")
    label = warmup_embedder()
    assert label.startswith("hash:")
    assert get_embedder() is get_embedder()


def test_get_embedder_sentence_transformers_requires_extra(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "embedding_backend", "sentence_transformers")

    class BrokenEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            raise ImportError("sentence_transformers not installed")

    monkeypatch.setattr("app.retrieval.embedder.SentenceTransformerEmbedder", BrokenEmbedder)
    with pytest.raises(RuntimeError, match="retrieval extra"):
        get_embedder()
