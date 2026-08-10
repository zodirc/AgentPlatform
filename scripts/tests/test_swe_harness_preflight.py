"""Unit tests for SWE harness preflight helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from official_bench import swe_run  # noqa: E402


def test_harness_preflight_missing_swebench(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if name == "swebench" or name.startswith("swebench."):
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(RuntimeError, match="swebench package missing"):
        swe_run._harness_preflight()


def test_harness_preflight_missing_docker_sock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "swebench", type(sys)("swebench"))

    class _FakePath(type(Path())):  # type: ignore[misc]
        def exists(self) -> bool:  # noqa: A003
            return False

    monkeypatch.setattr(swe_run, "Path", _FakePath)
    with pytest.raises(RuntimeError, match="docker.sock not mounted"):
        swe_run._harness_preflight()
