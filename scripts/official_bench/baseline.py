"""Committed official-bench baselines under ``eval/official/baseline/``.

Full run artifacts stay gitignored in ``eval/reports/official/``. Long-term
iteration compares against these small protocol-keyed snapshots (same idea as
golden ``eval/baseline.json`` + ``--update-baseline``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_suites
from .paths import reports_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO_ROOT / "eval" / "official" / "baseline"

# Keys kept for primary macro / case metrics (compact, comparable).
_RETRIEVAL_KEYS = (
    "ndcg_at_1",
    "recall_at_1",
    "map_at_1",
    "ndcg_at_10",
    "recall_at_10",
    "map_at_10",
    "ndcg_at_100",
    "recall_at_100",
    "map_at_100",
)
_CONTEXT_KEYS = (
    "agent_em",
    "agent_f1",
    "oracle_f1",
    "oracle_em",
    "retention_vs_oracle",
    "full_em",
    "full_f1",
    "budget_em",
    "budget_f1",
    "retention_vs_full_f1",
    "compact_em",
    "compact_f1",
    "retention_compact_vs_full",
)
_CONTEXT_CASE_KEYS = (
    "agent_f1",
    "agent_em",
    "full_f1",
    "budget_f1",
    "retention",
    "compact_f1",
    "retention_compact_vs_full",
    "n",
)


def protocol_version(cfg: dict[str, Any] | None = None) -> str:
    data = cfg or load_suites()
    return str(data.get("protocol_version") or "official-small")


def _manifest_protocol(manifest: dict[str, Any] | None) -> str | None:
    if not isinstance(manifest, dict):
        return None
    meta = manifest.get("model_meta") if isinstance(manifest.get("model_meta"), dict) else {}
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    for blob in (meta, result, manifest):
        pv = blob.get("protocol_version")
        if isinstance(pv, str) and pv.strip():
            return pv.strip()
    return None


def _manifest_eval_path(manifest: dict[str, Any] | None) -> str | None:
    if not isinstance(manifest, dict):
        return None
    meta = manifest.get("model_meta") if isinstance(manifest.get("model_meta"), dict) else {}
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    for blob in (meta, result, manifest):
        ep = blob.get("eval_path")
        if isinstance(ep, str) and ep.strip():
            return ep.strip().lower()
    return None


def protocol_from_latest() -> str | None:
    """Prefer protocol stamped on latest_* (L1 → m2) over suites.small.yaml (L0 m1)."""
    for name in ("latest_retrieval.json", "latest_context.json", "latest_coding.json"):
        pv = _manifest_protocol(_read_latest(name))
        if pv:
            return pv
    return None


def baseline_path(protocol: str | None = None) -> Path:
    pv = protocol or protocol_from_latest() or protocol_version()
    return BASELINE_DIR / f"{pv}.json"


def load_baseline(protocol: str | None = None) -> dict[str, Any] | None:
    path = baseline_path(protocol)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def suite_metrics(baseline: dict[str, Any] | None, suite: str) -> dict[str, float] | None:
    """Primary metrics for regress (retrieval = hybrid macro)."""
    if not baseline:
        return None
    suites = baseline.get("suites")
    if not isinstance(suites, dict):
        return None
    block = suites.get(suite)
    if not isinstance(block, dict):
        return None
    metrics = block.get("metrics")
    if not isinstance(metrics, dict):
        return None
    out = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
    return out or None


def infer_sample_tier(
    *,
    suite: str,
    limit_queries: int = 0,
    context_limit: int = 0,
    coding_tier: str | None = None,
    harness: bool = False,
    n_queries: float | int | None = None,
) -> str:
    """A-4: ``anchor`` = SCORECARD primary; ``smoke`` = direction only (no effect Δ)."""
    s = (suite or "").strip().lower()
    if s == "retrieval":
        if limit_queries > 0:
            return "smoke"
        if isinstance(n_queries, (int, float)) and 0 < float(n_queries) <= 50:
            return "smoke"
        return "anchor"
    if s == "context":
        return "smoke" if context_limit > 0 else "anchor"
    if s in {"coding", "coding_infer", "coding_eval"}:
        tier = (coding_tier or "").strip().lower()
        if tier in {"n25", "full300"} and harness:
            return "anchor"
        return "smoke"
    return "smoke"


def _manifest_sample_tier(manifest: dict[str, Any], suite: str) -> str:
    meta = manifest.get("model_meta") if isinstance(manifest.get("model_meta"), dict) else {}
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    for blob in (meta, result, manifest):
        st = blob.get("sample_tier")
        if isinstance(st, str) and st.strip():
            return st.strip().lower()
    metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), dict) else {}
    if suite == "retrieval":
        nq = metrics.get("n_queries") or metrics.get("agent.n_queries")
        return infer_sample_tier(
            suite="retrieval",
            n_queries=nq if isinstance(nq, (int, float)) else None,
        )
    if suite == "context":
        lim = meta.get("context_limit") or result.get("context_limit")
        return infer_sample_tier(
            suite="context",
            context_limit=int(lim) if isinstance(lim, (int, float)) else 0,
        )
    return infer_sample_tier(
        suite="coding",
        coding_tier=str(meta.get("coding_tier") or result.get("coding_tier") or ""),
        harness=bool(meta.get("harness") or result.get("harness")),
    )


def _float_metrics(raw: Any, keys: tuple[str, ...]) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k in keys:
        v = raw.get(k)
        if isinstance(v, (int, float)):
            out[k] = float(v)
    return out


def _case_metrics_map(
    cases: Any,
    *,
    keys: tuple[str, ...],
    only_pass: bool = True,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not isinstance(cases, list):
        return out
    for c in cases:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("case_id") or c.get("id") or "").strip()
        if not cid:
            continue
        if only_pass and str(c.get("status") or "").lower() not in {"pass", "passed", "ok"}:
            continue
        m = _float_metrics(c.get("metrics"), keys)
        if m:
            out[cid] = m
    return out


def _eligible_manifest(manifest: dict[str, Any]) -> bool:
    """Skip dry / skip_api / hash-smoke so baselines are effect scores only."""
    status = str(manifest.get("status") or "").lower()
    if status not in {"completed", "pass", "passed", "ok"}:
        return False
    meta = manifest.get("model_meta") if isinstance(manifest.get("model_meta"), dict) else {}
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    if manifest.get("dry_metrics") or result.get("dry_metrics") or meta.get("dry_metrics"):
        return False
    metrics = manifest.get("metrics") or (manifest.get("summary") or {}).get("metrics") or {}
    if isinstance(metrics, dict):
        mode = str(metrics.get("infer_mode") or "").lower()
        if mode in {"skip_api", "empty_patch"}:
            return False
        if metrics.get("hash_smoke") or metrics.get("embedding_backend") == "hash":
            # Allow only when explicitly marked effect-eligible (prod ST runs omit this).
            if metrics.get("effect_eligible") is False:
                return False
    return True


def extract_suite_snapshot(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Build one suite block from a latest_*.json / Ops manifest."""
    if not _eligible_manifest(manifest):
        return None
    suite = str(manifest.get("official_suite") or "").strip().lower()
    run_id = str(manifest.get("id") or "").strip()
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    metrics_raw = manifest.get("metrics") or summary.get("metrics") or {}
    model_meta = manifest.get("model_meta") if isinstance(manifest.get("model_meta"), dict) else {}

    eval_path = _manifest_eval_path(manifest) or "component"
    protocol = _manifest_protocol(manifest)

    if suite == "retrieval":
        # L1 prefers agent.*; L0 prefers hybrid.*; then unprefixed primary.
        prefixes = ("agent.", "hybrid.", "") if eval_path == "agent" else ("hybrid.", "agent.", "")
        primary: dict[str, float] = {}
        if isinstance(metrics_raw, dict):
            for k in _RETRIEVAL_KEYS:
                for prefix in prefixes:
                    key = f"{prefix}{k}" if prefix else k
                    if isinstance(metrics_raw.get(key), (int, float)):
                        primary[k] = float(metrics_raw[key])
                        break
            for extra in ("n_queries", "n_qrels"):
                for prefix in (("agent.", "") if eval_path == "agent" else ("", "agent.")):
                    key = f"{prefix}{extra}" if prefix else extra
                    if isinstance(metrics_raw.get(key), (int, float)):
                        primary[extra] = float(metrics_raw[key])
                        break
        bm25 = {
            k: float(metrics_raw[f"bm25.{k}"])
            for k in _RETRIEVAL_KEYS
            if isinstance(metrics_raw, dict) and isinstance(metrics_raw.get(f"bm25.{k}"), (int, float))
        }
        delta = {
            k.replace("delta_vs_bm25.", ""): float(v)
            for k, v in (metrics_raw or {}).items()
            if isinstance(k, str)
            and k.startswith("delta_vs_bm25.")
            and isinstance(v, (int, float))
        }
        cases = _case_metrics_map(manifest.get("cases"), keys=_RETRIEVAL_KEYS)
        result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
        arm = str(
            model_meta.get("arm")
            or result.get("arm")
            or ("agent" if eval_path == "agent" else "hybrid")
        )
        return {
            "run_id": run_id,
            "finished_at": manifest.get("finished_at"),
            "eval_path": eval_path,
            "protocol_version": protocol,
            "primary_arm": arm if eval_path == "agent" else "hybrid",
            "sample_tier": _manifest_sample_tier(manifest, "retrieval"),
            "metrics": primary,
            "bm25_metrics": bm25,
            "delta_vs_bm25": delta,
            "cases": cases,
        }

    if suite == "context":
        metrics = _float_metrics(metrics_raw, _CONTEXT_KEYS)
        # Case metrics may use "retention" alias for retention vs full.
        cases_out: dict[str, dict[str, float]] = {}
        for cid, m in _case_metrics_map(
            manifest.get("cases"),
            keys=_CONTEXT_CASE_KEYS + ("retention_vs_full_f1", "em", "f1"),
        ).items():
            if "retention" not in m and "retention_vs_full_f1" in m:
                m = {**m, "retention": m["retention_vs_full_f1"]}
            # L1 per-question cases expose em/f1 → keep as-is; also mirror to agent_* .
            if "agent_f1" not in m and isinstance(m.get("f1"), (int, float)):
                m = {**m, "agent_f1": float(m["f1"])}
            if "agent_em" not in m and isinstance(m.get("em"), (int, float)):
                m = {**m, "agent_em": float(m["em"])}
            # L0 compatibility only: map f1 → compact/full when those arms exist.
            if eval_path != "agent":
                if "compact_f1" not in m and isinstance(m.get("f1"), (int, float)):
                    m = {**m, "compact_f1": float(m["f1"]), "full_f1": float(m["f1"])}
            cases_out[cid] = {
                k: v
                for k, v in m.items()
                if k in _CONTEXT_CASE_KEYS or k in {"retention", "em", "f1", "agent_f1", "agent_em"}
            }
        return {
            "run_id": run_id,
            "finished_at": manifest.get("finished_at"),
            "eval_path": eval_path,
            "protocol_version": protocol,
            "model": model_meta.get("model") or (manifest.get("result") or {}).get("model"),
            "dry_metrics": False,
            "arm": model_meta.get("arm") or (manifest.get("result") or {}).get("arm"),
            "sample_tier": _manifest_sample_tier(manifest, "context"),
            "metrics": metrics,
            "cases": cases_out,
        }

    if suite in {"coding", "coding_infer", "coding_eval"}:
        m = metrics_raw if isinstance(metrics_raw, dict) else {}
        metrics = {
            k: (float(v) if isinstance(v, (int, float)) else v)
            for k, v in m.items()
            if k
            in {
                "patch_rate",
                "resolve_rate",
                "n_instances",
                "n_nonempty_patches",
                "exit_code",
            }
            and isinstance(v, (int, float))
        }
        return {
            "run_id": run_id,
            "finished_at": manifest.get("finished_at"),
            "eval_path": eval_path,
            "protocol_version": protocol,
            "coding_tier": m.get("coding_tier") or model_meta.get("coding_tier"),
            "n_instances": m.get("n_instances") or model_meta.get("n_instances"),
            "instance_fingerprint": m.get("instance_fingerprint")
            or model_meta.get("instance_fingerprint"),
            "infer_mode": m.get("infer_mode") or model_meta.get("infer_mode"),
            "harness": bool(
                m.get("resolve_rate") is not None or model_meta.get("harness") is True
            ),
            "sample_tier": _manifest_sample_tier(manifest, "coding"),
            "model": model_meta.get("model") or m.get("model_name_or_path"),
            "metrics": metrics,
            "note": m.get("note"),
        }

    return None


