#!/usr/bin/env python3
"""§12 Batch-6-前置 offline: RET-14 / RET-15-1 / CTX-10 from existing free L1 runs.

Reads local official run artifacts (+ optional Postgres turn_events for read paths).
Writes markdown + JSON under eval/reports/official/batch6/ (gitignored reports tree).
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
    gold_read_case_stats,
)
from official_bench.l2_probes import gold_read_aggregate  # noqa: E402

RUNS = ROOT / "eval/reports/official/runs"
OUT = ROOT / "eval/reports/official/batch6"
BEIR_ROOT = ROOT / "eval/official/.local-data/beir"
LONGBENCH_SLICE = ROOT / "eval/official/.local-data/longbench/small_slice.jsonl"

# Default anchors from brief §11.7 / §12
RET_RUN = "3c34de88-3cc1-4b86-84e6-cb4fc656a0aa"
CTX_RUN = "1707135c-76c7-4cf7-8a86-3ba2f20dab5e"
LOW_SCORE_HINT = 0.15


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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
        # BEIR small: query-id \t corpus-id \t score
        qid, doc_id = parts[0], parts[1]
        try:
            rel = float(parts[2]) if len(parts) >= 3 else 1.0
        except ValueError:
            rel = 1.0
        if rel > 0:
            out[qid].add(str(doc_id))
    return dict(out)


def _qid_from_case_id(case_id: str) -> tuple[str, str] | None:
    # beir.scifact.q-<qid>
    m = re.match(r"beir\.(scifact|nfcorpus|fiqa)\.q-(.+)$", str(case_id or ""))
    if not m:
        return None
    return m.group(1), m.group(2)


def _read_paths_from_db(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """turn_id → ordered read_file paths (tool.started)."""
    cases = [
        c
        for c in (manifest.get("cases") or [])
        if isinstance(c, dict)
        and c.get("turn_id")
        and not str(c.get("case_id") or "").endswith(".agent")
    ]
    if not cases:
        return {}
    vals = ", ".join(f"('{c['turn_id']}')" for c in cases)
    sql = f"""
SELECT e.turn_id::text || E'\\t' || COALESCE(e.payload->'arguments'->>'path','')
FROM turn_events e
WHERE e.turn_id IN (SELECT turn_id::uuid FROM (VALUES {vals}) AS v(turn_id))
  AND e.type='tool.started'
  AND e.payload->>'tool_name'='read_file'
