"""Official-bench runs: filesystem under /repo + optional ops_eval_runs rows."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

def _candidate_report_roots() -> list[Path]:
    """Resolve report dirs without assuming a fixed parents[N] depth (breaks in /app image)."""
    roots: list[Path] = [
        Path("/data/ops-official/reports"),
        Path("/repo/eval/reports/official"),
    ]
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "eval" / "reports" / "official"
        if candidate not in roots:
            roots.append(candidate)
        # Stop once we pass filesystem root-ish markers
        if parent.name in {"app", "AgentPlatform"} or (parent / ".git").exists():
            # still allow one more level above package root
            continue
    return roots


def reports_root() -> Path | None:
    candidates = _candidate_report_roots()
    for p in candidates:
        if p.is_dir():
            return p
    # Prefer writable data volume for Ops-triggered runs
    data = Path("/data/ops-official/reports")
    if Path("/data").is_dir():
        return data
    if Path("/repo").is_dir():
        return Path("/repo/eval/reports/official")
    return candidates[-1] if candidates else data


def _load_manifest(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", run_dir.name)
    data["report_dir"] = str(run_dir)
    html = run_dir / "report.html"
    if html.is_file():
        data["report_html_available"] = True
    return data


def list_fs_runs(*, limit: int = 50) -> list[dict[str, Any]]:
    root = reports_root()
    if root is None:
        return []
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for child in sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        manifest = _load_manifest(child)
        if not manifest:
            continue
        rows.append(
            {
                "id": manifest.get("id"),
                "status": manifest.get("status"),
                "suite": "official",
                "official_suite": manifest.get("official_suite"),
                "title": manifest.get("title"),
                "mode": "official",
                "created_at": manifest.get("created_at"),
                "finished_at": manifest.get("finished_at"),
                "error": manifest.get("error"),
                "summary": manifest.get("summary"),
                "model_meta": manifest.get("model_meta"),
                "source": "filesystem",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def clear_fs_runs() -> int:
    """Remove filesystem official run dirs under reports/runs (keeps data cache)."""
    root = reports_root()
    if root is None:
        return 0
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return 0
    removed = 0
    for child in list(runs_dir.iterdir()):
        if not child.is_dir():
            continue
        try:
            shutil.rmtree(child)
            removed += 1
        except OSError:
            continue
    for name in (
        "latest_run.json",
        "latest_retrieval.json",
        "latest_context.json",
        "latest_coding.json",
    ):
        path = root / name
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
    return removed


def get_fs_run(run_id: str) -> dict[str, Any] | None:
    root = reports_root()
    if root is None:
        return None
    return _load_manifest(root / "runs" / run_id)


def read_report_html(run_id: str) -> str | None:
    root = reports_root()
    if root is None:
        return None
    # 1) Ops aggregate written under the Ops live run id
    path = root / "runs" / run_id / "report.html"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    # 2) Direct bench session id (host make / imported FS run)
    # already covered by same path shape
    return None


def resolve_report_html(
    run_id: str,
    *,
    child_ids: list[str] | None = None,
    report_paths: list[str] | None = None,
) -> str | None:
    """Find HTML for an Ops or bench run id, falling back to linked children."""
    direct = read_report_html(run_id)
    if direct:
        return direct
    root = reports_root()
    if root is None:
        return None
    for cid in child_ids or []:
        html = read_report_html(str(cid))
        if html:
            return html
    for p in report_paths or []:
        path = Path(p)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    # Last resort: latest_run.json pointer
    latest = root / "latest_run.json"
    if latest.is_file():
        try:
            meta = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        for key in ("report_html", "dir"):
            cand = meta.get(key)
            if not cand:
                continue
            path = Path(cand)
            if key == "dir":
                path = path / "report.html"
            if path.is_file():
                return path.read_text(encoding="utf-8")
    return None


def write_ops_aggregate_report(
    ops_run_id: str,
    *,
    title: str,
    status: str,
    children: list[dict[str, Any]],
) -> Path | None:
    """Write /runs/<ops_id>/report.html aggregating finished child bench reports."""
    root = reports_root()
    if root is None:
        return None
    out_dir = root / "runs" / ops_run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    if not children:
        # Still write a stub so the button can explain state
        stub = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;color:#1c1916}}
.muted{{color:#6b635a}}</style></head>
<body>
<h1>{html.escape(title)}</h1>
<p>状态：{html.escape(status)}</p>
<p class="muted">还没有可展示的官方 HTML。每个套件（检索/上下文/编码）在
<strong>完整跑完并 finish</strong> 后才会生成 report.html；取消或中途停止不会有报告。</p>
</body></html>"""
        out = out_dir / "report.html"
        out.write_text(stub, encoding="utf-8")
        return out

    sections: list[str] = []
    for child in children:
        label = child.get("case_id") or child.get("target") or child.get("id") or "suite"
        html_body: str | None = None
        report_path = child.get("report_html")
        bench_id = child.get("bench_run_id") or child.get("id")
        if report_path and Path(str(report_path)).is_file():
            html_body = Path(str(report_path)).read_text(encoding="utf-8")
        elif bench_id:
            html_body = read_report_html(str(bench_id))
        if not html_body:
            sections.append(
                f"<section><h2>{html.escape(str(label))}</h2>"
                f"<p class='muted'>尚无 HTML（该套件未 finish 或被取消）。</p></section>"
            )
            continue
        # Extract body inner if full document
        lower = html_body.lower()
        if "<body" in lower:
            start = lower.find("<body")
            start = lower.find(">", start) + 1
            end = lower.rfind("</body>")
            inner = html_body[start:end] if end > start else html_body
        else:
            inner = html_body
        sections.append(
            f"<section class='child'><h2>{html.escape(str(label))}</h2>{inner}</section>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#f6f1e8;color:#1c1916}}
main{{max-width:960px;margin:0 auto;padding:1.5rem}}
.child{{margin:1.5rem 0;padding:1rem;background:#fffdf8;border:1px solid #d9d0c3;border-radius:8px}}
.muted{{color:#6b635a}}
</style></head>
<body><main>
<h1>{html.escape(title)}</h1>
<p class="muted">Ops 聚合报告 · 状态 {html.escape(status)} · 含子套件 {len(children)}</p>
{''.join(sections)}
</main></body></html>"""
    out = out_dir / "report.html"
    out.write_text(doc, encoding="utf-8")
    (out_dir / "aggregate.json").write_text(
        json.dumps({"id": ops_run_id, "children": children}, indent=2),
        encoding="utf-8",
    )
    return out


async def import_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Persist into ops_eval_runs so History / Run report can open it."""
    from app.services.ops import store as eval_store

    run_id = str(manifest.get("id") or "").strip()
    if not run_id:
        raise ValueError("missing_id")
    model_meta = dict(manifest.get("model_meta") or {})
    model_meta["suite"] = "official"
    model_meta.setdefault("official_suite", manifest.get("official_suite"))
    model_meta.setdefault("title", manifest.get("title"))
    payload = {
        "id": run_id,
        "status": manifest.get("status") or "completed",
        "mode": "official",
        "restart_runtime": False,
        "created_at": manifest.get("created_at"),
        "finished_at": manifest.get("finished_at"),
        "error": manifest.get("error"),
        "model_meta": model_meta,
        "summary": manifest.get("summary") or {},
        "cases": manifest.get("cases") or [],
        "logs": manifest.get("logs") or [],
    }
    await eval_store.upsert_run(payload)
    stored = await eval_store.load_run(run_id)
    return stored or payload
