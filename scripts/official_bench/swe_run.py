from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_suites
from .paths import ensure_dirs, reports_dir, suite_data
from .publish import publish_manifest
from .pull import pull_swebench
from .run_session import RunSession


def _phase(msg: str) -> None:
    print(f"[phase] {msg}", flush=True)


def _load_instances(path: Path, *, limit: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def _api_infer_one(instance: dict[str, Any], *, base_url: str, token: str) -> str:
    """Best-effort Turn against local Agent Platform (agent scenario).

    Returns a unified diff string (may be empty if the model did not emit a patch).
    """
    try:
        import httpx
    except ImportError as e:
        raise SystemExit(
            "SWE infer needs httpx. pip install -r eval/official/requirements.txt"
        ) from e

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    problem = instance.get("problem_statement") or ""
    iid = instance.get("instance_id")
    repo = instance.get("repo")
    hint = (
        f"SWE-bench instance {iid} ({repo}).\n"
        "Produce a minimal unified diff patch that fixes the issue. "
        "Prefer propose_patch / file edits; end when tests should pass.\n\n"
        f"{problem}"
    )

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=600.0, headers=headers) as client:
        # Create session (best-effort shapes used by this repo)
        sess = client.post("/api/v1/sessions", json={"title": f"swe-{iid}", "scenario_id": "agent"})
        if sess.status_code >= 400:
            sess = client.post("/api/v1/sessions", json={})
        sess.raise_for_status()
        session_id = sess.json().get("id") or sess.json().get("session_id")
        turn = client.post(
            f"/api/v1/sessions/{session_id}/turns",
            json={"message": hint, "scenario_id": "agent"},
        )
        turn.raise_for_status()
        body = turn.json()
        # Patch extraction is best-effort from view/artifacts if present
        patch = ""
        view = body.get("view") or body
        for key in ("patches", "proposed_patches", "artifacts"):
            blob = view.get(key) if isinstance(view, dict) else None
            if isinstance(blob, list) and blob:
                first = blob[0]
                if isinstance(first, dict):
                    patch = str(first.get("diff") or first.get("patch") or "")
                elif isinstance(first, str):
                    patch = first
                break
        return patch