ORDER BY e.turn_id, e.sequence;
"""
    raw = _pgsql(sql)
    if raw.startswith("__error__"):
        return {}
    by_turn: dict[str, list[str]] = defaultdict(list)
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[1]:
            continue
        by_turn[parts[0]].append(parts[1])
    return dict(by_turn)


def ret14_gold_read(manifest: dict[str, Any]) -> dict[str, Any]:
    """RET-14 offline: gold ∩ ranked ∩ read for an existing retrieval run."""
    qrels_cache: dict[str, dict[str, set[str]]] = {}
    read_by_turn = _read_paths_from_db(manifest)
    enriched: list[dict[str, Any]] = []
    for c in manifest.get("cases") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("case_id") or "")
        if cid.endswith(".agent"):
            continue
        parsed = _qid_from_case_id(cid)
        if not parsed:
            continue
        ds, qid = parsed
        if ds not in qrels_cache:
            qrels_cache[ds] = _load_qrels(ds)
        gold = qrels_cache[ds].get(qid) or set()
        ranked_ids: list[str] = []
        for h in c.get("top_hits") or []:
            if isinstance(h, dict):
                did = str(h.get("doc_id") or doc_id_from_path(str(h.get("path") or "")))
                if did and did not in ranked_ids:
                    ranked_ids.append(did)
        # Prefer full merge length from metrics when top_hits is truncated:
        # still use top_hits for intersection when DB ranked unavailable.
        tid = str(c.get("turn_id") or "")
        read_paths = read_by_turn.get(tid) or []
        read_ids: list[str] = []
        for p in read_paths:
            did = doc_id_from_path(p)
            if did and did not in read_ids:
                read_ids.append(did)
        # Fallback: if tools include read_file but DB empty, cannot classify unread.
        stats = gold_read_case_stats(
            ranked_doc_ids=ranked_ids,
            read_doc_ids=read_ids,
            gold_doc_ids=gold,
        )
        row = dict(c)
        l2 = dict(row.get("l2") or {})
        l2.update(
            {
                "read_doc_ids": read_ids,
                "gold_read_n": stats["gold_read_n"],
                "gold_on_ranked_n": stats["gold_on_ranked_n"],
                "gold_on_ranked_but_unread_n": stats["gold_on_ranked_but_unread_n"],
                "read_any_gold": stats["read_any_gold"],
                "gold_read_failure_slice": stats["failure_slice"],
                "read_target_ranks": stats["read_target_ranks"],
            }
        )
        row["l2"] = l2
        for k in (
            "read_doc_ids",
            "gold_read_n",
            "gold_on_ranked_n",
            "gold_on_ranked_but_unread_n",
            "read_any_gold",
            "gold_read_failure_slice",
            "read_target_ranks",
        ):
            row[k] = l2[k]
        enriched.append(row)

    agg = gold_read_aggregate(enriched)
    db_ok = bool(read_by_turn)
    # Distinct-doc diversity in top-5 detail slots (RET-16 gate input).
    detail_mono = 0
    detail_n = 0
    for c in enriched:
        hits = c.get("top_hits") or []
        if not isinstance(hits, list) or not hits:
            continue
        detail_n += 1
        docs = []
        for h in hits[:5]:
            if isinstance(h, dict):
                docs.append(str(h.get("doc_id") or ""))
        if len(set(d for d in docs if d)) <= 2:
            detail_mono += 1
    ret16_share = round(detail_mono / detail_n, 3) if detail_n else None
    return {
        "ok": True,
        "db_read_paths": db_ok,
        "aggregate": agg,
        "n_enriched": len(enriched),
        "ret16_detail_slot_le2_docs_share": ret16_share,
        "open_ret16": bool(ret16_share is not None and ret16_share >= (1 / 3)),
        "note": (
            None
            if db_ok
            else "Postgres read paths unavailable; gold_read_rate undercounts reads."
        ),
        "cases": [
            {
                "case_id": c.get("case_id"),
                "bucket": c.get("bucket"),
                "ndcg_at_10": (c.get("metrics") or {}).get("ndcg_at_10"),
                "gold_read_failure_slice": c.get("gold_read_failure_slice"),
                "read_any_gold": c.get("read_any_gold"),
                "gold_on_ranked_n": c.get("gold_on_ranked_n"),
                "gold_on_ranked_but_unread_n": c.get("gold_on_ranked_but_unread_n"),
                "read_doc_ids": c.get("read_doc_ids"),
            }
            for c in enriched
        ],
    }


def ret15_score_audit(manifest: dict[str, Any], *, threshold: float = LOW_SCORE_HINT) -> dict[str, Any]:
    """RET-15 stage 1: score distribution vs low_score hint threshold."""
    top1_scores: list[float] = []
    all_scores: list[float] = []
    by_ds: dict[str, list[float]] = defaultdict(list)
    n_cases = 0
    n_top1_below = 0
    for c in manifest.get("cases") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("case_id") or "")
        if cid.endswith(".agent"):
            continue
        hits = c.get("top_hits") or []
        if not isinstance(hits, list) or not hits:
            continue
        n_cases += 1
        ds = "other"
        for name in ("scifact", "nfcorpus", "fiqa"):
            if f".{name}." in cid:
                ds = name
                break
        scores = []
        for h in hits:
            if isinstance(h, dict) and isinstance(h.get("score"), (int, float)):
                scores.append(float(h["score"]))
        if not scores:
            continue
        top1 = scores[0]
        top1_scores.append(top1)
        by_ds[ds].append(top1)
        all_scores.extend(scores)
        if top1 < threshold:
            n_top1_below += 1

    def _pct(xs: list[float], p: float) -> float | None:
        if not xs:
            return None
        s = sorted(xs)
        i = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
        return s[i]

    trigger_rate = (n_top1_below / n_cases) if n_cases else None
    # Adjudication: never / always / mixed relative to designed 0.15 threshold.
    if trigger_rate is None:
        adjudication = "no_scores"
    elif trigger_rate == 0.0:
        adjudication = "never_triggers"
    elif trigger_rate >= 0.95:
        adjudication = "always_triggers"
    else:
        adjudication = "mixed"
    open_stage2 = adjudication in {"never_triggers", "always_triggers"}
    return {
        "threshold": threshold,
        "n_cases_with_hits": n_cases,
        "top1_trigger_rate": round(trigger_rate, 4) if trigger_rate is not None else None,
        "adjudication": adjudication,
        "open_ret15_stage2_normalize": open_stage2,
        "top1": {
            "min": min(top1_scores) if top1_scores else None,
            "max": max(top1_scores) if top1_scores else None,
            "mean": (sum(top1_scores) / len(top1_scores)) if top1_scores else None,
            "p10": _pct(top1_scores, 10),
            "p50": _pct(top1_scores, 50),
            "p90": _pct(top1_scores, 90),
        },
        "all_hits": {
            "n": len(all_scores),
            "min": min(all_scores) if all_scores else None,
            "max": max(all_scores) if all_scores else None,
            "mean": (sum(all_scores) / len(all_scores)) if all_scores else None,
            "p10": _pct(all_scores, 10),
            "p50": _pct(all_scores, 50),
        },
        "by_dataset_top1_mean": {
            ds: (sum(xs) / len(xs) if xs else None) for ds, xs in sorted(by_ds.items())
        },
        "verdict": (
            f"low_score hint@{threshold} → {adjudication}; "
            + (
                "open stage-2 (normalize / percentile threshold)"
                if open_stage2
                else "stage-2 not required by magnitude mismatch alone"
            )
        ),
    }


def _load_longbench_golds() -> dict[str, list[str]]:
    """Map longbench.<task>.<idx> → answers list."""
    out: dict[str, list[str]] = {}
    if not LONGBENCH_SLICE.is_file():
        return out
    # small_slice is ordered; case_id uses task + index within task? Runner uses idx from enumerate.
    # Prefer matching via task + sequential idx in slice order per task.
    per_task: dict[str, int] = defaultdict(int)
    for line in LONGBENCH_SLICE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        task = str(row.get("task") or row.get("dataset") or "longbench")
        idx = per_task[task]
        per_task[task] += 1
        golds_raw = row.get("answers") or row.get("answer")
        if isinstance(golds_raw, str):
            golds = [golds_raw]
        elif isinstance(golds_raw, list):
            golds = [str(x) for x in golds_raw]
        else:
            golds = [str(golds_raw or "")]
        out[f"longbench.{task}.{idx}"] = golds
        # Also key by explicit idx field if present
        if row.get("idx") is not None:
            out[f"longbench.{task}.{row['idx']}"] = golds
    return out


def _norm_ans(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _alias_close(pred: str, golds: list[str]) -> bool:
    """True if normalized pred ≈ any gold (alias / format / plural light)."""
    pn = _norm_ans(pred)
    if not pn:
        return False
    for g in golds:
        gn = _norm_ans(g)
        if not gn:
            continue
        if pn == gn:
            return True
        if pn in gn or gn in pn:
            return True
        # token Jaccard
        pt, gt = set(pn.split()), set(gn.split())
        if pt and gt:
            j = len(pt & gt) / len(pt | gt)
            if j >= 0.8:
                return True
    return False


def _tool_seq_from_db(turn_ids: list[str]) -> dict[str, list[str]]:
    if not turn_ids:
        return {}
    vals = ", ".join(f"('{t}')" for t in turn_ids)
    sql = f"""
