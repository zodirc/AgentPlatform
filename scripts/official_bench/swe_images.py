"""SWE-bench Lite official eval image refs (sweb.eval) — local cache helpers.

Images are ~1GiB compressed each and must not live in git. Pre-pull via
部署看板 or ``make official-bench-coding-pull-images``. Config:
``eval/official/suites.small.yaml`` → ``suites.coding.harness``.

After pull, each image is **env-smoked** (python / pytest /testbed) so 看板
「就绪」means present **and** suitable for resolve + solve-side reproduce.
Progress: ``reports/release/swe_eval_images_progress.json``; durable smoke
results: ``swe_eval_images_smoke.json`` (override dir with ``RELEASE_STATUS_DIR``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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


def _status_dir() -> Path:
    return Path(
        os.environ.get("RELEASE_STATUS_DIR")
        or (_ROOT / "reports" / "release")
    )


def progress_path() -> Path:
    return _status_dir() / "swe_eval_images_progress.json"


def smoke_results_path() -> Path:
    """Durable per-image env smoke results (board readiness + solve gate)."""
    return _status_dir() / "swe_eval_images_smoke.json"


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


def write_smoke_results(payload: dict[str, Any]) -> None:
    path = smoke_results_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        **payload,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    # Mirror so runtime (ops-eval) can gate solve-side run_tests without
    # depending solely on the release-console status dir mount.
    mirrors: list[Path] = []
    bench_reports = (os.environ.get("BENCH_REPORTS_DIR") or "").strip()
    if bench_reports:
        mirrors.append(Path(bench_reports) / "swe_eval_images_smoke.json")
    mirrors.append(Path("/data/ops-official/reports") / "swe_eval_images_smoke.json")
    mirrors.append(_ROOT / "eval" / "reports" / "official" / "swe_eval_images_smoke.json")
    seen = {str(path.resolve()) if path.exists() else str(path)}
    for mirror in mirrors:
        key = str(mirror)
        if key in seen:
            continue
        seen.add(key)
        try:
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mtmp = mirror.with_suffix(".tmp")
            mtmp.write_text(text, encoding="utf-8")
            mtmp.replace(mirror)
        except OSError:
            continue


def read_smoke_results(*, max_age_s: float = 0.0) -> dict[str, Any] | None:
    path = smoke_results_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if max_age_s > 0:
        raw = str(data.get("updated_at") or "").strip()
        if raw:
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
    arch: str = "x86_64",
) -> str:
    """Docker Hub ref for one Lite instance (matches swebench harness naming).

    swebench replaces ``__`` with ``_1776_`` for Docker Hub safety, e.g.::

        astropy__astropy-12907
          → swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest
    """
    iid = (instance_id or "").strip()
    if not iid:
        raise ValueError("empty instance_id")
    # Same transform as swebench.harness.test_spec.TestSpec.instance_image_key.
    slug = iid.lower().replace("__", "_1776_")
    return f"{namespace}/sweb.eval.{arch}.{slug}:{tag}"


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


DEFAULT_SMOKE_SHELL = (
    "set -euo pipefail; "
    "python -V; "
    "(python -m pytest --version || pytest --version); "
    "test -d /testbed"
)


def smoke_timeout_s() -> float:
    raw = os.environ.get("SWE_EVAL_SMOKE_TIMEOUT_S", "").strip()
    if raw:
        try:
            return max(10.0, float(raw))
        except ValueError:
            pass
    return 120.0


def smoke_shell_cmd() -> str:
    return (os.environ.get("SWE_EVAL_SMOKE_CMD") or "").strip() or DEFAULT_SMOKE_SHELL


def smoke_image(
    ref: str,
    *,
    timeout_s: float | None = None,
    shell_cmd: str | None = None,
) -> dict[str, Any]:
    """Run a lightweight env probe inside one local sweb.eval image.

    Checks python, pytest, and ``/testbed`` without network or worktree mounts.
    """
    limit = float(timeout_s if timeout_s is not None else smoke_timeout_s())
    cmd = (shell_cmd if shell_cmd is not None else smoke_shell_cmd()).strip()
    if not cmd:
        cmd = DEFAULT_SMOKE_SHELL
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-w",
        "/testbed",
        ref,
        "bash",
        "-lc",
        cmd,
    ]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=limit,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ref": ref,
            "ok": False,
            "error": "docker_cli_missing",
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
    except subprocess.TimeoutExpired:
        return {
            "ref": ref,
            "ok": False,
            "error": f"smoke_timeout_{int(limit)}s",
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
    out = (proc.stdout or "")[-800:]
    err = (proc.stderr or "")[-800:]
    ok = proc.returncode == 0
    return {
        "ref": ref,
        "ok": ok,
        "exit_code": int(proc.returncode),
        "stdout_tail": out,
        "stderr_tail": err,
        "error": None if ok else f"smoke_exit_{proc.returncode}",
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def read_smoke_ok_for_refs(refs: list[str]) -> dict[str, Any]:
    """Merge durable smoke file with requested refs → ok / failed / missing_smoke."""
    stored = read_smoke_results(max_age_s=0) or {}
    by_ref = stored.get("by_ref") if isinstance(stored.get("by_ref"), dict) else {}
    ok_refs: list[str] = []
    failed: list[dict[str, Any]] = []
    missing_smoke: list[str] = []
    for ref in refs:
        row = by_ref.get(ref)
        if not isinstance(row, dict):
            missing_smoke.append(ref)
            continue
        if row.get("ok") is True:
            ok_refs.append(ref)
        else:
            failed.append(
                {
                    "ref": ref,
                    "error": row.get("error") or "smoke_failed",
                    "exit_code": row.get("exit_code"),
                }
            )
    return {
        "ok_refs": ok_refs,
        "failed": failed,
        "missing_smoke": missing_smoke,
        "all_ok": not failed and not missing_smoke and bool(refs),
        "smoke_updated_at": stored.get("updated_at"),
        "tier": stored.get("tier"),
    }


def smoke_images(
    refs: list[str],
    *,
    tier: str | None = None,
    progress_base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Smoke every ref; persist results; update board progress while running."""
    total = len(refs)
    base = dict(progress_base or {})
    base.update(
        {
            "status": "building",
            "phase": "smoke",
            "tier": tier or base.get("tier"),
            "images_total": total,
            "smoke_total": total,
            "smoke_done": 0,
            "last_status": "smoking",
        }
    )
    write_progress(base)
    by_ref: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for idx, ref in enumerate(refs, start=1):
        short = ref.rsplit("/", 1)[-1]
        print(f"[swe-images] [{idx}/{total}] smoke {ref}", flush=True)
        write_progress(
            {
                **base,
                "images_done": idx - 1,
                "smoke_done": idx - 1,
                "current_ref": ref,
                "current_short": short,
                "last_status": "smoking",
            }
        )
        row = smoke_image(ref)
        by_ref[ref] = row
        results.append(row)
        if not row.get("ok"):
            failed.append(row)
            print(
                f"[swe-images] smoke FAIL {ref}: {row.get('error')} "
                f"exit={row.get('exit_code')}",
                flush=True,
            )
        else:
            print(
                f"[swe-images] smoke ok {ref} ({row.get('elapsed_s')}s)",
                flush=True,
            )
        write_progress(
            {
                **base,
                "images_done": idx,
                "smoke_done": idx,
                "current_ref": ref,
                "current_short": short,
                "last_status": "smoked" if row.get("ok") else "smoke_error",
            }
        )

    payload = {
        "tier": tier,
        "n": total,
        "ok_n": total - len(failed),
        "failed_n": len(failed),
        "all_ok": not failed and total > 0,
        "by_ref": by_ref,
        "failed": [
            {"ref": r["ref"], "error": r.get("error"), "exit_code": r.get("exit_code")}
            for r in failed
        ],
    }
    write_smoke_results(payload)
    return payload


