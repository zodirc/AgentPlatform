"""Unit tests for solve-side sweb.eval run_tests gating."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.tools.core import swe_solve_env as sse


def test_load_swe_instance_marker(tmp_path: Path) -> None:
    assert sse.load_swe_instance_marker(tmp_path) is None
    (tmp_path / sse.MARKER_NAME).write_text(
        json.dumps(
            {
                "instance_id": "astropy__astropy-12907",
                "image_ref": "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest",
            }
        ),
        encoding="utf-8",
    )
    m = sse.load_swe_instance_marker(tmp_path)
    assert m is not None
    assert m["instance_id"] == "astropy__astropy-12907"


def test_require_solve_env_missing_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sse, "docker_sock_available", lambda: True)
    monkeypatch.setattr(sse, "docker_cli_available", lambda: False)
    marker = {
        "instance_id": "x__1",
        "image_ref": "swebench/sweb.eval.x86_64.missing:latest",
    }
    err = sse.require_solve_env(marker)
    assert err is not None
    assert err["error"] == "swe_eval_docker_cli_missing"


def test_require_solve_env_missing_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sse, "docker_sock_available", lambda: True)
    monkeypatch.setattr(sse, "docker_cli_available", lambda: True)
    monkeypatch.setattr(sse, "docker_image_present", lambda ref, **k: False)
    marker = {
        "instance_id": "x__1",
        "image_ref": "swebench/sweb.eval.x86_64.missing:latest",
    }
    err = sse.require_solve_env(marker)
    assert err is not None
    assert err["error"] == "swe_eval_image_missing"


def test_require_solve_env_smoke_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELEASE_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("SWE_EVAL_REQUIRE_SMOKE", "1")
    monkeypatch.setattr(sse, "docker_sock_available", lambda: True)
    monkeypatch.setattr(sse, "docker_cli_available", lambda: True)
    monkeypatch.setattr(sse, "docker_image_present", lambda ref, **k: True)
    ref = "swebench/sweb.eval.x86_64.a:latest"
    (tmp_path / "swe_eval_images_smoke.json").write_text(
        json.dumps(
            {
                "by_ref": {
                    ref: {"ref": ref, "ok": False, "error": "smoke_exit_1", "exit_code": 1}
                }
            }
        ),
        encoding="utf-8",
    )
    err = sse.require_solve_env({"instance_id": "a", "image_ref": ref})
    assert err is not None
    assert err["error"] == "swe_eval_env_smoke_failed"


def test_require_solve_env_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASE_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("SWE_EVAL_REQUIRE_SMOKE", "1")
    monkeypatch.setattr(sse, "docker_sock_available", lambda: True)
    monkeypatch.setattr(sse, "docker_cli_available", lambda: True)
    monkeypatch.setattr(sse, "docker_image_present", lambda ref, **k: True)
    ref = "swebench/sweb.eval.x86_64.a:latest"
    (tmp_path / "swe_eval_images_smoke.json").write_text(
        json.dumps({"by_ref": {ref: {"ref": ref, "ok": True, "exit_code": 0}}}),
        encoding="utf-8",
    )
    assert sse.require_solve_env({"instance_id": "a", "image_ref": ref}) is None


def test_maybe_run_skips_without_ops_eval(tmp_path: Path) -> None:
    (tmp_path / sse.MARKER_NAME).write_text(
        json.dumps({"instance_id": "a", "image_ref": "img:latest"}),
        encoding="utf-8",
    )
    assert (
        sse.maybe_run_swe_eval_tests(
            work_root=tmp_path,
            argv=["pytest", "-q"],
            display_command="pytest -q",
            timeout_s=10,
            ops_eval=False,
        )
        is None
    )


def test_maybe_run_hard_fails_missing_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sse, "docker_sock_available", lambda: True)
    monkeypatch.setattr(sse, "docker_image_present", lambda ref, **k: False)
    (tmp_path / sse.MARKER_NAME).write_text(
        json.dumps(
            {
                "instance_id": "a",
                "image_ref": "swebench/sweb.eval.x86_64.missing:latest",
            }
        ),
        encoding="utf-8",
    )
    out = sse.maybe_run_swe_eval_tests(
        work_root=tmp_path,
        argv=["pytest", "-q"],
        display_command="pytest -q",
        timeout_s=10,
        ops_eval=True,
    )
    assert out is not None
    assert out["error"] == "swe_eval_image_missing"
    assert out["status"] == "failed"


def test_container_name_stable() -> None:
    a = sse.container_name_for("astropy__astropy-14182")
    b = sse.container_name_for("astropy__astropy-14182")
    assert a == b
    assert a.startswith("ap-swe-solve-")
    assert len(a) < 120


def test_sync_incremental_tracks_fingerprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pkg").mkdir()
    f = tmp_path / "pkg" / "a.py"
    f.write_text("x=1\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_docker(args, *, input_bytes=None, timeout=30.0):  # noqa: ANN001
        calls.append(list(args))
        class P:
            returncode = 0
            stdout = b""
            stderr = b""

        return P()

    monkeypatch.setattr(sse, "_docker", fake_docker)
    meta = sse.sync_worktree_to_container(
        container="ap-swe-solve-demo",
        work_root=tmp_path,
        testbed="/testbed",
        force_full=True,
    )
    assert meta["ok"] is True
    assert meta["mode"] == "full"
    # Second sync with no changes → incremental, 0 changed files packed (no tar exec if empty)
    meta2 = sse.sync_worktree_to_container(
        container="ap-swe-solve-demo",
        work_root=tmp_path,
        testbed="/testbed",
    )
    assert meta2["ok"] is True
    assert meta2["mode"] == "incremental"
    assert meta2["changed"] == 0
    f.write_text("x=2\n", encoding="utf-8")
    meta3 = sse.sync_worktree_to_container(
        container="ap-swe-solve-demo",
        work_root=tmp_path,
        testbed="/testbed",
    )
    assert meta3["ok"] is True
    assert meta3["changed"] == 1


def test_probe_uses_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = "swebench/sweb.eval.x86_64.a:latest"
    (tmp_path / sse.MARKER_NAME).write_text(
        json.dumps({"instance_id": "a", "image_ref": ref}),
        encoding="utf-8",
    )
    (tmp_path / sse.PROBE_CACHE_NAME).write_text(
        json.dumps(
            {
                "ok": True,
                "image_ref": ref,
                "summary": "cached ready",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sse, "require_solve_env", lambda m: None)
    out = sse.probe_solve_env(work_root=tmp_path, use_cache=True)
    assert out["ok"] is True
    assert out.get("cached") is True
