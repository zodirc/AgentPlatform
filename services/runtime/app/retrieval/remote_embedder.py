"""Remote embedder client — orchestrator calls sources-retrieval over HTTP."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)


class RemoteEmbedder:
    """HTTP client to ``sources-retrieval`` ``POST /internal/embed``.

    Keeps embedding weights off the orchestrator process (ADR-020).
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (
            base_url
            or getattr(settings, "sources_retrieval_url", "")
            or ""
        ).rstrip("/")
        if not self.base_url:
            raise RuntimeError(
                "EMBEDDING_BACKEND=remote requires SOURCES_RETRIEVAL_URL"
            )
        self.token = token if token is not None else settings.internal_service_token
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"X-Internal-Token": self.token},
        )

    def embed(self, text: str, *, lane: int | None = None) -> list[float]:
        vectors = self.embed_many([text], lane=lane)
        return vectors[0] if vectors else []

    def embed_many(
        self, texts: Sequence[str], *, lane: int | None = None
    ) -> list[list[float]]:
        if not texts:
            return []
        body: dict[str, Any] = {"texts": list(texts)}
        if lane is not None:
            body["lane"] = int(lane)
        resp = self._client.post("/internal/embed", json=body)
        resp.raise_for_status()
        data = resp.json()
        vectors = data.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError("remote embed: malformed vectors response")
        return [list(map(float, row)) for row in vectors]

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            logger.debug("remote embedder close failed", exc_info=True)
