"""Unit tests for SWE harness preflight helpers."""

from __future__ import annotations

import json
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


def test_harness_dataset_arg_prefers_local_jsonl(tmp_path: Path) -> None:
    root = tmp_path / "swebench_lite"
    root.mkdir()
    instances = root / "instances.jsonl"
    instances.write_text('{"instance_id":"astropy__astropy-12907"}\n', encoding="utf-8")
    assert swe_run._harness_dataset_arg(root) == str(instances.resolve())


def test_harness_dataset_arg_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="instances.jsonl"):
        swe_run._harness_dataset_arg(tmp_path)
    empty = tmp_path / "instances.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="instances.jsonl"):
        swe_run._harness_dataset_arg(tmp_path)


def test_stream_harness_process_applies_env_extra(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    class _FakeStdout:
        def read(self, _n: int) -> bytes:
            return b""

        def close(self) -> None:
            return None

    class _FakeProc:
        stdout = _FakeStdout()

        def wait(self) -> int:
            return 0

    def _fake_popen(cmd, **kwargs):  # noqa: ANN001, ANN003
        seen["cmd"] = cmd
        seen["env"] = kwargs.get("env") or {}
        return _FakeProc()

    monkeypatch.setattr(swe_run.subprocess, "Popen", _fake_popen)
    log_path = tmp_path / "harness.log"
    code = swe_run._stream_harness_process(
        ["true"],
        cwd=str(tmp_path),
        log_path=log_path,
        env_extra={"HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"},
    )
    assert code == 0
    assert seen["env"].get("HF_HUB_OFFLINE") == "1"
    assert seen["env"].get("HF_DATASETS_OFFLINE") == "1"


def test_instance_image_ref() -> None:
    assert (
        swe_images.instance_image_ref("astropy__astropy-12907")
        == "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"
    )
    # Docker Hub slug is lowercased + __ → _1776_
    assert (
        swe_images.instance_image_ref("Django__django-10554")
        == "swebench/sweb.eval.x86_64.django_1776_django-10554:latest"
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
            "current_short": "sweb.eval.x86_64.astropy_1776_astropy-12907:latest",
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
        skip_smoke=True,
    )
    assert out["n"] == 1
    assert out["results"][0]["status"] == "cached"
    prog = swe_images.read_progress(max_age_s=60)
    assert prog is not None
    assert prog["status"] == "ready"
    assert prog["images_done"] == 1
    assert prog["images_cached"] == 1
    assert prog.get("smoke_skipped") is True


def test_smoke_image_ok_and_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Ok:
        returncode = 0
        stdout = "Python 3.11\npytest 7.0\n"
        stderr = ""

    class _Fail:
        returncode = 2
        stdout = ""
        stderr = "pytest: command not found"

    calls: list[list[str]] = []

    def _run(argv, **kwargs):  # noqa: ANN001, ANN003
        calls.append(list(argv))
        if any("fail-image" in a for a in argv):
            return _Fail()
        return _Ok()

    monkeypatch.setattr(swe_images.subprocess, "run", _run)
    ok = swe_images.smoke_image("swebench/sweb.eval.x86_64.ok:latest")
    assert ok["ok"] is True
    assert ok["exit_code"] == 0
    assert "docker" in calls[0][0]
    assert "--network" in calls[0]
    bad = swe_images.smoke_image("swebench/sweb.eval.x86_64.fail-image:latest")
    assert bad["ok"] is False
    assert bad["error"] == "smoke_exit_2"


def test_pull_images_runs_smoke_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELEASE_STATUS_DIR", str(tmp_path))
    monkeypatch.setattr(swe_images, "docker_image_present", lambda ref, **k: True)

    def _smoke(refs, **kwargs):  # noqa: ANN001, ANN003
        by_ref = {
            r: {"ref": r, "ok": True, "exit_code": 0, "elapsed_s": 0.1} for r in refs
        }
        payload = {
            "tier": kwargs.get("tier"),
            "n": len(refs),
            "ok_n": len(refs),
            "failed_n": 0,
            "all_ok": True,
            "by_ref": by_ref,
            "failed": [],
        }
        swe_images.write_smoke_results(payload)
        return payload

    monkeypatch.setattr(swe_images, "smoke_images", _smoke)
    ref = "swebench/sweb.eval.x86_64.demo:latest"
    out = swe_images.pull_images([ref], tier="n5")
    assert out["smoke"]["all_ok"] is True
    stored = swe_images.read_smoke_results(max_age_s=60)
    assert stored is not None
    assert stored["by_ref"][ref]["ok"] is True
    smoke = swe_images.read_smoke_ok_for_refs([ref])
    assert smoke["all_ok"] is True


def test_local_image_status_requires_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELEASE_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("SWE_EVAL_REQUIRE_SMOKE", "1")
    refs = ["swebench/sweb.eval.x86_64.a:latest", "swebench/sweb.eval.x86_64.b:latest"]
    monkeypatch.setattr(swe_images, "image_refs_for_tier", lambda *a, **k: refs)
    monkeypatch.setattr(swe_images, "docker_image_present", lambda ref, **k: True)
    st = swe_images.local_image_status("n5")
    assert st["images_ready"] is True
    assert st["smoke_ready"] is False
    assert st["ready"] is False
    assert len(st["smoke_missing"]) == 2

    swe_images.write_smoke_results(
        {
            "tier": "n5",
            "n": 2,
            "ok_n": 2,
            "failed_n": 0,
            "all_ok": True,
            "by_ref": {
                refs[0]: {"ref": refs[0], "ok": True},
                refs[1]: {"ref": refs[1], "ok": True},
            },
            "failed": [],
        }
    )
    st2 = swe_images.local_image_status("n5")
    assert st2["ready"] is True
    assert st2["smoke_ready"] is True


def test_local_image_status_smoke_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELEASE_STATUS_DIR", str(tmp_path))
    refs = ["swebench/sweb.eval.x86_64.a:latest"]
    monkeypatch.setattr(swe_images, "image_refs_for_tier", lambda *a, **k: refs)
    monkeypatch.setattr(swe_images, "docker_image_present", lambda ref, **k: True)
    swe_images.write_smoke_results(
        {
            "tier": "n5",
            "n": 1,
            "ok_n": 0,
            "failed_n": 1,
            "all_ok": False,
            "by_ref": {refs[0]: {"ref": refs[0], "ok": False, "error": "smoke_exit_1"}},
            "failed": [{"ref": refs[0], "error": "smoke_exit_1"}],
        }
    )
    st = swe_images.local_image_status("n5")
    assert st["images_ready"] is True
    assert st["ready"] is False
    assert st["smoke_failed"]


def test_docker_pull_progress_parser() -> None:
    class _Clock:
        def __init__(self) -> None:
            self.t = 1000.0

        def __call__(self) -> float:
            return self.t

        def advance(self, dt: float) -> None:
            self.t += dt

    clock = _Clock()
    t = swe_images.DockerPullProgress(clock=clock)
    assert t.feed("abc12345: Pulling fs layer")
    assert t.feed("abc12345: Downloading [==>] 12.5MB/100MB")
    assert t.feed("def67890: Pulling fs layer")
    assert t.feed("def67890: Waiting")
    snap = t.snapshot()
    assert snap["layers_total"] == 2
    assert snap["layers_downloading"] == 1
    assert snap["layers_waiting"] == 1
    assert snap["bytes_done"] == int(12.5 * 1024**2)
    assert snap["bytes_total"] == int(100 * 1024**2)
    assert snap["layer_pct"] == 12.5
    assert "12.5MiB/100.0MiB" in (snap["layer_detail"] or "")
    clock.advance(1.0)
    assert t.feed("abc12345: Downloading [====>] 37.5MB/100MB")
    snap_speed = t.snapshot()
    assert snap_speed["speed_bps"] is not None
    assert snap_speed["speed_bps"] > 1e6  # ~25 MiB over 1s
    assert snap_speed["speed_label"] and "MiB/s" in snap_speed["speed_label"]
    assert snap_speed["speed_label"] in (snap_speed["layer_detail"] or "")
    assert t.feed("abc12345: Download complete")
    assert t.feed("abc12345: Pull complete")
    snap2 = t.snapshot()
    assert snap2["layers_done"] == 1
    assert snap2["layers_downloaded"] >= 1


def test_fmt_speed_units() -> None:
    assert swe_images._fmt_speed(None) is None
    assert swe_images._fmt_speed(100.0) == "100 B/s"
    assert swe_images._fmt_speed(2048.0) == "2.0 KiB/s"
    assert "MiB/s" in (swe_images._fmt_speed(3.5 * 1024**2) or "")


def test_harness_report_picks_newest_matching_run(tmp_path: Path) -> None:
    run_id = "agentplatform-20260816120000"
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / f"{run_id}.json").write_text(
        json.dumps(
            {
                "resolved_ids": ["old__1"],
                "submitted_ids": ["old__1"],
                "resolve_rate": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (new / f"{run_id}.json").write_text(
        json.dumps(
            {
                "resolved_ids": ["new__1"],
                "unresolved_ids": ["new__2"],
                "submitted_ids": ["new__1", "new__2"],
                "resolve_rate": 0.5,
            }
        ),
        encoding="utf-8",
    )
    import os
    import time

    os.utime(old / f"{run_id}.json", (1, 1))
    now = time.time()
    os.utime(new / f"{run_id}.json", (now, now))
    out = swe_run._harness_report_from_disk(tmp_path, run_id)
    assert out["resolve_rate"] == 0.5
    assert out["resolved_ids"] == ["new__1"]


def test_harness_report_rejects_disjoint_instance_set(tmp_path: Path) -> None:
    run_id = "agentplatform-20260816120100"
    (tmp_path / f"{run_id}.json").write_text(
        json.dumps(
            {
                "resolved_ids": ["other__1"],
                "submitted_ids": ["other__1"],
                "resolve_rate": 1.0,
            }
        ),
        encoding="utf-8",
    )
    out = swe_run._harness_report_from_disk(
        tmp_path, run_id, expected_instance_ids=["ours__1", "ours__2"]
    )
    assert out == {}


def test_harness_report_accepts_overlapping_instance_set(tmp_path: Path) -> None:
    run_id = "agentplatform-20260816120200"
    (tmp_path / f"{run_id}.json").write_text(
        json.dumps(
            {
                "resolved_ids": ["ours__1"],
                "unresolved_ids": ["ours__2"],
                "submitted_ids": ["ours__1", "ours__2"],
                "resolve_rate": 0.5,
            }
        ),
        encoding="utf-8",
    )
    out = swe_run._harness_report_from_disk(
        tmp_path, run_id, expected_instance_ids=["ours__1", "ours__2"]
    )
    assert out["resolve_rate"] == 0.5
    assert out["resolved_ids"] == ["ours__1"]