def local_image_status(
    tier: str | None = None,
    *,
    n_instances: int | None = None,
    cfg: dict[str, Any] | None = None,
    require_smoke: bool | None = None,
) -> dict[str, Any]:
    h = harness_cfg(cfg)
    use_tier = (tier or h["board_tier"]).strip() or "n5"
    refs = image_refs_for_tier(use_tier, n_instances=n_instances, cfg=cfg)
    missing = missing_images(refs)
    present = [r for r in refs if r not in missing]
    approx = int(h["approx_mib_per_image"]) * len(refs)
    want_smoke = (
        bool(require_smoke)
        if require_smoke is not None
        else _env_bool("SWE_EVAL_REQUIRE_SMOKE", default=True)
    )
    smoke = (
        read_smoke_ok_for_refs(present)
        if present
        else {
            "ok_refs": [],
            "failed": [],
            "missing_smoke": [],
            "all_ok": False,
            "smoke_updated_at": None,
            "tier": None,
        }
    )
    images_ready = not missing
    if not want_smoke:
        smoke_ready = True
    elif not images_ready or not present:
        smoke_ready = False
    else:
        smoke_ready = (
            bool(smoke.get("all_ok"))
            and not smoke.get("failed")
            and not smoke.get("missing_smoke")
        )
    return {
        "tier": use_tier,
        "n": len(refs),
        "refs": refs,
        "present": present,
        "missing": missing,
        "ready": images_ready and smoke_ready,
        "images_ready": images_ready,
        "smoke_ready": smoke_ready,
        "require_smoke": want_smoke,
        "smoke_ok_n": len(smoke.get("ok_refs") or []),
        "smoke_failed": smoke.get("failed") or [],
        "smoke_missing": smoke.get("missing_smoke") or [],
        "smoke_updated_at": smoke.get("smoke_updated_at"),
        "approx_mib_total": approx,
        "cache_level": h["cache_level"],
        "require_local_images": h["require_local_images"],
    }


