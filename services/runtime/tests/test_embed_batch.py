"""Batch embedding (Index plane) — not on search hot path."""

from __future__ import annotations

from pathlib import Path

from app.retrieval.chunking import chunk_source_text
from app.retrieval.embedder import HashEmbedder, embed_many
from app.retrieval.index_embed import assign_deferred_vectors


def test_hash_embed_many_matches_embed() -> None:
    emb = HashEmbedder(dimensions=64)
    texts = ["alpha retrieval", "beta intel", ""]
    many = emb.embed_many(texts)
    assert len(many) == 3
    for text, vec in zip(texts, many, strict=True):
        assert vec == emb.embed(text)


def test_embed_many_helper_falls_back_without_method() -> None:
    class _OnlyEmbed:
        def embed(self, text: str) -> list[float]:
            return [float(len(text))]

    out = embed_many(_OnlyEmbed(), ["ab", "abcd"])
    assert out == [[2.0], [4.0]]


def test_chunk_source_text_deferred_then_batch(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# One\n\nhello world\n\n# Two\n\nmore text\n", encoding="utf-8")
    emb = HashEmbedder(dimensions=32)
    deferred = chunk_source_text(
        path, "sources/note.md", path.read_text(encoding="utf-8"), embedder=emb, embed=False
    )
    assert deferred
    assert all("embed_input" in c for c in deferred)
    assert all("vector" not in c for c in deferred)
    n = assign_deferred_vectors(deferred, emb, label="test")
    assert n == len(deferred)
    assert all(isinstance(c.get("vector"), list) for c in deferred)
    assert all("embed_input" not in c for c in deferred)

    eager = chunk_source_text(
        path, "sources/note.md", path.read_text(encoding="utf-8"), embedder=emb, embed=True
    )
    assert len(eager) == len(deferred)
    for a, b in zip(eager, deferred, strict=True):
        assert a["vector"] == b["vector"]
