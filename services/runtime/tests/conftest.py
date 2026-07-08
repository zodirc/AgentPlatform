from __future__ import annotations

from pathlib import Path

import pytest

from app.settings import settings


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    return tmp_path
