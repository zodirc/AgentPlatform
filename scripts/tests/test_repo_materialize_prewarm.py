from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.repo_materialize import prewarm_repo_mirrors  # noqa: E402


def test_prewarm_repo_mirrors_dedupes_and_reports(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_ensure(repo: str, *, timeout_s: int = 600):
        calls.append(repo)
        if repo == "bad/repo":
            raise RuntimeError("boom")
        return tmp_path / f"{repo.replace('/', '__')}.git"

    monkeypatch.setattr(
        "official_bench.repo_materialize.ensure_repo_mirror",
        fake_ensure,
    )
    out = prewarm_repo_mirrors(
        ["owner/a", "owner/a", "owner/b", "bad/repo", ""],
        timeout_s=10,
    )
    assert out["n_repos"] == 3
    assert set(out["ok"]) == {"owner/a", "owner/b"}
    assert "bad/repo" in out["failed"]
    assert calls == ["bad/repo", "owner/a", "owner/b"]  # sorted unique