SELECT e.turn_id::text || E'\\t' || COALESCE(e.payload->>'tool_name','')
FROM turn_events e
WHERE e.turn_id IN (SELECT turn_id::uuid FROM (VALUES {vals}) AS v(turn_id))
  AND e.type='tool.started'
ORDER BY e.turn_id, e.sequence;
"""
    raw = _pgsql(sql)
    if raw.startswith("__error__"):
        return {}
    out: dict[str, list[str]] = defaultdict(list)
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1]:
            out[parts[0]].append(parts[1])
    return dict(out)


def ctx10_wrong_answer(manifest: dict[str, Any]) -> dict[str, Any]:
    """CTX-10: classify wrong_answer_after_read into (i)/(ii)/(iii)/(iv)."""
    golds = _load_longbench_golds()
    cases = [
        c
        for c in (manifest.get("cases") or [])
        if isinstance(c, dict) and c.get("bucket") == "wrong_answer_after_read"
    ]
    turn_tools = _tool_seq_from_db(
        [str(c.get("turn_id")) for c in cases if c.get("turn_id")]
    )
    classified = []
    counts: Counter[str] = Counter()
    for c in cases:
        cid = str(c.get("case_id") or "")
        pred = str(c.get("pred") or "")
        gold_list = golds.get(cid) or []
        cov = float(c.get("read_coverage") or 0.0)
        n_reads = int(c.get("n_reads") or 0)
        used_off = bool(c.get("used_next_offset"))
        tools = turn_tools.get(str(c.get("turn_id") or "")) or []
        metrics = c.get("metrics") if isinstance(c.get("metrics"), dict) else {}
        em = float(metrics.get("em") or 0.0)
        f1 = float(metrics.get("f1") or 0.0)

        # (iii) scorer/alias: EM=1 with F1=0 quirk, or near-alias mismatch
        if em >= 1.0 and f1 <= 0.0:
            klass = "iii_scorer_alias"
        elif _alias_close(pred, gold_list) and f1 < 0.5:
            klass = "iii_scorer_alias"
        # (iv) multi-hop assembly: ≥2 reads or continue, coverage ok, still wrong
        elif (n_reads >= 2 or used_off) and cov >= 0.05 and "hotpotqa" in cid:
            klass = "iv_multihop_assembly"
        # (ii) localization: low coverage or single blind read on long narrative
        elif cov < 0.15 or (n_reads <= 1 and not used_off and "narrativeqa" in cid):
            klass = "ii_localization_miss"
        else:
            klass = "i_read_but_reason_wrong"

        counts[klass] += 1
        classified.append(
            {
                "case_id": cid,
                "pred": pred[:120],
                "golds": [g[:80] for g in gold_list[:3]],
                "f1": f1,
                "em": em,
                "read_coverage": cov,
                "n_reads": n_reads,
                "used_next_offset": used_off,
                "tools": tools,
                "failure_class": klass,
            }
        )

    n = len(classified) or 1
    share = {k: round(v / n, 3) for k, v in counts.items()}
    i_iv = counts.get("i_read_but_reason_wrong", 0) + counts.get(
        "iv_multihop_assembly", 0
    )
    ii = counts.get("ii_localization_miss", 0)
    iii = counts.get("iii_scorer_alias", 0)
    return {
        "n_wrong_answer": len(classified),
        "class_counts": dict(counts),
        "class_share": share,
        "ctx8_addressable_share": round(i_iv / n, 3),
        "open_ctx11": ii / n >= (1 / 3),
        "scorer_limit_share": round(iii / n, 3),
        "ctx8_expected_band": (
            "full"
            if i_iv / n >= 0.5
            else ("downshift" if i_iv / n < 0.35 else "moderate")
        ),
        "cases": classified,
        "verdict": (
            f"(i)+(iv)={i_iv}/{len(classified)} → CTX-8 expected {('full' if i_iv/n>=0.5 else 'downshift' if i_iv/n<0.35 else 'moderate')}; "
            f"(ii)={ii} → CTX-11 {'open' if ii/n >= 1/3 else 'hold'}; "
            f"(iii)={iii} → ruler limit (do not retune scorer for points)"
        ),
    }


def write_reports(
    *,
    ret_run: str = RET_RUN,
    ctx_run: str = CTX_RUN,
) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    ret_dir = RUNS / ret_run
    ctx_dir = RUNS / ctx_run
    ret_manifest = _load_json(ret_dir / "manifest.json")
    ctx_manifest = _load_json(ctx_dir / "manifest.json")

    ret14 = ret14_gold_read(ret_manifest)
    ret15 = ret15_score_audit(ret_manifest)
    ctx10 = ctx10_wrong_answer(ctx_manifest)

    payload = {
        "ret_run_id": ret_run,
        "ctx_run_id": ctx_run,
        "RET-14": {k: v for k, v in ret14.items() if k != "cases"},
        "RET-15": ret15,
        "CTX-10": {k: v for k, v in ctx10.items() if k != "cases"},
    }
    (OUT / "batch6_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "ret14_cases.json").write_text(
        json.dumps(ret14, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "ctx10_cases.json").write_text(
        json.dumps(ctx10, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Batch 6 前置 offline (§12)",
        "",
        f"- retrieval run: `{ret_run}`",
        f"- context run: `{ctx_run}`",
        "",
        "## RET-14 gold-read",
        "",
        "```json",
        json.dumps(payload["RET-14"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## RET-15 score / low_score hint audit",
        "",
        "```json",
        json.dumps(ret15, ensure_ascii=False, indent=2),
        "```",
        "",
        "## CTX-10 wrong_answer_after_read",
        "",
        "```json",
        json.dumps(payload["CTX-10"], ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    (OUT / "batch6_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ret-run", default=RET_RUN)
    ap.add_argument("--ctx-run", default=CTX_RUN)
    args = ap.parse_args()
    payload = write_reports(ret_run=args.ret_run, ctx_run=args.ctx_run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
