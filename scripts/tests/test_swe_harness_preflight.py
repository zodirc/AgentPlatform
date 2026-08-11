"""Unit tests for SWE harness preflight helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from official_bench import swe_images, swe_run  # noqa: E402


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


def test_prediction_instance_ids(tmp_path: Path) -> None:
    pred = tmp_path / "predictions.jsonl"
    pred.write_text(
        '{"instance_id":"a__1","model_patch":""}\n'
        '{"instance_id":"b__2","model_patch":"x"}\n'
        '{"instance_id":"a__1","model_patch":"dup"}\n',
        encoding="utf-8",
    )
    assert swe_run._prediction_instance_ids(pred) == ["a__1", "b__2"]


def test_instance_image_ref() -> None:
    assert (
        swe_images.instance_image_ref("astropy__astropy-12907")
        == "swebench/sweb.eval.x86_64.astropy__astropy-12907:latest"
    )


def test_harness_preflight_require_local_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "swebench", type(sys)("swebench"))

    class _SockPath(type(Path())):  # type: ignore[misc]
        def exists(self) -> bool:  # noqa: A003
            return True

    monkeypatch.setattr(swe_run, "Path", _SockPath)

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr(
        swe_run.subprocess,
        "run",
        lambda *a, **k: _Proc(),
    )
    monkeypatch.setenv("SWE_HARNESS_REQUIRE_LOCAL_IMAGES", "1")
    monkeypatch.setattr(swe_images, "docker_image_present", lambda ref, **k: False)
    # missing_images imports docker_image_present from module namespace
    monkeypatch.setattr(
        swe_run,
        "missing_images",
        lambda refs: list(refs),
    )
    with pytest.raises(RuntimeError, match="SWE eval images missing"):
        swe_run._harness_preflight(instance_ids=["astropy__astropy-12907"])


def test_write_progress_for_board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASE_STATUS_DIR", str(tmp_path))
    swe_images.write_progress(
        {
            "status": "building",
            "phase": "pull",
            "tier": "n5",
            "images_total": 5,
            "images_done": 2,
            "last_status": "pulling",
            "current_short": "sweb.eval.x86_64.astropy__astropy-12907:latest",
        }
    )
    prog = swe_images.read_progress(max_age_s=60)
    assert prog is not None
    assert prog["images_done"] == 2
    assert prog["images_total"] == 5
    assert (tmp_path / "swe_eval_images_progress.json").is_file()


def test_pull_images_cached_emits_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELEASE_STATUS_DIR", str(tmp_path))
    monkeypatch.setattr(swe_images, "docker_image_present", lambda ref, **k: True)
    out = swe_images.pull_images(
        ["swebench/sweb.eval.x86_64.demo:latest"],
        tier="n5",
    )
    assert out["n"] == 1
    assert out["results"][0]["status"] == "cached"
    prog = swe_images.read_progress(max_age_s=60)
    assert prog is not None
    assert prog["status"] == "ready"
    assert prog["images_done"] == 1
    assert prog["images_cached"] == 1
