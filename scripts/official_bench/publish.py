from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .paths import reports_dir


def _secret() -> str:
    return (
        os.environ.get("OPS_TEST_SECRET")
        or os.environ.get("BENCH_OPS_SECRET")
        or ""
    ).strip()


def _base() -> str:
    return (
        os.environ.get("BENCH_API_BASE")
        or os.environ.get("OPS_API_BASE")
        or "http://localhost"
    ).rstrip("/")


def publish_manifest(manifest: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """POST run into Ops so history/report UI can show process + results."""
    enabled = os.environ.get("BENCH_PUBLISH", "1").strip() not in {"0", "false", "no"}
    if not enabled and not force:
        return {"published": False, "reason": "BENCH_PUBLISH disabled"}

    secret = _secret()
    if not secret:
        # Still write a publish payload for manual import
        out = reports_dir() / "runs" / manifest["id"] / "ops_import.json"
        out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "published": False,
            "reason": "OPS_TEST_SECRET missing — wrote ops_import.json for later import",
            "ops_import": str(out),
        }

    url = f"{_base()}/api/v1/ops/official/runs/import"
    body = json.dumps(manifest).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        print(f"[publish] Ops recorded run {manifest.get('id')} → {url}")
        return {"published": True, "response": payload}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"[publish] HTTP {exc.code}: {detail[:400]}")
        return {"published": False, "reason": f"HTTP {exc.code}", "detail": detail[:800]}
    except Exception as exc:  # noqa: BLE001
        print(f"[publish] failed: {exc}")
        return {"published": False, "reason": str(exc)}


def publish_run_dir(run_dir: Path, *, force: bool = False) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return publish_manifest(manifest, force=force)