def _read_latest(name: str) -> dict[str, Any] | None:
    path = reports_dir() / name
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def build_baseline_from_latest(
    *,
    suites: tuple[str, ...] = ("retrieval", "context", "coding"),
    protocol: str | None = None,
) -> dict[str, Any]:
    """Assemble baseline document from ``latest_{suite}.json`` pointers.

    A-4: ``sample_tier=anchor`` writes into ``suites`` (SCORECARD 主栏);
    ``smoke`` writes into ``smoke_suites`` (趋势栏，不作效果结论).
    """
    pv = protocol or protocol_from_latest() or protocol_version()
    existing = load_baseline(pv) or {}
    suite_blocks: dict[str, Any] = {}
    smoke_blocks: dict[str, Any] = {}
    if isinstance(existing.get("suites"), dict):
        suite_blocks.update(existing["suites"])
    if isinstance(existing.get("smoke_suites"), dict):
        smoke_blocks.update(existing["smoke_suites"])

    mapping = {
        "retrieval": "latest_retrieval.json",
        "context": "latest_context.json",
        "coding": "latest_coding.json",
    }
    updated: list[str] = []
    skipped: list[str] = []
    eval_paths: set[str] = set()
    for suite in suites:
        fname = mapping.get(suite)
        if not fname:
            skipped.append(f"{suite}:unknown")
            continue
        manifest = _read_latest(fname)
        if not manifest:
            skipped.append(f"{suite}:missing_latest")
            continue
        snap = extract_suite_snapshot(manifest)
        if not snap:
            skipped.append(f"{suite}:not_eligible")
            continue
        ep = snap.get("eval_path")
        if isinstance(ep, str) and ep:
            eval_paths.add(ep)
        tier = str(snap.get("sample_tier") or "anchor").lower()
        if tier == "smoke":
            smoke_blocks[suite] = snap
            updated.append(f"{suite}:smoke")
        else:
            suite_blocks[suite] = snap
            updated.append(f"{suite}:anchor")

    return {
        "protocol_version": pv,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "eval_path": next(iter(eval_paths)) if len(eval_paths) == 1 else (
            "agent" if "agent" in eval_paths else "mixed"
        ),
        "suites": suite_blocks,
        "smoke_suites": smoke_blocks,
        "_meta": {
            "updated_suites": updated,
            "skipped": skipped,
            "source": "latest_*.json under BENCH_REPORTS_DIR",
            "note": "suites=anchor 主栏；smoke_suites=冒烟趋势（不作效果结论）",
        },
    }


