from __future__ import annotations

import hashlib
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
from .swe_images import (
    CODING_TIERS as _IMAGE_TIERS,
    harness_cfg,
    local_image_status,
    missing_images,
    pull_tier_images,
)

CODING_TIERS = {
    "n3": 3,
    "n5": 5,
    "n10": 10,
    "n25": 25,
    "full300": 300,
    "custom": None,
}
assert set(CODING_TIERS) == set(_IMAGE_TIERS)
DEFAULT_CODING_TIER = "n25"
_SLICE_DIR = Path(__file__).resolve().parents[2] / "eval" / "official" / "swe_lite_slices"


def _phase(msg: str) -> None:
    print(f"[phase] {msg}", flush=True)


def _read_instance_ids(path: Path) -> list[str]:
    if not path.is_file():
        raise ValueError(f"missing SWE Lite selection file: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resolve_coding_selection(
    *, tier: str = DEFAULT_CODING_TIER, n_instances: int | None = None
) -> tuple[str, int, list[str], str]:
    """Return tier, count, ordered IDs, and an SHA-256 selection fingerprint."""
    if tier not in CODING_TIERS:
        raise ValueError(f"unknown coding tier: {tier}; choose one of {', '.join(CODING_TIERS)}")
    order = _read_instance_ids(_SLICE_DIR / "instance_order.txt")
    if len(order) < 300:
        raise ValueError(f"instance_order.txt must contain 300 IDs, found {len(order)}")
    if tier == "custom":
        if n_instances is None or n_instances < 3:
            raise ValueError("custom coding tier requires --n-instances >= 3")
        n = min(n_instances, 300)
        ids = order[:n]
    elif tier == "full300":
        n = 300
        ids = order[:n]
    else:
        n = CODING_TIERS[tier]
        assert n is not None
        ids = _read_instance_ids(_SLICE_DIR / f"swe_lite_slice_{n}.txt")
        if len(ids) != n:
            raise ValueError(f"tier {tier} slice must contain exactly {n} IDs, found {len(ids)}")
    fingerprint = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()
    return tier, n, ids, fingerprint


