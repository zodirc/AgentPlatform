#!/usr/bin/env python3
"""§13 offline: RET-17 gold rank bands + CTX-12 EM residual anatomy.

Reuses existing free L1 run artifacts (+ optional Postgres turn_events for full
ranked lists). Writes under eval/reports/official/batch6b/ (gitignored).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.agent_path_extract import (  # noqa: E402
    doc_id_from_path,
    merge_retrieval_rankings,
)
from official_bench.context_run import _normalize as normalize_answer  # noqa: E402

RUNS = ROOT / "eval/reports/official/runs"
OUT = ROOT / "eval/reports/official/batch6b"
BEIR_ROOT = ROOT / "eval/official/.local-data/beir"
LONGBENCH_SLICE = ROOT / "eval/official/.local-data/longbench/small_slice.jsonl"

# Default anchors from brief §12.8–12.9 / §13.2
RET_RUNS = [
    "dfe97d37-05ac-4ea9-8d98-8f5ff0fca312",
    "6c87e401-eab4-4f68-98e5-95a9fe6c98d5",
    "bcdbbb85",  # prefix ok — resolved below
    "f92bc610",
]
CTX_RUNS = [
    "13647cb0",
    "61624e34",
]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_run(prefix_or_id: str) -> Path | None:
    p = RUNS / prefix_or_id
    if (p / "manifest.json").is_file():
        return p
    matches = sorted(RUNS.glob(f"{prefix_or_id}*"))
    for m in matches:
        if (m / "manifest.json").is_file():
            return m
    return None


def _pgsql(sql: str) -> str:
    try:
        proc = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "agent-postgres",
                "psql",
                "-U",
                "agent",
                "-d",
                "agent",
                "-t",
                "-A",
            ],
            input=sql,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"__error__:{exc}"
    if proc.returncode != 0:
        return f"__error__:{(proc.stderr or proc.stdout or '')[:400]}"
    return proc.stdout or ""


def _load_qrels(dataset: str) -> dict[str, set[str]]:
    path = BEIR_ROOT / dataset / "qrels" / "test.tsv"
    out: dict[str, set[str]] = defaultdict(set)
    if not path.is_file():
        return {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        parts = line.split("\t")
        if i == 0 and parts[0].lower() in {"query-id", "qid"}:
            continue
        if len(parts) < 2:
            continue
        qid, doc_id = parts[0], parts[1]
        try:
            rel = float(parts[2]) if len(parts) >= 3 else 1.0
        except ValueError:
            rel = 1.0
        if rel > 0:
            out[qid].add(str(doc_id))
    return dict(out)


def _qid_from_case_id(case_id: str) -> tuple[str, str] | None:
    m = re.match(r"beir\.(scifact|nfcorpus|fiqa)\.q-(.+)$", str(case_id or ""))
    if not m:
        return None
    return m.group(1), m.group(2)


def _rank_band(rank: int | None) -> str:
    if rank is None:
        return "absent"
    if rank <= 10:
        return "top10"
    if rank <= 30:
        return "11-30"
    if rank <= 100:
        return "31-100"
    return "absent"


def _ranked_from_case_fallback(case: dict[str, Any]) -> list[str]:
    """Best-effort ranked list when DB events unavailable (top_hits only ≤10)."""
    hits = case.get("top_hits") or []
    ordered: list[str] = []
    seen: set[str] = set()
    if isinstance(hits, list):
        for h in hits:
            if not isinstance(h, dict):
                continue
            doc_id = str(h.get("doc_id") or doc_id_from_path(str(h.get("path") or "")))
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                ordered.append(doc_id)
    return ordered


def _ranked_from_db(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """turn_id → first-seen merged ranked doc ids from retrieval.completed."""
    cases = [
        c
        for c in (manifest.get("cases") or [])
        if isinstance(c, dict)
        and c.get("turn_id")
        and not str(c.get("case_id") or "").endswith(".agent")
    ]
    if not cases:
        return {}
    turn_ids = [str(c["turn_id"]) for c in cases if c.get("turn_id")]
    if not turn_ids:
        return {}
    vals = ", ".join(f"('{tid}')" for tid in turn_ids)
    sql = f"""
SELECT e.turn_id::text || E'\\t' || e.payload::text
FROM turn_events e
WHERE e.turn_id IN (SELECT turn_id::uuid FROM (VALUES {vals}) AS v(turn_id))
  AND e.type='retrieval.completed'