def scorecard_path() -> Path:
    return BASELINE_DIR / "SCORECARD.md"


def _fmt(v: Any, *, digits: int = 4) -> str:
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    if isinstance(v, int):
        return str(v)
    if v is None:
        return "—"
    return str(v)


def render_scorecard(doc: dict[str, Any]) -> str:
    """Human-facing markdown for git glance (not a substitute for Ops HTML)."""
    suites = doc.get("suites") if isinstance(doc.get("suites"), dict) else {}
    smoke = doc.get("smoke_suites") if isinstance(doc.get("smoke_suites"), dict) else {}
    eval_path = str(doc.get("eval_path") or "").strip().lower()
    is_l1 = eval_path == "agent"
    lines: list[str] = [
        "# Official live scorecard",
        "",
        f"- **protocol**: `{doc.get('protocol_version')}`",
        f"- **eval_path**: `{eval_path or '—'}`"
        + ("（L1 agent-path 主栏）" if is_l1 else "（L0 组件对照）"),
        f"- **updated_at**: `{doc.get('updated_at')}`",
        "- **含义**: **主栏 = 锚点档**（全量/自由臂/官方裁判）；冒烟档仅作迭代方向盘，**不作效果结论**。",
        "- **明细**: Ops 官方页 / `eval/reports/official/runs/<id>/`（不进 git）",
    ]
    if is_l1:
        lines.append(
            "- **L0 对照**: 旁路组件史见同目录 `official-small-2026-08-m1.json`（不进本表主栏）"
        )
        lines.append(
            "- **过渡**: `m2.json` 为强制臂史；现行协议 `m3` 自由主臂"
        )
    lines.extend(
        [
            "",
            "## 主栏 · 锚点档（唯一效果结论）",
            "",
            "| 套件 | 主指标 | 值 | run_id | 备注 |",
            "|------|--------|----|--------|------|",
        ]
    )

    def _suite_rows(block: dict[str, Any], *, smoke_banner: bool = False) -> list[str]:
        out: list[str] = []
        ret = block.get("retrieval") if isinstance(block.get("retrieval"), dict) else {}
        rm = ret.get("metrics") if isinstance(ret.get("metrics"), dict) else {}
        rd = ret.get("delta_vs_bm25") if isinstance(ret.get("delta_vs_bm25"), dict) else {}
        ret_label = "agent nDCG@10" if is_l1 else "hybrid nDCG@10"
        ret_note = (
            f"tier={_fmt(ret.get('sample_tier'))} · arm={_fmt(ret.get('primary_arm'))} · "
            f"n_queries={_fmt(rm.get('n_queries'), digits=0)} · R@100={_fmt(rm.get('recall_at_100'))}"
            if is_l1
            else f"ΔBM25 nDCG@10={_fmt(rd.get('ndcg_at_10'))} · R@100={_fmt(rm.get('recall_at_100'))}"
        )
        if ret:
            out.append(
                f"| retrieval | {ret_label} | "
                f"{_fmt(rm.get('ndcg_at_10'))} | `{_fmt(ret.get('run_id'))}` | {ret_note} |"
            )

        ctx = block.get("context") if isinstance(block.get("context"), dict) else {}
        cm = ctx.get("metrics") if isinstance(ctx.get("metrics"), dict) else {}
        if ctx:
            if is_l1 and isinstance(cm.get("agent_f1"), (int, float)):
                out.append(
                    "| context | agent F1 / EM | "
                    f"{_fmt(cm.get('agent_f1'))} / {_fmt(cm.get('agent_em'))} | "
                    f"`{_fmt(ctx.get('run_id'))}` | "
                    f"tier={_fmt(ctx.get('sample_tier'))} · arm={_fmt(ctx.get('arm'))} · "
                    f"model=`{_fmt(ctx.get('model'))}` |"
                )
            else:
                out.append(
                    "| context | compact F1 / retention | "
                    f"{_fmt(cm.get('compact_f1'))} / {_fmt(cm.get('retention_compact_vs_full'))} | "
                    f"`{_fmt(ctx.get('run_id'))}` | "
                    f"full={_fmt(cm.get('full_f1'))} · truncate={_fmt(cm.get('budget_f1'))} · "
                    f"model=`{_fmt(ctx.get('model'))}` |"
                )

        cod = block.get("coding") if isinstance(block.get("coding"), dict) else {}
        km = cod.get("metrics") if isinstance(cod.get("metrics"), dict) else {}
        if cod:
            primary_label = (
                "resolve_rate"
                if isinstance(km.get("resolve_rate"), (int, float))
                else "patch_rate"
            )
            primary_val = km.get("resolve_rate") if primary_label == "resolve_rate" else km.get(
                "patch_rate"
            )
            cod_note = (
                f"tier={_fmt(cod.get('sample_tier'))} · coding=`{_fmt(cod.get('coding_tier'))}` · "
                f"n={_fmt(cod.get('n_instances'))} · "
                f"resolve={'yes' if cod.get('harness') else 'no'} · `{_fmt(cod.get('infer_mode'))}`"
            )
            if smoke_banner:
                cod_note = f"不作效果结论 · {cod_note}"
            if cod.get("note"):
                cod_note = f"{cod_note} · {cod.get('note')}"
            out.append(
                f"| coding | {primary_label} | "
                f"{_fmt(primary_val)} | `{_fmt(cod.get('run_id'))}` | {cod_note} |"
            )
        return out

    rows = _suite_rows(suites)
    if rows:
        lines.extend(rows)
    else:
        lines.append("| — | — | — | — | 尚无锚点档入库 |")

    lines.extend(
        [
            "",
            "## 冒烟趋势（不作效果结论）",
            "",
            "| 套件 | 主指标 | 值 | run_id | 备注 |",
            "|------|--------|----|--------|------|",
        ]
    )
    smoke_rows = _suite_rows(smoke, smoke_banner=True)
    if smoke_rows:
        lines.extend(smoke_rows)
    else:
        lines.append("| — | — | — | — | 尚无冒烟指针 |")

    if is_l1:
        lines.extend(
            [
                "",
                "## Retrieval / Context cases",
                "",
                "明细见 Ops / `eval/reports/official/runs/<id>/`；分桶报告："
                "`python -m official_bench.bucket_report <manifest.json>`。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Retrieval · hybrid cases (nDCG@10)",
                "",
                "| case | nDCG@10 | R@100 |",
                "|------|---------|-------|",
            ]
        )
        ret = suites.get("retrieval") if isinstance(suites.get("retrieval"), dict) else {}
        cases = ret.get("cases") if isinstance(ret.get("cases"), dict) else {}
        for cid in sorted(cases):
            if ".hybrid" not in cid:
                continue
            m = cases[cid] if isinstance(cases[cid], dict) else {}
            lines.append(
                f"| `{cid}` | {_fmt(m.get('ndcg_at_10'))} | {_fmt(m.get('recall_at_100'))} |"
            )

        lines.extend(
            [
                "",
                "## Context · per task",
                "",
                "| case | full F1 | truncate F1 | compact F1 | compact retention |",
                "|------|---------|-------------|------------|-------------------|",
            ]
        )
        ctx = suites.get("context") if isinstance(suites.get("context"), dict) else {}
        cc = ctx.get("cases") if isinstance(ctx.get("cases"), dict) else {}
        for cid in sorted(cc):
            m = cc[cid] if isinstance(cc[cid], dict) else {}
            lines.append(
                f"| `{cid}` | {_fmt(m.get('full_f1'))} | {_fmt(m.get('budget_f1'))} | "
                f"{_fmt(m.get('compact_f1'))} | "
                f"{_fmt(m.get('retention_compact_vs_full') or m.get('retention'))} |"
            )

    lines.extend(
        [
            "",
            "## 怎么用（live 调优）",
            "",
            "```bash",
            "make official-bench-retrieval-agent context-agent coding-infer-agent   # L1 实测",
            "make official-bench-compare       # latest vs 本 scorecard/baseline 打 Δ 表（同档才比）",
            "make official-bench-update-baseline  # 认可后写 JSON + 刷新本文件（协议跟 latest）",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_scorecard(doc: dict[str, Any]) -> Path:
    path = scorecard_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_scorecard(doc), encoding="utf-8")
    return path


def compare_latest_to_baseline(
    *,
    suites: tuple[str, ...] = ("retrieval", "context", "coding"),
) -> dict[str, Any]:
    """Diff latest_* against committed baseline. A-4: refuse cross-tier Δ."""
    baseline = load_baseline() or {"suites": {}, "smoke_suites": {}}
    base_suites = baseline.get("suites") if isinstance(baseline.get("suites"), dict) else {}
    base_smoke = (
        baseline.get("smoke_suites") if isinstance(baseline.get("smoke_suites"), dict) else {}
    )
    latest_doc = build_baseline_from_latest(suites=suites)
    latest_suites = latest_doc.get("suites") if isinstance(latest_doc.get("suites"), dict) else {}
    latest_smoke = (
        latest_doc.get("smoke_suites") if isinstance(latest_doc.get("smoke_suites"), dict) else {}
    )

    primary_keys = {
        "retrieval": ("ndcg_at_10", "recall_at_100", "map_at_100"),
        "context": (
            "agent_f1",
            "agent_em",
            "oracle_f1",
            "retention_vs_oracle",
            "full_f1",
            "budget_f1",
            "compact_f1",
            "retention_compact_vs_full",
        ),
        "coding": ("resolve_rate", "patch_rate", "n_nonempty_patches"),
    }
    rows: list[dict[str, Any]] = []
    for suite in suites:
        keys = primary_keys.get(suite) or ()
        # Prefer comparing within the tier that latest actually updated.
        latest_anchor = latest_suites.get(suite) if isinstance(latest_suites.get(suite), dict) else None
        latest_sm = latest_smoke.get(suite) if isinstance(latest_smoke.get(suite), dict) else None
        # Which latest pointer is newest for this suite? Prefer the one in _meta updated list.
        meta = latest_doc.get("_meta") if isinstance(latest_doc.get("_meta"), dict) else {}
        updated = meta.get("updated_suites") or []
        prefer_smoke = f"{suite}:smoke" in updated and f"{suite}:anchor" not in updated
        l = latest_sm if prefer_smoke else (latest_anchor or latest_sm)
        if l is None:
            rows.append({"suite": suite, "status": "missing_or_ineligible_latest"})
            continue
        latest_tier = str(l.get("sample_tier") or ("smoke" if prefer_smoke else "anchor")).lower()
        b = (
            base_smoke.get(suite)
            if latest_tier == "smoke"
            else base_suites.get(suite)
        )
        if not isinstance(b, dict):
            # Fall back the other bucket only to report mismatch, not to invent Δ.
            other = base_suites.get(suite) if latest_tier == "smoke" else base_smoke.get(suite)
            if isinstance(other, dict):
                rows.append(
                    {
                        "suite": suite,
                        "status": "tier_mismatch",
                        "latest_tier": latest_tier,
                        "baseline_tier": other.get("sample_tier") or (
                            "anchor" if latest_tier == "smoke" else "smoke"
                        ),
                        "message": "refuse Δ: smoke vs anchor (A-4)",
                        "latest_run_id": l.get("run_id"),
                    }
                )
                continue
            rows.append({"suite": suite, "status": "missing_baseline_for_tier", "latest_tier": latest_tier})
            continue
        base_tier = str(b.get("sample_tier") or latest_tier).lower()
        if base_tier != latest_tier:
            rows.append(
                {
                    "suite": suite,
                    "status": "tier_mismatch",
                    "latest_tier": latest_tier,
                    "baseline_tier": base_tier,
                    "message": "refuse Δ: sample_tier mismatch (A-4)",
                    "latest_run_id": l.get("run_id"),
                }
            )
            continue
        bm = b.get("metrics") if isinstance(b.get("metrics"), dict) else {}
        lm = l.get("metrics") if isinstance(l.get("metrics"), dict) else {}
        for k in keys:
            bv = bm.get(k)
            lv = lm.get(k)
            delta = None
            if isinstance(bv, (int, float)) and isinstance(lv, (int, float)):
                delta = float(lv) - float(bv)
            rows.append(
                {
                    "suite": suite,
                    "metric": k,
                    "sample_tier": latest_tier,
                    "baseline": bv,
                    "latest": lv,
                    "delta": delta,
                    "latest_run_id": l.get("run_id"),
                }
            )
    return {
        "protocol_version": latest_doc.get("protocol_version") or baseline.get("protocol_version"),
        "baseline_updated_at": baseline.get("updated_at"),
        "rows": rows,
        "latest_meta": latest_doc.get("_meta"),
    }


def format_compare_table(report: dict[str, Any]) -> str:
    lines = [
        f"protocol={report.get('protocol_version')}  baseline_updated_at={report.get('baseline_updated_at')}",
        "",
        f"{'suite':<12} {'metric':<28} {'baseline':>10} {'latest':>10} {'delta':>10}",
        "-" * 74,
    ]
    for row in report.get("rows") or []:
        if row.get("status"):
            extra = row.get("message") or row.get("status")
            tier = ""
            if row.get("latest_tier") or row.get("baseline_tier"):
                tier = f" latest={row.get('latest_tier')} baseline={row.get('baseline_tier')}"
            lines.append(f"{row.get('suite'):<12} ({extra}{tier})")
            continue
        d = row.get("delta")
        ds = "—" if d is None else f"{d:+.4f}"
        lines.append(
            f"{str(row.get('suite')):<12} {str(row.get('metric')):<28} "
            f"{_fmt(row.get('baseline')):>10} {_fmt(row.get('latest')):>10} {ds:>10}"
        )
    return "\n".join(lines)


def write_baseline(doc: dict[str, Any], *, protocol: str | None = None) -> Path:
    pv = protocol or str(doc.get("protocol_version") or protocol_version())
    path = baseline_path(pv)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Drop internal helper key from committed file.
    out = {k: v for k, v in doc.items() if not k.startswith("_")}
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_scorecard(out)
    return path


def update_baseline_from_latest(
    *,
    suites: tuple[str, ...] = ("retrieval", "context", "coding"),
) -> tuple[Path, dict[str, Any]]:
    doc = build_baseline_from_latest(suites=suites)
    path = write_baseline(doc)
    return path, doc
