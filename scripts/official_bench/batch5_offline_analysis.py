#!/usr/bin/env python3
"""§10 Batch 5 offline analysis: RET-6 / RET-8 / CTX-4 from existing free L1 runs.

Reads local official run artifacts (+ optional Postgres turn_events for limits).
Writes markdown + JSON under eval/reports/official/batch5/.
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

from official_bench.l2_probes import depth_audit_aggregate  # noqa: E402

RUNS = ROOT / "eval/reports/official/runs"
OUT = ROOT / "eval/reports/official/batch5"

RET_RUN = "99d729de-c6dd-44f8-b46c-8ba7f7269757"
CTX_RUN = "083eca09-49c4-46b3-8b7b-31e8f41a814c"


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
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"__error__:{exc}"
    if proc.returncode != 0:
        return f"__error__:{(proc.stderr or proc.stdout or '')[:400]}"
    return proc.stdout or ""


def _postgres_depth_from_db(manifest: dict[str, Any]) -> dict[str, Any]:
    """Pull per-search limit + ranked_len from turn_events for RET-6."""
    cases = [
        c
        for c in (manifest.get("cases") or [])
        if isinstance(c, dict)
        and c.get("turn_id")
        and not str(c.get("case_id") or "").endswith(".agent")
    ]
    if not cases:
        return {"ok": False, "error": "no_cases"}
    meta = {
        str(c["turn_id"]): {
            "case_id": c.get("case_id"),
            "n_hits": (c.get("metrics") or {}).get("n_hits"),
            "n_search": c.get("n_search"),
        }
        for c in cases
    }
    vals = ", ".join(f"('{tid}')" for tid in meta)
    sql = f"""
SELECT e.turn_id::text || E'\\t' || e.type || E'\\t' ||
       COALESCE(e.payload->'arguments'->>'limit','') || E'\\t' ||
       COALESCE(e.payload->>'hit_count','') || E'\\t' ||
       COALESCE(jsonb_array_length(e.payload->'ranked')::text,'')
FROM turn_events e
WHERE e.turn_id IN (SELECT turn_id::uuid FROM (VALUES {vals}) AS v(turn_id))
  AND (
    (e.type='tool.started' AND e.payload->>'tool_name'='search_sources')
    OR e.type='retrieval.completed'
  )
