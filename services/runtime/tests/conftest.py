from __future__ import annotations

from pathlib import Path

import pytest

from app.retrieval.embedder import reset_embedder_cache
from app.settings import settings


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _isolate_host_deploy_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Keep unit tests off host ``.env`` / compose deploy knobs.

    Developers often export ``EMBEDDING_BACKEND=sentence_transformers``,
    ``DATABASE_URL=...@postgres``, ``DATA_DIR=/data`` from project ``.env``.
    Those break hash-only unit tests (ST ImportError, DNS hang, PermissionError).
    """
    data = tmp_path_factory.mktemp("runtime-data")
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    monkeypatch.setattr(settings, "embedding_model", "hash")
    monkeypatch.setattr(settings, "retrieval_backend", "json")
    monkeypatch.setattr(settings, "data_dir", str(data))
    monkeypatch.setattr(settings, "workspace_root", str(data / "workspace"))
    # Fail fast if any code still tries the docker hostname from compose .env.
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql://agent:agent@127.0.0.1:1/agent",
    )
    reset_embedder_cache()
    yield
    reset_embedder_cache()