def write_predictions(
    instances: list[dict[str, Any]],
    *,
    model_name: str,
    patches: dict[str, str],
    out_path: Path,
) -> Path:
    """SWE-bench harness prediction JSONL: instance_id, model_name_or_path, model_patch."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for inst in instances:
            iid = str(inst["instance_id"])
            row = {
                "instance_id": iid,
                "model_name_or_path": model_name,
                "model_patch": patches.get(iid, ""),
            }
            f.write(json.dumps(row) + "\n")
    return out_path


def run_swe_pull_only(*, force_pull: bool = False) -> dict[str, Any]:
    cfg = load_suites()
    coding = cfg["suites"]["coding"]
    session = RunSession(suite="coding", title="SWE-bench Lite · pull")
    session.extra = {
        "protocol_version": cfg.get("protocol_version"),
        "official": coding.get("official"),
        "phase": "pull",
    }
    try:
        _phase("1/3 PULL — SWE-bench Lite (skip if cached)")
        session.log("pull", coding["hf_dataset"])
        root = pull_swebench(cfg, force=force_pull)
        instances = _load_instances(root / "instances.jsonl")
        _phase(f"1/3 PULL — done · n_instances={len(instances)}")
        _phase("2/3 EVAL — skipped on pull-only target")
        _phase("3/3 REGRESS — skipped on pull-only target")
        session.add_case(
            "swebench.lite.pull",
            status="pass",
            metrics={"n_instances": len(instances)},
        )
        result = {
            "phase": "pulled",
            "data_dir": str(root),
            "n_instances": len(instances),
            "next": [
                "make official-bench-coding-infer",
                "make official-bench-coding-eval",
            ],
        }
        manifest = session.finish(status="completed", metrics=result, result=result)
        manifest["publish"] = publish_manifest(manifest)
        print(f"[coding] HTML → {session.dir / 'report.html'}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        session.log("error", str(exc), level="error")
        manifest = session.finish(status="failed", error=str(exc))
        publish_manifest(manifest)
        raise


def run_swe_infer(
    *,
    force_pull: bool = False,
    limit: int = 0,
    skip_api: bool = False,
) -> dict[str, Any]:
    cfg = load_suites()
    coding = cfg["suites"]["coding"]
    session = RunSession(suite="coding", title="SWE-bench Lite · infer")
    session.extra = {
        "protocol_version": cfg.get("protocol_version"),
        "official": coding.get("official"),
        "phase": "infer",
        "skip_api": skip_api,
    }
    try:
        _phase("1/3 PULL — ensure SWE instances (skip if cached)")
        session.log("pull", "ensure instances")
        root = pull_swebench(cfg, force=force_pull)
        max_cfg = int(coding.get("max_instances") or 0)
        use_limit = limit or max_cfg
        instances = _load_instances(root / "instances.jsonl", limit=use_limit)
        _phase(f"1/3 PULL — done · using {len(instances)} instances")
        model_name = os.environ.get("BENCH_MODEL_NAME") or "agentplatform-agent"
        base_url = os.environ.get("BENCH_API_BASE") or "http://localhost"
        token = (
            os.environ.get("BENCH_API_TOKEN")
            or os.environ.get("ADMIN_TOKEN")
            or ""
        ).strip()
        session.extra["model_name_or_path"] = model_name

        _phase(
            "2/3 EVAL — write predictions "
            + ("skip_api (empty patches)" if skip_api else f"via {base_url}")
        )
        patches: dict[str, str] = {}
        if skip_api:
            session.log("infer", "skip_api — empty patches")
        else:
            for i, inst in enumerate(instances):
                iid = str(inst["instance_id"])
                session.log("infer", f"{i + 1}/{len(instances)} {iid}")
                try:
                    patches[iid] = _api_infer_one(inst, base_url=base_url, token=token)
                except Exception as exc:  # noqa: BLE001
                    session.log("infer_error", f"{iid}: {exc}", level="error")
                    patches[iid] = ""

        pred_path = root / (coding.get("predictions_filename") or "predictions.jsonl")
        write_predictions(instances, model_name=model_name, patches=patches, out_path=pred_path)
        non_empty = sum(1 for p in patches.values() if p.strip())
        metrics = {
            "n_instances": len(instances),
            "n_nonempty_patches": non_empty,
            "patch_rate": (non_empty / len(instances)) if instances else 0.0,
        }
        _phase(
            f"2/3 EVAL — done · patch_rate={metrics['patch_rate']:.4f} "
            f"({non_empty}/{len(instances)})"
        )
        _phase("3/3 REGRESS — compare patch_rate in Ops history / official harness later")
        session.add_case(
            "swebench.lite.infer",
            status="skipped" if skip_api else ("pass" if non_empty else "fail"),
            metrics=metrics,
        )
        result = {
            "phase": "predictions",
            "predictions": str(pred_path),
            "metrics": metrics,
            "model_name_or_path": model_name,
        }
        manifest = session.finish(
            status="completed" if skip_api or non_empty else "failed",
            metrics=metrics,
            result=result,
        )
        manifest["publish"] = publish_manifest(manifest)
        print(f"[coding] HTML → {session.dir / 'report.html'}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        session.log("error", str(exc), level="error")
        manifest = session.finish(status="failed", error=str(exc))
        publish_manifest(manifest)
        raise


def run_swe_eval(*, predictions: Path | None = None) -> dict[str, Any]:
    """Invoke official SWE-bench evaluation harness if installed."""
    ensure_dirs()
    cfg = load_suites()
    coding = cfg["suites"]["coding"]
    session = RunSession(suite="coding", title="SWE-bench Lite · official evaluate")
    session.extra = {
        "protocol_version": cfg.get("protocol_version"),
        "official": coding.get("official"),
        "phase": "evaluate",
    }
    root = suite_data("swebench_lite")
    pred_path = predictions or (root / (coding.get("predictions_filename") or "predictions.jsonl"))
    if not pred_path.exists():
        raise SystemExit(f"missing predictions: {pred_path} (run coding-infer first)")

    harness_run_id = f"agentplatform-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    cmd = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        coding["hf_dataset"],
        "--predictions_path",
        str(pred_path),
        "--max_workers",
        os.environ.get("SWE_MAX_WORKERS", "2"),
        "--run_id",
        harness_run_id,
    ]
    _phase("1/3 PULL — predictions already on disk (harness may pull Docker images)")
    _phase("2/3 EVAL — official swebench.harness.run_evaluation")
    session.log("evaluate", " ".join(cmd))
    session.log("evaluate", "requires Docker + pip install swebench; large image download possible")
    proc = subprocess.run(cmd, cwd=str(root), check=False)
    _phase(f"2/3 EVAL — harness exit={proc.returncode}")
    _phase("3/3 REGRESS — compare resolve rate vs prior harness runs in Ops")
    metrics = {"exit_code": proc.returncode, "harness_run_id": harness_run_id}
    session.add_case(
        "swebench.lite.evaluate",
        status="pass" if proc.returncode == 0 else "fail",
        metrics=metrics,
        error=None if proc.returncode == 0 else f"exit {proc.returncode}",
    )
    result = {
        "phase": "evaluate",
        "predictions": str(pred_path),
        "harness_run_id": harness_run_id,
        "exit_code": proc.returncode,
    }
    manifest = session.finish(
        status="completed" if proc.returncode == 0 else "failed",
        error=None if proc.returncode == 0 else f"harness exit {proc.returncode}",
        metrics=metrics,
        result=result,
    )
    manifest["publish"] = publish_manifest(manifest)
    print(f"[coding] HTML → {session.dir / 'report.html'}")
    (reports_dir() / "swebench_lite_eval.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return manifest