ORDER BY e.turn_id, e.sequence;
"""
    raw = _pgsql(sql)
    if raw.startswith("__error__"):
        return {}
    by_turn_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in raw.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        tid, payload_s = line.split("\t", 1)
        try:
            payload = json.loads(payload_s)
        except json.JSONDecodeError:
            continue
        by_turn_events[tid].append({"type": "retrieval.completed", "payload": payload})
    out: dict[str, list[str]] = {}
    for tid, events in by_turn_events.items():
        out[tid] = merge_retrieval_rankings(events)
    return out


def ret17_gold_rank_bands(manifest: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    """RET-17: best gold doc rank → {top10 / 11-30 / 31-100 / absent}."""
    ranked_by_turn = _ranked_from_db(manifest)
    db_ok = bool(ranked_by_turn)
    qrels_cache: dict[str, dict[str, set[str]]] = {}
    bands = Counter()
    by_ds: dict[str, Counter] = defaultdict(Counter)
    cases_out: list[dict[str, Any]] = []
    for c in manifest.get("cases") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("case_id") or "")
        parsed = _qid_from_case_id(cid)
        if not parsed:
            continue
        ds, qid = parsed
        if ds not in qrels_cache:
            qrels_cache[ds] = _load_qrels(ds)
        gold = qrels_cache[ds].get(qid) or set()
        tid = str(c.get("turn_id") or "")
        ranked = ranked_by_turn.get(tid) or _ranked_from_case_fallback(c)
        best: int | None = None
        for i, doc_id in enumerate(ranked, start=1):
            if doc_id in gold:
                best = i
                break
        # If DB missing and gold not in top_hits, use RET-14 slice when present.
        if best is None and not db_ok:
            slice_name = str(c.get("gold_read_failure_slice") or "")
            if slice_name == "absent_from_ranked":
                best = None
            elif int(c.get("gold_on_ranked_n") or 0) > 0:
                # Known on ranked but rank unknown with top10-only fallback.
                best = 11  # conservative → 11-30 band for sizing
        band = _rank_band(best)
        bands[band] += 1
        by_ds[ds][band] += 1
        cases_out.append(
            {
                "case_id": cid,
                "dataset": ds,
                "best_gold_rank": best,
                "band": band,
                "ranked_len": len(ranked),
                "ndcg_at_10": (c.get("metrics") or {}).get("ndcg_at_10"),
            }
        )
    n = sum(bands.values()) or 1
    shares = {k: round(bands.get(k, 0) / n, 3) for k in ("top10", "11-30", "31-100", "absent")}
    # Honest sizing note for RET-4: absent share = recall ceiling pressure.
    return {
        "run_id": run_id,
        "db_ranked": db_ok,
        "n_cases": sum(bands.values()),
        "bands": dict(bands),
        "shares": shares,
        "by_dataset": {ds: dict(ctr) for ds, ctr in by_ds.items()},
        "ret4_sizing": {
            "absent_share": shares["absent"],
            "rank_11_100_share": round(
                shares["11-30"] + shares["31-100"], 3
            ),
            "note": (
                "absent → RET-4/11 recall ceiling; 11–100 → ranking residual "
                "(do not open new rerank knife; let embed lift absorb)"
            ),
        },
        "cases": cases_out,
    }


def _load_longbench_golds() -> dict[str, list[str]]:
    """Keys: `longbench.{task}.{idx}` and `task|question` → answers."""
    out: dict[str, list[str]] = {}
    if not LONGBENCH_SLICE.is_file():
        return out
    # Per-task running index matches runner materialize order (small_slice order).
    task_counts: dict[str, int] = defaultdict(int)
    for line in LONGBENCH_SLICE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        task = str(row.get("task") or row.get("dataset") or "")
        q = str(row.get("question") or row.get("input") or "").strip()
        golds_raw = row.get("answers") or row.get("answer")
        if isinstance(golds_raw, str):
            golds = [golds_raw]
        elif isinstance(golds_raw, list):
            golds = [str(x) for x in golds_raw]
        else:
            golds = [str(golds_raw or "")]
        out[f"{task}|{q}"] = golds
        idx = row.get("idx")
        if idx is None:
            idx = task_counts[task]
            task_counts[task] += 1
        else:
            idx = int(idx)
            task_counts[task] = max(task_counts[task], idx + 1)
        out[f"longbench.{task}.{idx}"] = golds
    return out


def _ctx12_class(pred: str, golds: list[str], *, f1: float) -> str:
    """Heuristic α/β/γ for EM=0 ∧ F1>0 (δ is batch-level noise, not per-case)."""
    p_raw = (pred or "").strip()
    p_norm = normalize_answer(p_raw)
    gold_norms = [normalize_answer(g) for g in golds if str(g).strip()]
    # (α) short overshoot: pred is proper substring of a gold (dropped qualifier)
    for g, gn in zip(golds, gold_norms):
        g_raw = str(g).strip()
        if p_raw and g_raw and p_raw != g_raw and (p_raw in g_raw or p_norm in gn):
            if len(p_norm) < len(gn):
                return "alpha_short_overshoot"
    # (β) alias / normalize: tokens largely overlap after normalize, near-equal length
    for gn in gold_norms:
        if not p_norm or not gn:
            continue
        pt, gt = set(p_norm.split()), set(gn.split())
        if pt and gt and (pt <= gt or gt <= pt) and abs(len(p_norm) - len(gn)) <= 4:
            return "beta_scorer_alias"
        if pt & gt and f1 >= 0.5:
            # high F1 but EM=0 often alias/format
            if abs(len(pt) - len(gt)) <= 2:
                return "beta_scorer_alias"
    # (γ) paraphrase / synonym path — F1>0 residual
    if f1 > 0:
        return "gamma_paraphrase"
    return "other"


def ctx12_em_residual(manifest: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    """CTX-12: EM=0 ∧ F1>0 residual anatomy."""
    gold_index = _load_longbench_golds()
    classified: list[dict[str, Any]] = []
    counts = Counter()
    for c in manifest.get("cases") or []:
        if not isinstance(c, dict):
            continue
        if str(c.get("bucket") or "") == "infra_channel":
            continue
        metrics = c.get("metrics") or {}
        em = float(metrics.get("em") or metrics.get("agent_em") or 0.0)
        f1 = float(metrics.get("f1") or metrics.get("agent_f1") or 0.0)
        if em >= 1.0 or f1 <= 0.0:
            continue
        pred = str(c.get("pred") or "")
        golds: list[str] = []
        for key in ("golds", "answers", "gold"):
            raw = c.get(key)
            if isinstance(raw, list):
                golds = [str(x) for x in raw]
                break
            if isinstance(raw, str) and raw.strip():
                golds = [raw]
                break
        cid = str(c.get("case_id") or "")
        if not golds and cid in gold_index:
            golds = gold_index[cid]
        label = _ctx12_class(pred, golds, f1=f1) if golds else (
            "gamma_paraphrase" if f1 > 0 else "other"
        )
        counts[label] += 1
        classified.append(
            {
                "case_id": c.get("case_id"),
                "bucket": c.get("bucket"),
                "em": em,
                "f1": f1,
                "pred": pred[:200],
                "golds": [g[:120] for g in golds[:3]],
                "class": label,
                "had_golds": bool(golds),
            }
        )
    n = sum(counts.values()) or 1
    # δ note: same-config EM Δ≈3.4pp (~2 cases) — deduct before "streak" narrative.
    return {
        "run_id": run_id,
        "n_em0_f1pos": sum(counts.values()),
        "counts": dict(counts),
        "shares": {k: round(v / n, 3) for k, v in counts.items()},
        "delta_noise_note": (
            "Same-config CTX-7 pair EM Δ≈3.4pp (~2/60); deduct before calling "
            "a three-run EM drop a causal streak (δ)."
        ),
        "implications": {
            "alpha_dominant": "tune CTX-7 example wording (single knife), do not roll back CTX-1",
            "beta_dominant": "scorer/alias limitation — record in终态归因, do not open knife",
            "gamma_dominant": "CTX-8 may add 'prefer passage wording in final short answer'",
        },
        "gold_index_size": len(gold_index),
        "cases": classified,
    }


def write_reports(*, ret_prefixes: list[str], ctx_prefixes: list[str]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    ret_payloads = []
    for pref in ret_prefixes:
        path = _resolve_run(pref)
        if path is None:
            ret_payloads.append({"run_prefix": pref, "ok": False, "error": "not_found"})
            continue
        manifest = _load_json(path / "manifest.json")
        # Prefer result.json cases when richer
        result_path = path / "result.json"
        if result_path.is_file():
            result = _load_json(result_path)
            if isinstance(result, dict) and result.get("cases"):
                # Official runner keeps per-query cases on manifest; result may be rollups.
                pass
        analysis = ret17_gold_rank_bands(manifest, run_id=path.name)
        analysis["ok"] = True
        analysis["run_prefix"] = pref
        ret_payloads.append(analysis)
        (OUT / f"ret17_{path.name[:8]}.json").write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    ctx_payloads = []
    for pref in ctx_prefixes:
        path = _resolve_run(pref)
        if path is None:
            ctx_payloads.append({"run_prefix": pref, "ok": False, "error": "not_found"})
            continue
        manifest = _load_json(path / "manifest.json")
        analysis = ctx12_em_residual(manifest, run_id=path.name)
        analysis["ok"] = True
        analysis["run_prefix"] = pref
        ctx_payloads.append(analysis)
        (OUT / f"ctx12_{path.name[:8]}.json").write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    payload = {
        "RET-17": ret_payloads,
        "CTX-12": ctx_payloads,
    }
    (OUT / "batch6b_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Batch 6b offline (§13 RET-17 / CTX-12)",
        "",
        "## RET-17 gold rank bands",
        "",
        "```json",
        json.dumps(ret_payloads, ensure_ascii=False, indent=2),
        "```",
        "",
        "## CTX-12 EM residual",
        "",
        "```json",
        json.dumps(ctx_payloads, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    (OUT / "batch6b_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ret-run", action="append", default=None)
    ap.add_argument("--ctx-run", action="append", default=None)
    args = ap.parse_args()
    ret = args.ret_run or RET_RUNS
    ctx = args.ctx_run or CTX_RUNS
    payload = write_reports(ret_prefixes=ret, ctx_prefixes=ctx)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
