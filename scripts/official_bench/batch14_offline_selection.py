#!/usr/bin/env python3
"""§14 offline: RET-4 embed candidate selection (L0) + RET-19 CE rerank residual.

L0 numbers are hypothesis-only — never write into SCORECARD / free main column.
Writes under eval/reports/official/batch14/ (gitignored).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.agent_path_extract import (  # noqa: E402
    doc_id_from_path,
    merge_retrieval_rankings,
)
from official_bench.metrics_ir import ndcg_at_k, recall_at_k  # noqa: E402

RUNS = ROOT / "eval/reports/official/runs"
OUT = ROOT / "eval/reports/official/batch14"
BEIR_ROOT = ROOT / "eval/official/.local-data/beir"

# Smoke query ids: taken from a recent free retrieval run's cases (head_slice).
DEFAULT_SMOKE_RUN = "03569f22"
DATASETS = ("scifact", "nfcorpus", "fiqa")

# 384-d candidates (same ANN dim as MiniLM) — selection only.
CANDIDATES = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
    "thenlper/gte-small",
]
# Small CE for residual estimate (not production hot-path).
RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _hf_snapshot(model_id: str) -> str:
    """Resolve Hub id → local snapshot path under HF_HOME (offline-safe)."""
    hf_home = Path(os.environ.get("HF_HOME") or "/data/models")
    # models--org--name/snapshots/<rev>
    safe = "models--" + model_id.replace("/", "--")
    snaps = hf_home / safe / "snapshots"
    if snaps.is_dir():
        revs = sorted(p for p in snaps.iterdir() if p.is_dir())
        if revs:
            return str(revs[-1])
    # Already a filesystem path?
    if Path(model_id).is_dir():
        return model_id
    return model_id  # let ST try Hub / cache lookup


def _resolve_device() -> str:
    """Prefer CUDA when a usable GPU build is present (e.g. RTX 5080 + cu128)."""
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            print(
                f"[device] cuda=True torch={torch.__version__} gpu={name}",
                flush=True,
            )
            return "cuda"
        print(f"[device] cuda=False torch={torch.__version__}", flush=True)
    except Exception as exc:  # noqa: BLE001 — best-effort probe
        print(f"[device] torch probe failed: {exc}", flush=True)
    return "cpu"


def _load_st_model(model_id: str) -> Any:
    from sentence_transformers import SentenceTransformer

    local = _hf_snapshot(model_id)
    device = _resolve_device()
    print(f"[embed] load {model_id} → {local} device={device}", flush=True)
    try:
        return SentenceTransformer(local, device=device, local_files_only=True)
    except Exception:
        return SentenceTransformer(local, device=device)


def _load_ce_model(model_id: str) -> Any:
    from sentence_transformers import CrossEncoder

    local = _hf_snapshot(model_id)
    device = _resolve_device()
    print(f"[ce] load {model_id} → {local} device={device}", flush=True)
    try:
        return CrossEncoder(local, device=device, local_files_only=True)
    except TypeError:
        # older ST may not accept local_files_only
        return CrossEncoder(local, device=device)
    except Exception:
        return CrossEncoder(local, device=device)


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
    """Prefer TCP via psycopg (in-container); fall back to docker exec on host."""
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("AGENT_DATABASE_URL")
    if dsn:
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    rows = cur.fetchall()
            return "\n".join(
                "\t".join("" if c is None else str(c) for c in row) for row in rows
            )
        except Exception as exc:  # noqa: BLE001 — fall through to docker
            print(f"[pgsql] psycopg failed: {exc}; trying docker exec", flush=True)
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


def _load_qrels(dataset: str) -> dict[str, dict[str, int]]:
    path = BEIR_ROOT / dataset / "qrels" / "test.tsv"
    out: dict[str, dict[str, int]] = defaultdict(dict)
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
            rel = int(float(parts[2])) if len(parts) >= 3 else 1
        except ValueError:
            rel = 1
        if rel > 0:
            out[qid][str(doc_id)] = rel
    return dict(out)


def _load_corpus(dataset: str) -> dict[str, str]:
    path = BEIR_ROOT / dataset / "corpus.jsonl"
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        doc_id = str(row.get("_id") or row.get("id") or "")
        title = str(row.get("title") or "").strip()
        text = str(row.get("text") or "").strip()
        out[doc_id] = f"{title}\n{text}".strip() if title else text
    return out


def _load_queries(dataset: str) -> dict[str, str]:
    path = BEIR_ROOT / dataset / "queries.jsonl"
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[str(row.get("_id") or row.get("id"))] = str(row.get("text") or "")
    return out


def _qid_from_case_id(case_id: str) -> tuple[str, str] | None:
    m = re.match(r"beir\.(scifact|nfcorpus|fiqa)\.q-(.+)$", str(case_id or ""))
    if not m:
        return None
    return m.group(1), m.group(2)


def smoke_qids_from_run(run_prefix: str) -> dict[str, list[str]]:
    path = _resolve_run(run_prefix)
    if path is None:
        raise SystemExit(f"smoke run not found: {run_prefix}")
    manifest = _load_json(path / "manifest.json")
    by_ds: dict[str, list[str]] = defaultdict(list)
    for c in manifest.get("cases") or []:
        if not isinstance(c, dict):
            continue
        parsed = _qid_from_case_id(str(c.get("case_id") or ""))
        if not parsed:
            continue
        ds, qid = parsed
        by_ds[ds].append(qid)
    return {ds: qids for ds, qids in by_ds.items()}


def _encode_texts(model: Any, texts: list[str], *, batch_size: int = 256) -> Any:
    import numpy as np

    vecs = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return np.asarray(vecs, dtype="float32")


def _prefix_for_model(model_id: str, *, kind: str, text: str) -> str:
    """e5-family needs query:/passage: prefixes; others pass-through."""
    mid = model_id.lower()
    if "e5" in mid:
        return f"{'query' if kind == 'query' else 'passage'}: {text}"
    return text


def ret4_select(
    *,
    smoke_run: str,
    models: list[str],
    top_k: int = 100,
) -> dict[str, Any]:
    smoke = smoke_qids_from_run(smoke_run)
    report: dict[str, Any] = {
        "kind": "RET-4_L0_selection",
        "smoke_run": smoke_run,
        "smoke_qids": {ds: len(v) for ds, v in smoke.items()},
        "discipline": "L0 hypothesis only — not free main column / not SCORECARD",
        "models": {},
    }
    # Cache corpus/queries/qrels once.
    corpora = {ds: _load_corpus(ds) for ds in DATASETS}
    queries_all = {ds: _load_queries(ds) for ds in DATASETS}
    qrels_all = {ds: _load_qrels(ds) for ds in DATASETS}

    for model_id in models:
        print(f"[RET-4] loading {model_id}", flush=True)
        model = _load_st_model(model_id)
        per_ds: dict[str, Any] = {}
        macro_ndcg: list[float] = []
        for ds in DATASETS:
            qids = smoke.get(ds) or []
            if not qids:
                continue
            corpus = corpora[ds]
            doc_ids = list(corpus.keys())
            doc_texts = [
                _prefix_for_model(model_id, kind="passage", text=corpus[d]) for d in doc_ids
            ]
            print(f"[RET-4] {model_id} embed {ds} corpus n={len(doc_ids)}", flush=True)
            doc_vecs = _encode_texts(model, doc_texts)
            q_texts = [
                _prefix_for_model(
                    model_id,
                    kind="query",
                    text=queries_all[ds].get(qid, ""),
                )
                for qid in qids
            ]
            q_vecs = _encode_texts(model, q_texts)
            results: dict[str, dict[str, float]] = {}
            for qi, qid in enumerate(qids):
                scores = doc_vecs @ q_vecs[qi]
                # top_k via argpartition
                if len(scores) > top_k:
                    idx = scores.argpartition(-top_k)[-top_k:]
                    idx = idx[scores[idx].argsort()[::-1]]
                else:
                    idx = scores.argsort()[::-1]
                results[qid] = {doc_ids[j]: float(scores[j]) for j in idx}
            # Restrict qrels to smoke qids for macro over smoke only.
            qrels = {qid: qrels_all[ds].get(qid, {}) for qid in qids}
            ndcg10 = ndcg_at_k(qrels, results, 10)
            r10 = recall_at_k(qrels, results, 10)
            r100 = recall_at_k(qrels, results, 100)
            # absent @100: gold never in top100
            absent = 0
            for qid in qids:
                gold = {d for d, rel in (qrels.get(qid) or {}).items() if rel > 0}
                if not gold:
                    continue
                hit = set((results.get(qid) or {}).keys()) & gold
                if not hit:
                    absent += 1
            per_ds[ds] = {
                "n": len(qids),
                "ndcg_at_10": round(ndcg10, 4),
                "recall_at_10": round(r10, 4),
                "recall_at_100": round(r100, 4),
                "absent_at_100": absent,
            }
            macro_ndcg.append(ndcg10)
            print(f"[RET-4] {model_id} {ds} nDCG@10={ndcg10:.4f} absent@100={absent}", flush=True)
        report["models"][model_id] = {
            "by_dataset": per_ds,
            "macro_ndcg_at_10": round(sum(macro_ndcg) / len(macro_ndcg), 4) if macro_ndcg else 0.0,
        }
        # Free memory between models.
        del model
    # Ranking
    ranked = sorted(
        report["models"].items(),
        key=lambda kv: kv[1]["macro_ndcg_at_10"],
        reverse=True,
    )
    report["ranking"] = [
        {"model": mid, "macro_ndcg_at_10": payload["macro_ndcg_at_10"]} for mid, payload in ranked
    ]
    if ranked:
        best_id, best_payload = ranked[0]
        base = report["models"].get(CANDIDATES[0], {})
        report["recommendation"] = {
            "selected": best_id,
            "macro_ndcg_at_10": best_payload["macro_ndcg_at_10"],
            "delta_vs_minilm": round(
                best_payload["macro_ndcg_at_10"] - float(base.get("macro_ndcg_at_10") or 0.0),
                4,
            ),
            "note": "Pick for INDEX_VERSION=9 shadow re-embed; free N≥2 still required",
        }
    return report


def _ranked_from_db(manifest: dict[str, Any]) -> dict[str, list[str]]:
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


def _load_ranked_dump(path: Path) -> dict[str, list[str]]:
    """turn_id → ranked doc ids from pre-dumped JSON (host postgres export)."""
    payload = _load_json(path)
    out: dict[str, list[str]] = {}
    for c in payload.get("cases") or []:
        if not isinstance(c, dict):
            continue
        tid = str(c.get("turn_id") or "")
        ranked = c.get("ranked") or []
        if tid and isinstance(ranked, list):
            out[tid] = [str(x) for x in ranked]
    return out


def ret19_rerank_residual(
    *,
    run_prefixes: list[str],
    pool: int = 50,
    reranker_id: str = RERANKER,
    ranked_dumps: dict[str, Path] | None = None,
) -> dict[str, Any]:
    print(f"[RET-19] loading {reranker_id}", flush=True)
    ce = _load_ce_model(reranker_id)
    corpora = {ds: _load_corpus(ds) for ds in DATASETS}
    qrels_all = {ds: _load_qrels(ds) for ds in DATASETS}
    queries_all = {ds: _load_queries(ds) for ds in DATASETS}
    runs_out: list[dict[str, Any]] = []

    for pref in run_prefixes:
        path = _resolve_run(pref)
        if path is None:
            runs_out.append({"run_prefix": pref, "ok": False, "error": "not_found"})
            continue
        manifest = _load_json(path / "manifest.json")
        ranked_by_turn: dict[str, list[str]] = {}
        dump = (ranked_dumps or {}).get(pref) or (ranked_dumps or {}).get(path.name[:8])
        if dump and Path(dump).is_file():
            ranked_by_turn = _load_ranked_dump(Path(dump))
            print(f"[RET-19] using ranked dump {dump} n={len(ranked_by_turn)}", flush=True)
        else:
            ranked_by_turn = _ranked_from_db(manifest)
        if not ranked_by_turn:
            runs_out.append({"run_prefix": pref, "ok": False, "error": "no_db_ranked"})
            continue
        base_results: dict[str, dict[str, float]] = {}
        ce_results: dict[str, dict[str, float]] = {}
        qrels_smoke: dict[str, dict[str, int]] = {}
        n_pairs = 0
        for c in manifest.get("cases") or []:
            if not isinstance(c, dict):
                continue
            parsed = _qid_from_case_id(str(c.get("case_id") or ""))
            if not parsed:
                continue
            ds, qid = parsed
            tid = str(c.get("turn_id") or "")
            ranked = (ranked_by_turn.get(tid) or [])[:pool]
            if not ranked:
                continue
            qrels_smoke[qid] = qrels_all[ds].get(qid, {})
            # Original order as descending scores.
            base_results[qid] = {doc_id: float(pool - i) for i, doc_id in enumerate(ranked)}
            qtext = queries_all[ds].get(qid, "")
            pairs = []
            valid_docs = []
            for doc_id in ranked:
                body = corpora[ds].get(doc_id)
                if body is None:
                    continue
                pairs.append([qtext, body[:2000]])
                valid_docs.append(doc_id)
            if not pairs:
                continue
            scores = ce.predict(pairs, batch_size=32, show_progress_bar=False)
            ce_results[qid] = {
                doc_id: float(scores[i]) for i, doc_id in enumerate(valid_docs)
            }
            n_pairs += len(pairs)
        base_ndcg = ndcg_at_k(qrels_smoke, base_results, 10)
        ce_ndcg = ndcg_at_k(qrels_smoke, ce_results, 10)
        delta = ce_ndcg - base_ndcg
        # Per-dataset
        by_ds: dict[str, Any] = {}
        for ds in DATASETS:
            ds_qids = [
                qid
                for qid in qrels_smoke
                if any(
                    _qid_from_case_id(str(c.get("case_id") or "")) == (ds, qid)
                    for c in (manifest.get("cases") or [])
                    if isinstance(c, dict)
                )
            ]
            # simpler: from case list
            ds_qids = []
            for c in manifest.get("cases") or []:
                if not isinstance(c, dict):
                    continue
                parsed = _qid_from_case_id(str(c.get("case_id") or ""))
                if parsed and parsed[0] == ds and parsed[1] in qrels_smoke:
                    ds_qids.append(parsed[1])
            if not ds_qids:
                continue
            qr = {qid: qrels_smoke[qid] for qid in ds_qids}
            br = {qid: base_results[qid] for qid in ds_qids if qid in base_results}
            cr = {qid: ce_results[qid] for qid in ds_qids if qid in ce_results}
            b = ndcg_at_k(qr, br, 10)
            r = ndcg_at_k(qr, cr, 10)
            by_ds[ds] = {
                "n": len(ds_qids),
                "base_ndcg_at_10": round(b, 4),
                "ce_ndcg_at_10": round(r, 4),
                "delta": round(r - b, 4),
            }
        verdict = (
            "worth_budget_ticket"
            if delta >= 0.03
            else ("close_rerank_topic" if delta < 0.02 else "borderline")
        )
        runs_out.append(
            {
                "run_prefix": pref,
                "run_id": path.name,
                "ok": True,
                "reranker": reranker_id,
                "pool": pool,
                "n_pairs": n_pairs,
                "base_ndcg_at_10": round(base_ndcg, 4),
                "ce_ndcg_at_10": round(ce_ndcg, 4),
                "delta_pp": round(delta * 100, 2),
                "delta": round(delta, 4),
                "by_dataset": by_ds,
                "verdict": verdict,
            }
        )
        print(
            f"[RET-19] {pref[:8]} base={base_ndcg:.4f} ce={ce_ndcg:.4f} "
            f"Δ={delta*100:.2f}pp → {verdict}",
            flush=True,
        )
    deltas = [r["delta"] for r in runs_out if r.get("ok")]
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    return {
        "kind": "RET-19_offline_rerank_residual",
        "reranker": reranker_id,
        "runs": runs_out,
        "mean_delta": round(mean_delta, 4),
        "mean_delta_pp": round(mean_delta * 100, 2),
        "adjudication": (
            "worth_budget_ticket"
            if mean_delta >= 0.03
            else ("close_rerank_topic" if mean_delta < 0.02 else "borderline")
        ),
        "discipline": "offline residual only — do not enable CE on hot path from this alone",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ret4", action="store_true", help="Run RET-4 L0 selection")
    ap.add_argument("--ret19", action="store_true", help="Run RET-19 CE residual")
    ap.add_argument("--smoke-run", default=DEFAULT_SMOKE_RUN)
    ap.add_argument("--ret19-run", action="append", default=None)
    ap.add_argument(
        "--ranked-dump",
        action="append",
        default=None,
        help="prefix=path.json for pre-exported ranked lists",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Encode batch size (0 = auto: 1024 on CUDA, 256 on CPU)",
    )
    ap.add_argument("--model", action="append", default=None, help="Override RET-4 models")
    ap.add_argument("--reranker", default=RERANKER)
    args = ap.parse_args()
    if not args.ret4 and not args.ret19:
        args.ret4 = True
        args.ret19 = True
    if args.batch_size <= 0:
        try:
            import torch

            args.batch_size = 1024 if torch.cuda.is_available() else 256
        except Exception:  # noqa: BLE001
            args.batch_size = 256
    print(f"[cli] batch_size={args.batch_size}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    # Allow downloads when running under make/host; container often has HF_HUB_OFFLINE=1.
    os.environ.setdefault("HF_HOME", os.environ.get("HF_HOME") or "/data/models")
    # Speed up CPU encode a bit.
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")

    summary: dict[str, Any] = {}
    if args.ret4:
        models = args.model or CANDIDATES
        # Monkey-patch batch size into encode helper via closure default override.
        global _encode_texts  # noqa: PLW0603 — intentional for CLI knob

        def _encode_texts(model: Any, texts: list[str], *, batch_size: int = args.batch_size) -> Any:  # type: ignore[no-redef]
            import numpy as np

            vecs = model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=True,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return np.asarray(vecs, dtype="float32")

        ret4 = ret4_select(smoke_run=args.smoke_run, models=models)
        summary["RET-4"] = ret4
        (OUT / "ret4_selection.json").write_text(
            json.dumps(ret4, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.ret19:
        runs = args.ret19_run or ["03304987", "03569f22"]
        ranked_dumps: dict[str, Path] = {}
        for item in args.ranked_dump or []:
            if "=" not in item:
                continue
            pref, pth = item.split("=", 1)
            ranked_dumps[pref] = Path(pth)
        # Auto-discover dumps in OUT if not passed.
        if not ranked_dumps:
            for pref in runs:
                cand = OUT / f"ranked_{pref[:8]}.json"
                if cand.is_file():
                    ranked_dumps[pref] = cand
        ret19 = ret19_rerank_residual(
            run_prefixes=runs,
            reranker_id=args.reranker,
            ranked_dumps=ranked_dumps,
        )
        summary["RET-19"] = ret19
        (OUT / "ret19_rerank.json").write_text(
            json.dumps(ret19, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (OUT / "batch14_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
