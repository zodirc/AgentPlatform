"""Unit tests for remote embedder client (ADR-020)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.retrieval.remote_embedder import RemoteEmbedder


class _Transport(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/embed"
        body = json.loads(request.content.decode())
        texts = body["texts"]
        vectors = [[float(len(t)), 0.0, 1.0] for t in texts]
        return httpx.Response(200, json={"vectors": vectors, "count": len(vectors)})


def test_remote_embed_many(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.remote_embedder.settings.internal_service_token",
        "tok",
        raising=False,
    )
    emb = RemoteEmbedder(base_url="http://retrieval.test", token="tok")
    emb._client = httpx.Client(
        base_url="http://retrieval.test",
        transport=_Transport(),
        headers={"X-Internal-Token": "tok"},
    )
    out = emb.embed_many(["ab", "c"])
    assert out == [[2.0, 0.0, 1.0], [1.0, 0.0, 1.0]]
    assert emb.embed("xyz") == [3.0, 0.0, 1.0]
    emb.close()


def test_remote_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.remote_embedder.settings.sources_retrieval_url",
        "",
        raising=False,
    )
    with pytest.raises(RuntimeError, match="SOURCES_RETRIEVAL_URL"):
        RemoteEmbedder(base_url="")