_DOCKER_PULL_PROGRESS: bool | None = None

_LAYER_LINE_RE = re.compile(
    r"^([0-9a-f]{8,64}):\s*(.+?)\s*$",
    re.IGNORECASE,
)
_SIZE_PAIR_RE = re.compile(
    r"([\d.]+)\s*([KMGT]?i?B)\s*/\s*([\d.]+)\s*([KMGT]?i?B)",
    re.IGNORECASE,
)
_SIZE_UNIT = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def _parse_size_token(num: str, unit: str) -> int | None:
    try:
        n = float(num)
    except ValueError:
        return None
    u = (unit or "B").upper()
    # docker pull progress labels MB/GB but uses binary multiples.
    if u in {"KB", "MB", "GB", "TB"}:
        u = {"KB": "KIB", "MB": "MIB", "GB": "GIB", "TB": "TIB"}[u]
    mul = _SIZE_UNIT.get(u)
    if mul is None:
        return None
    return int(n * mul)


def _fmt_bytes(n: int | None) -> str:
    if n is None or n < 0:
        return "?"
    x = float(n)
    for unit, div in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if x >= div:
            return f"{x / div:.1f}{unit}"
    return f"{int(x)}B"


def _fmt_speed(bps: float | None) -> str | None:
    """Human download rate, e.g. ``3.1 MiB/s`` (binary units, like docker pull)."""
    if bps is None or bps < 0:
        return None
    if bps < 512:
        return f"{int(bps)} B/s"
    x = float(bps)
    for unit, div in (("GiB/s", 1024**3), ("MiB/s", 1024**2), ("KiB/s", 1024)):
        if x >= div:
            return f"{x / div:.1f} {unit}"
    return f"{int(x)} B/s"