ORDER BY e.turn_id, e.sequence;
"""
    raw = _pgsql(sql)
    if raw.startswith("__error__"):
        return {"ok": False, "error": raw}
    by_turn: dict[str, dict[str, list[Any]]] = defaultdict(
        lambda: {"limits": [], "ranked_lengths": []}
    )
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        tid, etype, lim, _hc, ranked_len = parts[0], parts[1], parts[2], parts[3], parts[4]
        if etype == "tool.started":
            by_turn[tid]["limits"].append(int(lim) if lim.isdigit() else None)
        elif ranked_len.isdigit():
            by_turn[tid]["ranked_lengths"].append(int(ranked_len))

    enriched = []
    for c in cases:
        tid = str(c.get("turn_id"))
        info = by_turn.get(tid, {"limits": [], "ranked_lengths": []})
        row = dict(c)
        row["search_limits"] = info["limits"]
        row["ranked_lengths"] = info["ranked_lengths"]
        merged = (c.get("metrics") or {}).get("n_hits")
        row["merged_len"] = int(merged) if merged is not None else 0
        l2 = dict(row.get("l2") or {})
        l2["search_limits"] = info["limits"]
        l2["ranked_lengths"] = info["ranked_lengths"]
        l2["merged_len"] = row["merged_len"]
        row["l2"] = l2
        enriched.append(row)

    agg = depth_audit_aggregate(enriched)
    notes = {
        "fiqa_note": (
            "On 99d729de, FiQA searches pass limit≥20/30 but ranked_len≈9–11. "
            "SciFact/NFCorpus fill to 30. DB audit: BM25 often empty on long FiQA "
            "queries; vector lane keeps only cosine score>0 neighbors "
            "(pgvector_store.search_vector drops score<=0), collapsing the pool. "
            "Adjudication → pool_starvation_despite_limit (not small model limit; "
            "not first-seen burial). RET-5 stays suspended; RET-4 / score-filter "
            "review are the structural levers."
        )
    }
    return {"ok": True, "aggregate": agg, "notes": notes, "n_enriched": len(enriched)}


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def classify_weak_hit(card: dict[str, Any], qrels_doc_ids: set[str] | None = None) -> str:
    """RET-8 failure class: lexical_miss | near_topic_miss | qrels_structure | other."""
    query = str(card.get("query") or "")
    q_toks = _tokenize(query)
    top = card.get("top_hits") or []
    if not isinstance(top, list):
        top = []
    hit_toks: set[str] = set()
    hit_ids: set[str] = set()
    for h in top:
        if not isinstance(h, dict):
            continue
        doc_id = str(h.get("doc_id") or "")
        path = str(h.get("path") or "")
        if not doc_id and path:
            doc_id = Path(path).stem
        if doc_id:
            hit_ids.add(doc_id)
        hit_toks |= _tokenize(doc_id)
        hit_toks |= _tokenize(path)
    overlap = q_toks & hit_toks
    ndcg = float(card.get("ndcg_at_10") or 0.0)
    cid = str(card.get("case_id") or "")

    # NFCorpus structural: many qrels, R@10 structurally hard — flag by dataset + tiny nDCG
    if "nfcorpus" in cid and ndcg < 0.15:
        return "qrels_structure"
    if not top and ndcg <= 0.0:
        return "lexical_miss"
    if len(overlap) <= 1 and len(q_toks) >= 4:
        return "lexical_miss"
    if qrels_doc_ids is not None and hit_ids and hit_ids.isdisjoint(qrels_doc_ids):
        # hits present but none gold — near-topic / ranking granularity
        if overlap:
            return "near_topic_miss"
        return "lexical_miss"
    if overlap and ndcg < 0.35:
        return "near_topic_miss"
    return "other"


def ret8_classify(result: dict[str, Any]) -> dict[str, Any]:
    cards = result.get("weak_hits_cases") or []
    classified = []
    counts: Counter[str] = Counter()
    for card in cards:
        if not isinstance(card, dict):
            continue
        klass = classify_weak_hit(card)
        counts[klass] += 1
        classified.append({**card, "failure_class": klass})
    n = len(classified) or 1
    share = {k: round(v / n, 3) for k, v in counts.items()}
    embed_ready = (counts.get("lexical_miss", 0) + counts.get("near_topic_miss", 0)) >= (
        len(classified) / 2
    )
    return {
        "n_cards": len(classified),
        "class_counts": dict(counts),
        "class_share": share,
        "embed_ticket_sufficient": embed_ready,
        "cases": classified,
        "verdict": (
            "RET-4 立项充分（①+②≥半数）"
            if embed_ready
            else "③ 结构类占比较高 → RET-4 预期下修"
        ),
    }


def ctx4_classify(process_path: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    """Classify gave_up_early probes; enrich with tool sequence when turn_id known."""
    probes = []
    for line in process_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") == "l2_probe" and row.get("bucket") == "gave_up_early":
            probes.append(row)

    # Optional: tool sequences from DB
    turn_tools: dict[str, list[str]] = {}
    turn_ids = [str(p.get("turn_id")) for p in probes if p.get("turn_id")]
    if turn_ids:
        vals = ", ".join(f"('{t}')" for t in turn_ids)
        sql = f"""
SELECT e.turn_id::text || E'\\t' || COALESCE(e.payload->>'tool_name','')
FROM turn_events e
WHERE e.turn_id IN (SELECT turn_id::uuid FROM (VALUES {vals}) AS v(turn_id))
  AND e.type='tool.started'