def _ensure_slice_files(instances_path: Path) -> None:
    """Create missing canonical slices from the pulled HF test order only."""
    required = [_SLICE_DIR / "instance_order.txt"] + [
        _SLICE_DIR / f"swe_lite_slice_{n}.txt" for n in (3, 5, 10, 25)
    ]
    if all(path.is_file() for path in required):
        return
    order = [
        str(json.loads(line)["instance_id"])
        for line in instances_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(order) != 300:
        raise ValueError(
            f"cannot create SWE Lite slices: expected 300 pulled HF test IDs, found {len(order)}"
        )
    _SLICE_DIR.mkdir(parents=True, exist_ok=True)
    for path, ids in [
        (_SLICE_DIR / "instance_order.txt", order),
        *[(_SLICE_DIR / f"swe_lite_slice_{n}.txt", order[:n]) for n in (3, 5, 10, 25)],
    ]:
        if not path.is_file():
            path.write_text("\n".join(ids) + "\n", encoding="utf-8")


def _load_instances(
    path: Path, *, limit: int = 0, allowed_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if allowed_ids is not None and str(row.get("instance_id")) not in allowed_ids:
                continue
            rows.append(row)
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
        "Prefer edit_file for in-place fixes; end when tests should pass.\n\n"
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


def _strip_patch_fences(text: str) -> str:
    """Keep unified diff body if the model wrapped it in Markdown fences."""
    import re

    raw = (text or "").strip()
    if not raw:
        return ""
    fenced = re.search(r"```(?:diff|patch)?\s*\n([\s\S]*?)```", raw, re.I)
    if fenced:
        raw = fenced.group(1).strip()
    # Prefer a hunk that looks like a unified diff.
    if "@@" in raw or raw.startswith("--- ") or raw.startswith("diff --git"):
        return raw
    return raw


def _bench_infer_one(
    instance: dict[str, Any], *, model: str, base_url: str, api_key: str
) -> str:
    """Ask the dedicated benchmark model endpoint for a SWE-bench patch."""
    from official_bench.llm_client import chat_complete

    prompt = (
        "Solve this SWE-bench Lite issue. Return only the minimal unified diff patch; "
        "do not use Markdown fences or explain the solution.\n\n"
        f"Instance: {instance.get('instance_id')} ({instance.get('repo')})\n\n"
        f"{instance.get('problem_statement') or ''}"
    )
    # Mature path: keep DeepSeek V4 thinking ON (API default). Give a large enough
    # max_tokens so CoT (reasoning_content) + final patch (content) both fit.
    # Patch is taken from content only — never from reasoning_content.
    extra: dict[str, Any] | None = None
    provider = (os.environ.get("BENCH_MODEL_PROVIDER") or "").strip().lower()
    if (
        provider == "deepseek"
        or "deepseek" in (model or "").lower()
        or "deepseek.com" in (base_url or "").lower()
    ):
        extra = {
            "thinking": {"type": "enabled"},
            "reasoning_effort": os.environ.get("BENCH_MODEL_REASONING_EFFORT", "high"),
        }
    max_tokens = int(os.environ.get("BENCH_MODEL_MAX_TOKENS", "65536") or "65536")
    text = chat_complete(
        prompt,
        model=model,
        base_url=base_url,
        api_key=api_key,
        max_tokens=max_tokens,
        extra_body=extra,
    )
    patch = _strip_patch_fences(text)
    if not patch.strip():
        print(
            f"[coding] empty_patch instance={instance.get('instance_id')} "
            f"content_len={len(text or '')} max_tokens={max_tokens} "
            f"(thinking on; check stderr for reasoning_content_len / finish_reason)",
            flush=True,
        )
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
        _ensure_slice_files(root / "instances.jsonl")
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
    tier: str = DEFAULT_CODING_TIER,
    n_instances: int | None = None,
    run_harness: bool = False,
) -> dict[str, Any]:
    if tier not in CODING_TIERS:
        raise ValueError(f"unknown coding tier: {tier}; choose one of {', '.join(CODING_TIERS)}")
    if tier == "custom" and (n_instances is None or n_instances < 3):
        raise ValueError("custom coding tier requires --n-instances >= 3")
    cfg = load_suites()
    coding = cfg["suites"]["coding"]
    session = RunSession(suite="coding", title=f"SWE-bench Lite · infer · {tier}")
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
        instances_path = root / "instances.jsonl"
        _ensure_slice_files(instances_path)
        if limit and tier == DEFAULT_CODING_TIER and n_instances is None:
            tier, n_instances = "custom", limit
        selected_tier, selected_n, ids, fingerprint = resolve_coding_selection(
            tier=tier, n_instances=n_instances
        )
        selected_by_id = _load_instances(instances_path, allowed_ids=set(ids))
        by_id = {str(row["instance_id"]): row for row in selected_by_id}
        instances = [by_id[iid] for iid in ids if iid in by_id]
        if len(instances) != selected_n:
            raise ValueError(
                f"selected {selected_n} IDs but found {len(instances)} in pulled SWE Lite data"
            )
        infer_mode = (
            "skip_api"
            if skip_api
            else "platform_turn"
            if os.environ.get("BENCH_CODING_VIA_PLATFORM") == "1"
            else "bench_model"
        )
        session.title = f"SWE-bench Lite · infer · {selected_tier} ({selected_n})"
        session.extra.update(
            coding_tier=selected_tier,
            n_instances=selected_n,
            instance_fingerprint=fingerprint,
            infer_mode=infer_mode,
        )
        _phase(f"1/3 PULL — done · tier={selected_tier} · using {selected_n} instances")
        model_name = os.environ.get("BENCH_MODEL_NAME") or (
            "agentplatform-agent" if infer_mode == "platform_turn" else "bench-model"
        )
        if infer_mode == "platform_turn":
            base_url = os.environ.get("BENCH_API_BASE") or "http://localhost"
            api_key = (
                os.environ.get("BENCH_API_TOKEN")
                or os.environ.get("ADMIN_TOKEN")
                or os.environ.get("BENCH_MODEL_API_KEY")
                or ""
            ).strip()
        else:
            base_url = (
                os.environ.get("BENCH_MODEL_BASE_URL")
                or os.environ.get("MODEL_BASE_URL")
                or ""
            ).strip()
            api_key = (
                os.environ.get("BENCH_MODEL_API_KEY")
                or os.environ.get("MODEL_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or ""
            ).strip()
        session.extra["model_name_or_path"] = model_name
        session.extra["provider"] = (os.environ.get("BENCH_MODEL_PROVIDER") or "").strip() or None
        session.extra["api_style"] = (
            os.environ.get("BENCH_MODEL_API_STYLE") or ""
        ).strip() or None
        cw = (os.environ.get("BENCH_MODEL_CONTEXT_WINDOW") or "").strip()
        session.extra["context_window_tokens"] = int(cw) if cw.isdigit() else None

        _phase(
            "2/3 EVAL — write predictions "
            + ("skip_api (empty patches)" if skip_api else f"via {infer_mode}")
        )
        patches: dict[str, str] = {}
        if skip_api:
            session.log("infer", "skip_api — empty patches")
            print(
                "[progress] eval dataset=1/1 name=swebench_lite arm=skip_api "
                "stage=infer unit=1/1 pct=100",
                flush=True,
            )
        else:
            n_inst = len(instances)
            for i, inst in enumerate(instances):
                iid = str(inst["instance_id"])
                cur = i + 1
                pct = int(100 * cur / n_inst) if n_inst else 0
                session.log("infer", f"{cur}/{n_inst} {iid}")
                print(
                    f"[progress] eval dataset={cur}/{n_inst} name={iid} "
                    f"arm=infer stage=infer unit={cur}/{n_inst} pct={pct}",
                    flush=True,
                )
                try:
                    if infer_mode == "platform_turn":
                        patches[iid] = _api_infer_one(inst, base_url=base_url, token=api_key)
                    else:
                        patches[iid] = _bench_infer_one(
                            inst, model=model_name, base_url=base_url, api_key=api_key
                        )
                except Exception as exc:  # noqa: BLE001
                    session.log("infer_error", f"{iid}: {exc}", level="error")
                    patches[iid] = ""

        pred_path = root / (coding.get("predictions_filename") or "predictions.jsonl")
        write_predictions(instances, model_name=model_name, patches=patches, out_path=pred_path)
        non_empty = sum(1 for p in patches.values() if p.strip())
        metrics = {
            "coding_tier": selected_tier,
            "n_instances": len(instances),
            "instance_fingerprint": fingerprint,
            "infer_mode": infer_mode,
            "n_nonempty_patches": non_empty,
            "patch_rate": (non_empty / len(instances)) if instances else 0.0,
        }
        _phase(
            f"2/3 EVAL — done · patch_rate={metrics['patch_rate']:.4f} "
            f"({non_empty}/{len(instances)})"
        )
        if run_harness or os.environ.get("BENCH_CODING_HARNESS") == "1":
            _phase("3/3 REGRESS — running official SWE-bench harness")
            try:
                harness = run_swe_eval(predictions=pred_path)
                harness_metrics = harness.get("metrics") or {}
                metrics.update(harness_metrics)
            except SystemExit as exc:
                metrics["exit_code"] = exc.code if isinstance(exc.code, int) else 1
                metrics["note"] = "resolve rate requires Docker-backed harness results"
            if "resolve_rate" not in metrics:
                metrics.setdefault("note", "resolve rate requires Docker-backed harness results")
        else:
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


def _harness_report_from_disk(root: Path, harness_run_id: str) -> dict[str, Any]:
    """Best-effort read of the official harness summary JSON (rate + id lists)."""
    out: dict[str, Any] = {}
    for path in root.rglob(f"*{harness_run_id}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        # Prefer the run summary (has resolved_ids); skip per-instance report files.
        has_ids = isinstance(payload.get("resolved_ids"), list)
        if not has_ids and not any(
            k in payload for k in ("resolve_rate", "resolved_rate", "resolved", "total_instances")
        ):
            continue
        if has_ids:
            for key in (
                "resolved_ids",
                "unresolved_ids",
                "error_ids",
                "empty_patch_ids",
                "completed_ids",
                "incomplete_ids",
                "submitted_ids",
            ):
                raw = payload.get(key)
                if isinstance(raw, list):
                    out[key] = [str(x) for x in raw]
            out["report_path"] = str(path)
        for key in ("resolve_rate", "resolved_rate"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                out["resolve_rate"] = float(value)
                break
        if "resolve_rate" not in out:
            resolved = payload.get("resolved")
            if isinstance(resolved, list):
                # Some older dumps store resolved as an id list.
                out.setdefault("resolved_ids", [str(x) for x in resolved])
                submitted = payload.get("submitted") or payload.get("submitted_ids")
                if isinstance(submitted, list) and submitted:
                    out["resolve_rate"] = float(len(resolved)) / float(len(submitted))
            else:
                total = (
                    payload.get("total")
                    or payload.get("n_instances")
                    or payload.get("total_instances")
                    or payload.get("submitted_instances")
                )
                if (
                    isinstance(resolved, (int, float))
                    and isinstance(total, (int, float))
                    and total
                ):
                    out["resolve_rate"] = float(resolved) / float(total)
        if out.get("resolve_rate") is not None or out.get("resolved_ids") is not None:
            if "resolve_rate" not in out and out.get("resolved_ids") is not None:
                submitted = out.get("submitted_ids") or out.get("completed_ids")
                if isinstance(submitted, list) and submitted:
                    out["resolve_rate"] = float(len(out["resolved_ids"])) / float(
                        len(submitted)
                    )
            return out
    return out


def _resolve_rate_from_harness(root: Path, harness_run_id: str) -> float | None:
    """Best-effort read of the official harness JSON results."""
    report = _harness_report_from_disk(root, harness_run_id)
    rate = report.get("resolve_rate")
    return float(rate) if isinstance(rate, (int, float)) else None


def _harness_preflight(*, instance_ids: list[str] | None = None) -> dict[str, Any]:
    """Fail fast with actionable errors before spawning the official harness."""
    try:
        import swebench  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "swebench package missing in this process — rebuild api with "
            "`swebench` (services/api Dockerfile) or `pip install 'swebench>=2.1,<5'`"
        ) from exc
    sock = Path("/var/run/docker.sock")
    if not sock.exists():
        raise RuntimeError(
            "docker.sock not mounted — run `make up-ops-eval` so api can drive "
            "swebench.harness Docker images"
        )
    try:
        probe = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "docker CLI missing in api image — api Dockerfile must install docker-cli"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("docker info timed out — docker daemon unreachable") from exc
    if probe.returncode != 0:
        err = (probe.stderr or probe.stdout or "").strip()[:300]
        raise RuntimeError(
            "docker daemon unreachable from api "
            f"(exit={probe.returncode}): {err or 'no output'}"
        )
    h = harness_cfg()
    if h["require_local_images"] and instance_ids:
        from .swe_images import instance_image_ref

        refs = [
            instance_image_ref(iid, namespace=h["namespace"], tag=h["image_tag"])
            for iid in instance_ids
        ]
        miss = missing_images(refs)
        if miss:
            sample = ", ".join(miss[:3])
            more = f" (+{len(miss) - 3} more)" if len(miss) > 3 else ""
            raise RuntimeError(
                "SWE eval images missing locally "
                f"({len(miss)}/{len(refs)}). Pre-pull via 部署看板「SWE eval 镜像」or "
                "`make official-bench-coding-pull-images` "
                f"(missing e.g. {sample}{more}). "
                "Set SWE_HARNESS_REQUIRE_LOCAL_IMAGES=0 to allow on-demand docker pull."
            )
    return h


def run_swe_pull_images(
    *,
    tier: str | None = None,
    n_instances: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Pre-pull sweb.eval images for a coding tier (host Docker cache)."""
    h = harness_cfg()
    use_tier = (tier or h["board_tier"]).strip() or "n5"
    _phase(f"PULL-IMAGES — tier={use_tier} cache_level={h['cache_level']}")
    out = pull_tier_images(use_tier, n_instances=n_instances, force=force)
    status = local_image_status(use_tier, n_instances=n_instances)
    _phase(
        f"PULL-IMAGES — done · ready={status['ready']} "
        f"{len(status['present'])}/{status['n']} · ~{status['approx_mib_total']} MiB compressed"
    )
    return {**out, "status": status}


def _prediction_instance_ids(pred_path: Path) -> list[str]:
    """Read instance_id values from a SWE-bench predictions JSONL."""
    ids: list[str] = []
    seen: set[str] = set()
    try:
        with pred_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                iid = str((row or {}).get("instance_id") or "").strip()
                if iid and iid not in seen:
                    seen.add(iid)
                    ids.append(iid)
    except OSError:
        return []
    return ids


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
        raise RuntimeError(f"missing predictions: {pred_path} (run coding-infer first)")

    harness_run_id = f"agentplatform-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    instance_ids = _prediction_instance_ids(pred_path)
    h = _harness_preflight(instance_ids=instance_ids)
    cmd = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        coding["hf_dataset"],
        "--predictions_path",
        str(pred_path),
        "--max_workers",
        h["max_workers"],
        "--run_id",
        harness_run_id,
        "--cache_level",
        h["cache_level"],
        "--clean",
        "true" if h["clean"] else "false",
        "--namespace",
        h["namespace"],
        "--instance_image_tag",
        h["image_tag"],
    ]
    # Subset predictions must scope the harness — otherwise Lite's 300-row
    # dataset leaves hundreds "incomplete" and some harness versions exit ≠0
    # even when the submitted subset was fully graded (N0 / P6).
    if instance_ids:
        cmd.extend(["--instance_ids", *instance_ids])
    _phase(
        "1/3 PULL — predictions on disk; "
        f"cache_level={h['cache_level']} require_local={h['require_local_images']}"
    )
    _phase(
        "2/3 EVAL — official swebench.harness.run_evaluation"
        + (f" · n={len(instance_ids)}" if instance_ids else "")
    )
    session.log("evaluate", " ".join(cmd))
    session.log(
        "evaluate",
        "requires Docker + swebench; prefer pre-pulled sweb.eval "
        "(部署看板 / make official-bench-coding-pull-images)",
    )
    log_path = Path(session.dir) / "harness.stdout.log"
    with log_path.open("w", encoding="utf-8") as logf:
        logf.write(" ".join(cmd) + "\n\n")
        logf.flush()
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            check=False,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    _phase(f"2/3 EVAL — harness exit={proc.returncode}")
    _phase("3/3 REGRESS — compare resolve rate vs prior harness runs in Ops")
    log_tail = ""
    try:
        raw_log = log_path.read_text(encoding="utf-8", errors="replace")
        log_tail = raw_log[-4000:] if raw_log else ""
    except OSError:
        log_tail = ""
    metrics: dict[str, Any] = {
        "exit_code": proc.returncode,
        "harness_run_id": harness_run_id,
        "harness_log": str(log_path),
    }
    if instance_ids:
        metrics["n_instance_ids"] = float(len(instance_ids))
    report = _harness_report_from_disk(root, harness_run_id)
    resolve_rate = report.get("resolve_rate")
    if isinstance(resolve_rate, (int, float)):
        metrics["resolve_rate"] = float(resolve_rate)
    else:
        # Prefer submitted denominator when the JSON only has id lists.
        resolved_ids_tmp = report.get("resolved_ids") if isinstance(report.get("resolved_ids"), list) else []
        submitted = (
            report.get("submitted_ids")
            if isinstance(report.get("submitted_ids"), list)
            else instance_ids
        )
        if submitted:
            metrics["resolve_rate"] = float(len(resolved_ids_tmp)) / float(len(submitted))
        else:
            metrics["note"] = "resolve rate unavailable; Docker-backed harness results are required"
    resolved_ids = report.get("resolved_ids") if isinstance(report.get("resolved_ids"), list) else []
    if resolved_ids:
        metrics["n_resolved"] = float(len(resolved_ids))
    has_official_judgment = (
        isinstance(metrics.get("resolve_rate"), (int, float))
        or isinstance(report.get("resolved_ids"), list)
        or bool(report.get("report_path"))
    )
    harness_err = None
    if proc.returncode != 0:
        snippet = " ".join(log_tail.strip().split())
        if len(snippet) > 500:
            snippet = snippet[-500:]
        harness_err = f"harness exit {proc.returncode}" + (f": {snippet}" if snippet else "")
        metrics["harness_log_tail"] = log_tail[-1500:] if log_tail else ""
        # N0: if the official report exists, keep resolve_rate / id lists even when
        # the process exited non-zero (per-instance apply errors, etc.).
        if has_official_judgment:
            metrics["note"] = (
                f"harness exited {proc.returncode} but official report was archived"
            )
            harness_err = None
    session.add_case(
        "swebench.lite.evaluate",
        status="pass" if harness_err is None else "fail",
        metrics=metrics,
        error=harness_err,
    )
    result = {
        "phase": "evaluate",
        "predictions": str(pred_path),
        "harness_run_id": harness_run_id,
        "exit_code": proc.returncode,
        "instance_ids": instance_ids,
        "resolved_ids": resolved_ids,
        "unresolved_ids": report.get("unresolved_ids") or [],
        "error_ids": report.get("error_ids") or [],
        "empty_patch_ids": report.get("empty_patch_ids") or [],
        "harness_report_path": report.get("report_path"),
        "harness_log": str(log_path),
    }
    result_status = "completed" if harness_err is None else "failed"
    manifest = session.finish(
        status=result_status,
        error=harness_err,
        metrics=metrics,
        result=result,
    )
    manifest["publish"] = publish_manifest(manifest)
    print(f"[coding] HTML → {session.dir / 'report.html'}")
    if log_tail and proc.returncode != 0:
        print(f"[coding] harness log → {log_path}", flush=True)
    (reports_dir() / "swebench_lite_eval.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    if harness_err is not None:
        raise RuntimeError(harness_err)
    return manifest