class DockerPullProgress:
    """Parse classic ``docker pull`` layer lines into board-facing stats."""

    def __init__(self, *, clock: Any | None = None) -> None:
        self.layers: dict[str, str] = {}
        self.dl_done: dict[str, int] = {}
        self.dl_total: dict[str, int] = {}
        self.ex_done: dict[str, int] = {}
        self.ex_total: dict[str, int] = {}
        self.last_line = ""
        self._clock = clock or time.time
        # Sliding window of (t, cumulative download bytes) for rate.
        self._speed_samples: list[tuple[float, int]] = []
        self.speed_bps: float | None = None

    def feed(self, raw: str) -> bool:
        """Ingest one logical line (may contain ``\\r`` chunks). Return True if state changed."""
        changed = False
        for chunk in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = chunk.strip()
            if not line:
                continue
            self.last_line = line[:160]
            if self._feed_one(line):
                changed = True
        if changed:
            self._note_speed_sample()
        return changed

    def _feed_one(self, line: str) -> bool:
        m = _LAYER_LINE_RE.match(line)
        if not m:
            return False
        lid = m.group(1).lower()
        rest = m.group(2).strip()
        status = rest.split("[", 1)[0].strip().rstrip(":")
        status_l = status.lower()
        prev = self.layers.get(lid)
        self.layers[lid] = status_l
        pair = _SIZE_PAIR_RE.search(rest)
        if pair:
            a = _parse_size_token(pair.group(1), pair.group(2))
            b = _parse_size_token(pair.group(3), pair.group(4))
            if a is not None and b is not None:
                if "download" in status_l:
                    self.dl_done[lid] = a
                    self.dl_total[lid] = b
                elif "extract" in status_l:
                    self.ex_done[lid] = a
                    self.ex_total[lid] = b
        if "download complete" in status_l or "already exists" in status_l:
            if lid in self.dl_total:
                self.dl_done[lid] = self.dl_total[lid]
        if "pull complete" in status_l:
            if lid in self.dl_total:
                self.dl_done[lid] = self.dl_total[lid]
            if lid in self.ex_total:
                self.ex_done[lid] = self.ex_total[lid]
        return prev != status_l or pair is not None

    def _note_speed_sample(self) -> None:
        now = float(self._clock())
        total = int(sum(self.dl_done.values())) if self.dl_done else 0
        samples = self._speed_samples
        if samples and samples[-1][1] == total and (now - samples[-1][0]) < 0.2:
            return
        samples.append((now, total))
        cutoff = now - 5.0
        self._speed_samples = [(t, b) for t, b in samples if t >= cutoff]
        self._recompute_speed()

    def _recompute_speed(self) -> None:
        samples = self._speed_samples
        if len(samples) < 2:
            self.speed_bps = None
            return
        t0, b0 = samples[0]
        t1, b1 = samples[-1]
        dt = t1 - t0
        if dt < 0.35:
            self.speed_bps = None
            return
        # Prefer recent 2s window when we have enough points.
        recent = [(t, b) for t, b in samples if t >= t1 - 2.0]
        if len(recent) >= 2:
            t0, b0 = recent[0]
            t1, b1 = recent[-1]
            dt = t1 - t0
            if dt < 0.2:
                self.speed_bps = None
                return
        self.speed_bps = max(0.0, (b1 - b0) / dt)

    def snapshot(self) -> dict[str, Any]:
        # Refresh rate even on heartbeat writes with no new docker lines.
        self._note_speed_sample()
        layers = list(self.layers)
        n = len(layers)
        done = sum(
            1
            for lid, st in self.layers.items()
            if "pull complete" in st or "already exists" in st
        )
        downloaded = sum(
            1
            for lid, st in self.layers.items()
            if "download complete" in st
            or "pull complete" in st
            or "already exists" in st
            or "extract" in st
        )
        waiting = sum(1 for st in self.layers.values() if "wait" in st)
        downloading = sum(1 for st in self.layers.values() if "download" in st and "complete" not in st)
        extracting = sum(1 for st in self.layers.values() if "extract" in st and "complete" not in st)

        bytes_done = sum(self.dl_done.values()) if self.dl_done else None
        bytes_total = sum(self.dl_total.values()) if self.dl_total else None
        # Prefer byte ratio when we know totals for all known download layers.
        layer_pct: float | None = None
        if bytes_total and bytes_total > 0 and bytes_done is not None:
            layer_pct = round(100.0 * bytes_done / bytes_total, 1)
        elif n > 0:
            layer_pct = round(100.0 * done / n, 1)

        speed_bps = self.speed_bps
        # Hide noisy near-zero while still only Waiting / no byte counters yet.
        if not self.dl_done and not downloading:
            speed_bps = None
        speed_label = _fmt_speed(speed_bps)

        detail_bits: list[str] = []
        if speed_label and (downloading or (bytes_done or 0) > 0):
            detail_bits.append(speed_label)
        if n:
            detail_bits.append(f"层 {done}/{n}")
        if bytes_done is not None and bytes_total:
            detail_bits.append(f"{_fmt_bytes(bytes_done)}/{_fmt_bytes(bytes_total)}")
        elif downloading:
            detail_bits.append(f"下载中×{downloading}")
        elif extracting:
            detail_bits.append(f"解压中×{extracting}")
        elif waiting:
            detail_bits.append(f"排队×{waiting}")

        return {
            "layers_total": n,
            "layers_done": done,
            "layers_downloaded": downloaded,
            "layers_waiting": waiting,
            "layers_downloading": downloading,
            "layers_extracting": extracting,
            "bytes_done": bytes_done,
            "bytes_total": bytes_total,
            "layer_pct": layer_pct,
            "speed_bps": round(speed_bps, 1) if speed_bps is not None else None,
            "speed_label": speed_label,
            "layer_detail": " · ".join(detail_bits) if detail_bits else None,
            "last_pull_line": self.last_line or None,
        }


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
    """Run ``docker pull``, stream logs, and publish layer progress for 看板."""
    env = os.environ.copy()
    env.setdefault("DOCKER_CLI_HINTS", "false")
    # Force non-TTY progress lines so we can parse Downloading MB/MB.
    env["DOCKER_PROGRESS"] = env.get("DOCKER_PROGRESS") or "plain"
    cmd = _docker_pull_cmd(ref)
    tracker = DockerPullProgress()
    last_write = 0.0
    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("docker CLI missing on host") from exc

    assert proc.stdout is not None
    buf = ""
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        # Keep board/make logs readable.
        sys.stdout.write(text)
        sys.stdout.flush()
        buf += text
        # Emit on newline or carriage-return progress ticks.
        while True:
            nl = buf.find("\n")
            cr = buf.find("\r")
            cuts = [i for i in (nl, cr) if i >= 0]
            if not cuts:
                break
            i = min(cuts)
            line, buf = buf[: i + 1], buf[i + 1 :]
            changed = tracker.feed(line)
            now = time.time()
            if changed and (now - last_write) >= 0.4:
                snap = tracker.snapshot()
                write_progress({**progress_base, "last_status": "pulling", **snap})
                last_write = now
    if buf.strip():
        tracker.feed(buf)
        print(buf, end="" if buf.endswith("\n") else "\n", flush=True)
    rc = int(proc.wait())
    snap = tracker.snapshot()
    write_progress(
        {
            **progress_base,
            "last_status": "pulling" if rc == 0 else "error",
            **snap,
            "heartbeat": True,
        }
    )
    return rc


