"""Embedder max_seq_length policy (bge-m3 truncate for VRAM/throughput)."""

from __future__ import annotations

from app.retrieval import embedder as emb


def test_bge_m3_default_max_seq_applied(monkeypatch) -> None:
    class _FakeST:
        def __init__(self, *args, **kwargs):
            self.max_seq_length = 8192

    monkeypatch.setattr(emb.settings, "embedding_max_seq_length", 0)
    monkeypatch.setattr(emb.settings, "embedding_device", "cpu")
    monkeypatch.setattr(
        emb,
        "SentenceTransformer",
        _FakeST,
        raising=False,
    )

    # Patch import inside __init__
    import sys
    import types

    fake_mod = types.ModuleType("sentence_transformers")
    fake_mod.SentenceTransformer = _FakeST
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)

    model = emb.SentenceTransformerEmbedder("BAAI/bge-m3")
    assert model._model.max_seq_length == 512


def test_explicit_max_seq_overrides_bge_default(monkeypatch) -> None:
    class _FakeST:
        def __init__(self, *args, **kwargs):
            self.max_seq_length = 8192

    monkeypatch.setattr(emb.settings, "embedding_max_seq_length", 1024)
    monkeypatch.setattr(emb.settings, "embedding_device", "cpu")

    import sys
    import types

    fake_mod = types.ModuleType("sentence_transformers")
    fake_mod.SentenceTransformer = _FakeST
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)

    model = emb.SentenceTransformerEmbedder("BAAI/bge-m3")
    assert model._model.max_seq_length == 1024


def test_non_m3_leaves_default_when_unset(monkeypatch) -> None:
    class _FakeST:
        def __init__(self, *args, **kwargs):
            self.max_seq_length = 256

    monkeypatch.setattr(emb.settings, "embedding_max_seq_length", 0)
    monkeypatch.setattr(emb.settings, "embedding_device", "cpu")

    import sys
    import types

    fake_mod = types.ModuleType("sentence_transformers")
    fake_mod.SentenceTransformer = _FakeST
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)

    model = emb.SentenceTransformerEmbedder("thenlper/gte-small")
    assert model._model.max_seq_length == 256
