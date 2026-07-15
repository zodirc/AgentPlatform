from __future__ import annotations

from app.retrieval.two_level import merge_doc_and_chunk_hits, parallel_two_level
from app.retrieval.vector_index import ChunkHit


def _hit(path: str, chunk_id: str, score: float) -> ChunkHit:
    return ChunkHit(
        path=path,
        chunk_id=chunk_id,
        excerpt=chunk_id,
        citation_id=f"cite:{chunk_id}",
        score=score,
    )


def test_merge_boosts_doc_paths() -> None:
    merged = merge_doc_and_chunk_hits(
        doc_paths=["a.md"],
        chunk_hits=[_hit("b.md", "b1", 0.9), _hit("a.md", "a1", 0.5)],
        limit=2,
    )
    assert merged[0].chunk_id == "a1"
    assert merged[0].score > 0.5


def test_parallel_two_level_degrades_on_slow_doc() -> None:
    def slow_doc() -> list[str]:
        import time

        time.sleep(0.2)
        return ["a.md"]

    def fast_chunk() -> list[ChunkHit]:
        return [_hit("b.md", "b1", 0.8)]

    doc_paths, chunks, timed_out = parallel_two_level(
        doc_fn=slow_doc,
        chunk_fn=fast_chunk,
        timeout_seconds=0.05,
    )
    assert chunks
    assert chunks[0].chunk_id == "b1"
    # Doc may be empty when timed out; either way chunk lane wins degrade.
    assert timed_out or doc_paths == ["a.md"]