def pull_images(
    refs: list[str],
    *,
    force: bool = False,
    tier: str | None = None,
    skip_smoke: bool = False,
) -> dict[str, Any]:
    """Pull missing (or all if force) images, then env-smoke each.

    Emits line logs + ``swe_eval_images_progress.json`` for 部署看板.
    Ready status requires smoke unless ``skip_smoke`` / ``SWE_EVAL_SKIP_SMOKE=1``.
    """
    total = len(refs)
    results: list[dict[str, Any]] = []
    done = 0
    cached_n = 0
    pulled_n = 0
    smoke_out: dict[str, Any] | None = None
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

        do_smoke = not skip_smoke and not _env_bool("SWE_EVAL_SKIP_SMOKE", default=False)
        if do_smoke and refs:
            smoke_out = smoke_images(
                refs,
                tier=tier,
                progress_base={
                    "tier": tier,
                    "images_total": total,
                    "images_cached": cached_n,
                    "images_pulled": pulled_n,
                },
            )
            if not smoke_out.get("all_ok"):
                fail = (smoke_out.get("failed") or [{}])[0]
                err = (
                    f"sweb.eval env smoke failed: {fail.get('ref')} "
                    f"({fail.get('error') or 'unknown'})"
                )
                write_progress(
                    {
                        "status": "error",
                        "phase": "smoke_error",
                        "tier": tier,
                        "images_total": total,
                        "images_done": total,
                        "images_cached": cached_n,
                        "images_pulled": pulled_n,
                        "smoke_failed_n": smoke_out.get("failed_n"),
                        "last_status": "smoke_error",
                        "error": err[:400],
                    }
                )
                raise RuntimeError(err)

        write_progress(
            {
                "status": "ready",
                "phase": "finished",
                "tier": tier,
                "images_total": total,
                "images_done": total,
                "images_cached": cached_n,
                "images_pulled": pulled_n,
                "smoke_ok": bool(smoke_out.get("all_ok")) if smoke_out else (not do_smoke),
                "smoke_skipped": not do_smoke,
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
    out: dict[str, Any] = {"n": total, "results": results}
    if smoke_out is not None:
        out["smoke"] = {
            "all_ok": smoke_out.get("all_ok"),
            "ok_n": smoke_out.get("ok_n"),
            "failed_n": smoke_out.get("failed_n"),
            "failed": smoke_out.get("failed"),
        }
    return out


def pull_tier_images(
    tier: str | None = None,
    *,
    n_instances: int | None = None,
    force: bool = False,
    skip_smoke: bool = False,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    h = harness_cfg(cfg)
    use_tier = (tier or h["board_tier"]).strip() or "n5"
    refs = image_refs_for_tier(use_tier, n_instances=n_instances, cfg=cfg)
    out = pull_images(refs, force=force, tier=use_tier, skip_smoke=skip_smoke)
    out["tier"] = use_tier
    return out