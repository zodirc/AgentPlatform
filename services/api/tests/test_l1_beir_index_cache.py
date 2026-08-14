"""L1 BEIR index cache: fingerprint + progress scoping (no Docker)."""

from __future__ import annotations

from uuid import uuid4

from app.services.ops.l1 import common, index_ops
from app.services.resource.works import Work


def test_beir_corpus_fingerprint_stable_on_same_corpus(monkeypatch) -> None:
    monkeypatch.delenv("INDEX_VERSION", raising=False)
    monkeypatch.delenv("RETRIEVAL_INDEX_VERSION", raising=False)
    monkeypatch.setenv("EMBEDDING_BACKEND", "sentence_transformers")
    corpus = {"a": "hello", "b": "world"}
    a = common._beir_corpus_fingerprint("scifact", corpus)
    b = common._beir_corpus_fingerprint("scifact", dict(reversed(list(corpus.items()))))
    assert a == b
    assert len(a) == 20


def test_beir_corpus_fingerprint_changes_with_backend(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_BACKEND", "sentence_transformers")
    corpus = {"a": "x"}
    a = common._beir_corpus_fingerprint("scifact", corpus)
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    b = common._beir_corpus_fingerprint("scifact", corpus)
    assert a != b


def test_progress_for_work_matches_work_id() -> None:
    work = Work(
        id=uuid4(),
        owner_user_id=uuid4(),
        name="t",
        work_root="/data/ops-l1/beir-index/scifact",
        is_default=False,
    )
    other = uuid4()
    assert common._progress_for_work(
        {"status": "building", "progress": {"work_id": str(work.id), "phase": "embed"}},
        work,
    )
    assert not common._progress_for_work(
        {"status": "building", "progress": {"work_id": str(other), "phase": "embed"}},
        work,
    )


def test_progress_for_work_path_fallback() -> None:
    work = Work(
        id=uuid4(),
        owner_user_id=uuid4(),
        name="t",
        work_root="/data/ops-l1/beir-index/scifact",
        is_default=False,
    )
    assert common._progress_for_work(
        {
            "status": "building",
            "progress": {
                "phase": "scan",
                "path": "/data/ops-l1/beir-index/scifact/sources",
            },
        },
        work,
    )


def test_progress_for_work_rejects_unscoped_building() -> None:
    work = Work(
        id=uuid4(),
        owner_user_id=uuid4(),
        name="t",
        work_root="/data/ops-l1/beir-index/scifact",
        is_default=False,
    )
    assert not common._progress_for_work(
        {"status": "building", "progress": {"phase": "embed", "files_done": 100}},
        work,
    )


def test_format_sync_progress_includes_work() -> None:
    line = index_ops._format_sync_progress_line(
        "scifact",
        {
            "status": "building",
            "progress": {
                "phase": "embed",
                "work_id": "32805be1-8a02-4990-b395-ef011fd658df",
                "files_done": 10,
                "files_total": 100,
            },
        },
    )
    assert "work=32805be1" in line
    assert "phase=embed" in line
