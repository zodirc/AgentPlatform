"""SWE-bench Lite official eval image refs (sweb.eval) — local cache helpers.

Images are ~1GiB compressed each and must not live in git. Pre-pull via
部署看板 or ``make official-bench-coding-pull-images``. Config:
``eval/official/suites.small.yaml`` → ``suites.coding.harness``.

Progress for the release console is written to
``reports/release/swe_eval_images_progress.json`` (override with
``RELEASE_STATUS_DIR``).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import load_suites

_SLICE_DIR = Path(__file__).resolve().parents[2] / "eval" / "official" / "swe_lite_slices"
_ROOT = Path(__file__).resolve().parents[2]

CODING_TIERS = {
    "n3": 3,
    "n5": 5,
    "n10": 10,
    "n25": 25,
    "full300": 300,
    "custom": None,
}


def progress_path() -> Path:
    base = Path(
        os.environ.get("RELEASE_STATUS_DIR")
        or (_ROOT / "reports" / "release")
    )
    return base / "swe_eval_images_progress.json"


def write_progress(payload: dict[str, Any]) -> None:
    """Atomic-ish progress write for 部署看板 live overlay."""
    path = progress_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        **payload,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_progress(*, max_age_s: float = 600.0) -> dict[str, Any] | None:
    path = progress_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get("updated_at") or "").strip()
    if raw and max_age_s > 0:
        try:
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (time.time() - dt.timestamp()) > max_age_s:
                return None
        except Exception:
            pass
    return data


def harness_cfg(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    suites = cfg if cfg is not None else load_suites()
    coding = (suites.get("suites") or {}).get("coding") or {}
    raw = coding.get("harness") if isinstance(coding.get("harness"), dict) else {}
    return {
        "cache_level": str(
            os.environ.get("SWE_HARNESS_CACHE_LEVEL")
            or raw.get("cache_level")
            or "instance"
        ).strip()
        or "instance",
        "clean": _env_bool(
            "SWE_HARNESS_CLEAN",
            default=bool(raw.get("clean", False)),
        ),
        "namespace": str(
            os.environ.get("SWE_HARNESS_NAMESPACE") or raw.get("namespace") or "swebench"
        ).strip()
        or "swebench",
        "image_tag": str(
            os.environ.get("SWE_HARNESS_IMAGE_TAG") or raw.get("image_tag") or "latest"
        ).strip()
        or "latest",
        "max_workers": str(
            os.environ.get("SWE_MAX_WORKERS")
            or raw.get("max_workers")
            or "2"
        ).strip()
        or "2",
        "board_tier": str(
            os.environ.get("SWE_HARNESS_BOARD_TIER")
            or raw.get("board_tier")
            or "n5"
        ).strip()
        or "n5",
        "require_local_images": _env_bool(
            "SWE_HARNESS_REQUIRE_LOCAL_IMAGES",
            default=bool(raw.get("require_local_images", True)),
        ),
        "approx_mib_per_image": int(raw.get("approx_mib_per_image") or 1100),
    }


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def instance_image_ref(
    instance_id: str,
    *,
    namespace: str = "swebench",
    tag: str = "latest",
) -> str:
    """Docker ref for one Lite instance (matches current swebench namespace layout)."""
    iid = (instance_id or "").strip()
    if not iid:
        raise ValueError("empty instance_id")
    # swebench harness: {namespace}/sweb.eval.x86_64.{instance_id}:{tag}
    return f"{namespace}/sweb.eval.x86_64.{iid}:{tag}"


def tier_instance_ids(tier: str, *, n_instances: int | None = None) -> list[str]:
    tier = (tier or "n5").strip()
    if tier not in CODING_TIERS:
        raise ValueError(f"unknown coding tier: {tier}")
    order_path = _SLICE_DIR / "instance_order.txt"
    order = [
        line.strip()
        for line in order_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if tier == "custom":
        if n_instances is None or n_instances < 1:
            raise ValueError("custom tier requires n_instances >= 1")
        n = min(int(n_instances), len(order))
    elif tier == "full300":
        n = len(order)
    else:
        n = int(CODING_TIERS[tier] or 0)
    return order[:n]


def image_refs_for_tier(
    tier: str,
    *,
    n_instances: int | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[str]:
    h = harness_cfg(cfg)
    return [
        instance_image_ref(iid, namespace=h["namespace"], tag=h["image_tag"])
        for iid in tier_instance_ids(tier, n_instances=n_instances)
    ]


def docker_image_present(ref: str, *, timeout: float = 8.0) -> bool:
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", ref],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def missing_images(refs: list[str]) -> list[str]:
    return [r for r in refs if not docker_image_present(r)]


def local_image_status(
    tier: str | None = None,
    *,
    n_instances: int | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    h = harness_cfg(cfg)
    use_tier = (tier or h["board_tier"]).strip() or "n5"
    refs = image_refs_for_tier(use_tier, n_instances=n_instances, cfg=cfg)
    missing = missing_images(refs)
    present = [r for r in refs if r not in missing]
    approx = int(h["approx_mib_per_image"]) * len(refs)
    return {
        "tier": use_tier,
        "n": len(refs),
        "refs": refs,
        "present": present,
        "missing": missing,
        "ready": not missing,
        "approx_mib_total": approx,
        "cache_level": h["cache_level"],
        "require_local_images": h["require_local_images"],
    }


_DOCKER_PULL_PROGRESS: bool | None = None


def _docker_pull_cmd(ref: str) -> list[str]:
    """Prefer ``--progress=plain`` when the host docker CLI supports it."""
    global _DOCKER_PULL_PROGRESS
    if _DOCKER_PULL_PROGRESS is None:
        try:
            help_proc = subprocess.run(
                ["docker", "pull", "--help"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            blob = (help_proc.stdout or "") + (help_proc.stderr or "")
            _DOCKER_PULL_PROGRESS = "--progress" in blob
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _DOCKER_PULL_PROGRESS = False
    if _DOCKER_PULL_PROGRESS:
        return ["docker", "pull", "--progress=plain", ref]
    return ["docker", "pull", ref]


def _docker_pull(ref: str, *, progress_base: dict[str, Any]) -> int:
    """Run ``docker pull`` with heartbeat so 看板 progress stays fresh (~1GiB/image)."""
    env = os.environ.copy()
    env.setdefault("DOCKER_CLI_HINTS", "false")
    cmd = _docker_pull_cmd(ref)
    try:
        proc = subprocess.Popen(cmd, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError("docker CLI missing on host") from exc
    while True:
        try:
            return int(proc.wait(timeout=15))
        except subprocess.TimeoutExpired:
            write_progress({**progress_base, "last_status": "pulling", "heartbeat": True})


def pull_images(
    refs: list[str],
    *,
    force: bool = False,
    tier: str | None = None,
) -> dict[str, Any]:
    """Pull missing (or all if force) images. Host docker required.

    Emits line logs + ``swe_eval_images_progress.json`` for 部署看板.
    """
    total = len(refs)
    results: list[dict[str, Any]] = []
    done = 0
    cached_n = 0
    pulled_n = 0
    write_progress(
        {
            "status": "building",
            "phase": "pull",
            "tier": tier,
            "images_total": total,
            "images_done": 0,
            "images_cached": 0,
            "images_pulled": 0,
            "current_ref": None,
            "last_status": "starting",
        }
    )
    try:
        for idx, ref in enumerate(refs, start=1):
            short = ref.rsplit("/", 1)[-1]
            base = {
                "status": "building",
                "phase": "pull",
                "tier": tier,
                "images_total": total,
                "images_done": idx - 1,
                "images_cached": cached_n,
                "images_pulled": pulled_n,
                "current_ref": ref,
                "current_short": short,
            }
            if not force and docker_image_present(ref):
                results.append({"ref": ref, "status": "cached"})
                done = idx
                cached_n += 1
                print(f"[swe-images] [{idx}/{total}] cached {ref}", flush=True)
                write_progress({**base, "images_done": done, "images_cached": cached_n, "last_status": "cached"})
                continue
            print(f"[swe-images] [{idx}/{total}] pull {ref}", flush=True)
            write_progress({**base, "last_status": "pulling"})
            try:
                rc = _docker_pull(ref, progress_base={**base, "last_status": "pulling"})
            except RuntimeError as exc:
                write_progress(
                    {
                        **base,
                        "status": "error",
                        "phase": "error",
                        "images_done": done,
                        "last_status": "error",
                        "error": str(exc)[:400],
                    }
                )
                raise
            if rc != 0:
                results.append({"ref": ref, "status": "error", "exit_code": rc})
                write_progress(
                    {
                        **base,
                        "status": "error",
                        "phase": "error",
                        "images_done": done,
                        "last_status": "error",
                        "error": f"docker pull exit {rc}",
                    }
                )
                raise RuntimeError(f"docker pull failed ({rc}): {ref}")
            results.append({"ref": ref, "status": "pulled"})
            done = idx
            pulled_n += 1
            write_progress(
                {
                    **base,
                    "images_done": done,
                    "images_pulled": pulled_n,
                    "last_status": "pulled",
                }
            )
        write_progress(
            {
                "status": "ready",
                "phase": "finished",
                "tier": tier,
                "images_total": total,
                "images_done": total,
                "images_cached": cached_n,
                "images_pulled": pulled_n,
                "current_ref": None,
                "last_status": "finished",
            }
        )
    except Exception as exc:
        prev = read_progress(max_age_s=0) or {}
        if prev.get("status") != "error":
            write_progress(
                {
                    **{k: prev.get(k) for k in ("tier", "images_total", "images_done", "current_ref")},
                    "status": "error",
                    "phase": "error",
                    "error": str(exc)[:400],
                    "last_status": "error",
                }
            )
        raise
    return {"n": total, "results": results}


def pull_tier_images(
    tier: str | None = None,
    *,
    n_instances: int | None = None,
    force: bool = False,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    h = harness_cfg(cfg)
    use_tier = (tier or h["board_tier"]).strip() or "n5"
    refs = image_refs_for_tier(use_tier, n_instances=n_instances, cfg=cfg)
    out = pull_images(refs, force=force, tier=use_tier)
    out["tier"] = use_tier
    return out