ORDER BY e.turn_id, e.sequence;
"""
        raw = _pgsql(sql)
        if not raw.startswith("__error__"):
            for line in raw.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1]:
                    turn_tools.setdefault(parts[0], []).append(parts[1])

    classified = []
    counts: Counter[str] = Counter()
    for p in probes:
        tid = str(p.get("turn_id") or "")
        tools = turn_tools.get(tid) or []
        n_reads = int(p.get("n_reads") or 0)
        read_bytes = int(p.get("read_bytes") or 0)
        used_off = bool(p.get("used_next_offset"))
        cid = str(p.get("case_id") or "")

        # Heuristic classes per §10.3 CTX-4
        if "grep" in tools and n_reads <= 1 and not used_off:
            klass = "a_grep_miss_then_stop"
        elif n_reads <= 1 and not used_off and read_bytes == 0:
            # stats quirk OR answered without reading — treat as early stop
            klass = "b_single_read_no_continue"
        elif n_reads <= 1 and not used_off:
            klass = "b_single_read_no_continue"
        elif used_off or n_reads >= 2:
            klass = "c_continued_but_wrong_region"
        else:
            klass = "d_misbucket_or_wrong_answer"

        # narrativeqa + grep-first antagonism signal
        if "narrativeqa" in cid and klass.startswith("a_"):
            pass

        counts[klass] += 1
        classified.append(
            {
                "case_id": cid,
                "turn_id": tid,
                "n_reads": n_reads,
                "read_bytes": read_bytes,
                "used_next_offset": used_off,
                "tools": tools,
                "answer_len": p.get("answer_len"),
                "failure_class": klass,
            }
        )

    n = len(classified) or 1
    a_share = counts.get("a_grep_miss_then_stop", 0) / n
    return {
        "n_gave_up": len(classified),
        "class_counts": dict(counts),
        "class_share": {k: round(v / n, 3) for k, v in counts.items()},
        "grep_antagonism_share": round(a_share, 3),
        "open_ctx5": a_share >= (1 / 3),
        "cases": classified,
        "note": (
            "read_bytes=0 with n_reads≥1 is a known L2 extraction quirk "
            "(tool.completed result shape); tool sequences from turn_events "
            "are authoritative for (a)/(b)/(c)."
        ),
    }


def write_reports() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ret_dir = RUNS / RET_RUN
    ctx_dir = RUNS / CTX_RUN
    ret_result = _load_json(ret_dir / "result.json")
    ret_manifest = _load_json(ret_dir / "manifest.json")

    ret6 = _postgres_depth_from_db(ret_manifest)
    # Fallback: metrics-only aggregate if DB unavailable
    if not ret6.get("ok"):
        fallback_cases = []
        for c in ret_manifest.get("cases") or []:
            if str(c.get("case_id") or "").endswith(".agent"):
                continue
            if not isinstance(c.get("l2"), dict):
                continue
            row = dict(c)
            row["merged_len"] = int((c.get("metrics") or {}).get("n_hits") or 0)
            fallback_cases.append(row)
        ret6 = {
            "ok": False,
            "error": ret6.get("error"),
            "aggregate": depth_audit_aggregate(fallback_cases),
            "notes": {
                "fiqa_note": "DB unavailable; merged_len from metrics.n_hits only (no limit args)."
            },
        }

    ret8 = ret8_classify(ret_result)
    ctx4 = ctx4_classify(ctx_dir / "process.jsonl")

    payload = {
        "ret_run_id": RET_RUN,
        "ctx_run_id": CTX_RUN,
        "RET-6": ret6,
        "RET-8": {
            k: v for k, v in ret8.items() if k != "cases"
        },
        "CTX-4": {k: v for k, v in ctx4.items() if k != "cases"},
    }
    (OUT / "batch5_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "ret8_cases.json").write_text(
        json.dumps(ret8, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "ctx4_cases.json").write_text(
        json.dumps(ctx4, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fiqa_adj = (ret6.get("aggregate") or {}).get("fiqa_adjudication")
    md = f"""# Batch 5 offline outputs (§10)

Sources: retrieval `{RET_RUN}` · context `{CTX_RUN}`

## RET-6 · FiQA depth adjudication

- **fiqa_adjudication**: `{fiqa_adj}`
- Aggregate: see `batch5_summary.json` → RET-6.aggregate
- Note: {(ret6.get("notes") or {}).get("fiqa_note", "")}

| Result | Follow-up |
|--------|-----------|
| `pool_starvation_despite_limit` | Not model-limit; Index/embed + score≤0 filter → RET-4; RET-5 stays suspended |
| `shallow_limit_or_single_search` | Writing契约重申 limit≥30 |
| `depth_ok_relevance_or_qrels` | RET-4 / qrels structure |

## RET-8 · weak_hits classification (RET-4 ticket)

- n_cards: **{ret8["n_cards"]}**
- counts: `{ret8["class_counts"]}`
- share: `{ret8["class_share"]}`
- **embed_ticket_sufficient**: {ret8["embed_ticket_sufficient"]}
- verdict: {ret8["verdict"]}

## CTX-4 · gave_up_early anatomy

- n: **{ctx4["n_gave_up"]}**
- counts: `{ctx4["class_counts"]}`
- grep antagonism share: **{ctx4["grep_antagonism_share"]}**
- **open CTX-5**: {ctx4["open_ctx5"]}
- note: {ctx4["note"]}
"""
    (OUT / "BATCH5_REPORT.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    write_reports()
