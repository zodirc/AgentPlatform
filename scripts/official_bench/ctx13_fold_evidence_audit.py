#!/usr/bin/env python3
"""CTX-13 · Fold evidence-loss audit (offline observation · no runtime change).

Replays wrong_answer_after_read + truly_abandoned cases from free LongBench runs:
  gold evidence present in reconstructed raw tool bodies, but absent from the
  assembled model-visible window — classified into:

  (a) trunc_window_miss  — head budget truncation cut the evidence span
  (b) fold_budget_miss   — stale-path fold stub / non-latest 4k squeeze dropped it
  (c) pointer_lost       — evidence gone and no usable re-read pointer left

Writes eval/reports/official/batch15/ (gitignored reports tree).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.context_run import _normalize_v1 as _normalize  # noqa: E402
# CTX-13 evidence matching stays on v1 normalize so historical audits remain
# bit-stable; EVAL-8 scoring parity is orthogonal (score_prediction default=v2).

RUNS = ROOT / "eval/reports/official/runs"
OUT = ROOT / "eval/reports/official/batch15"
LONGBENCH_SLICE = ROOT / "eval/official/.local-data/longbench/small_slice.jsonl"

# Brief §7.7 anchors (fdd03298 may be absent on this host).
DEFAULT_RUNS = (
    "b5d24c9e-e010-4f44-951b-1b03882bb33e",  # CTX-8 N≥2 round 2
    "fdd03298",  # CTX-8 N≥2 round 1 — prefix match; often missing locally
    "1707135c-76c7-4cf7-8a86-3ba2f20dab5e",  # corroboration (CTX-9 era free)
)

TARGET_BUCKETS = frozenset({"wrong_answer_after_read", "truly_abandoned"})
DEFAULT_BUDGET = 4_000
LATEST_READ_BUDGET = 32_000
EVIDENCE_COVER_MIN = 0.45
STOP = frozenset(
    "a an the of to in on for and or is are was were be been being by with from as "
    "at it this that these those their its his her they them we you i not no yes "
    "do did does can could should would may might will".split()
)
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_DASHES = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\ufeff": "",
    }
)


@dataclass
class EvidenceSpan:
    start: int
    end: int
    score: float
    method: str
    gold: str
    text: str = ""


@dataclass
class CaseAudit:
    run_id: str
    case_id: str
    bucket: str
    turn_id: str
    primary: str
    golds: list[str] = field(default_factory=list)
    evidence_score: float = 0.0
    evidence_method: str = ""
    evidence_snip: str = ""
    gold_in_passage: bool = False
    evidence_in_any_raw: bool = False
    evidence_in_final_visible: bool = False
    had_budget_truncated: bool = False
    had_folded_stub: bool = False
    had_reable_pointer: bool = False
    n_reads: int = 0
    read_coverage: float = 0.0
    used_next_offset: bool = False
    notes: str = ""


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


def _docker_cat(path: str) -> str:
    try:
        proc = subprocess.run(
            ["docker", "exec", "agent-runtime", "cat", path],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def resolve_run_id(spec: str) -> str | None:
    """Resolve full run UUID from prefix or exact id."""
    spec = str(spec or "").strip()
    if not spec:
        return None
    exact = RUNS / spec
    if (exact / "manifest.json").is_file():
        return spec
    matches = sorted(
        p.name
        for p in RUNS.iterdir()
        if p.is_dir() and p.name.startswith(spec) and (p / "manifest.json").is_file()
    )
    return matches[0] if matches else None


def _canon(text: str) -> str:
    return _normalize(str(text or "").translate(_DASHES))


def load_longbench_rows(*, limit_per_task: int = 20) -> dict[str, dict[str, Any]]:
    """case_id → {golds, context, question} using the same idx as Ops L1 runner.

    Ops ``run_context_agent_path`` does ``enumerate(limit_rows_per_task(rows, limit))``,
    so ``longbench.{task}.{idx}`` uses the **global** enumerate index after the
    per-task cap — not the dataset-local idx. Matching that is required for
    hotpotqa.20+ / narrativeqa.40+ case ids.
    """
    from official_bench.l1_prompts import limit_rows_per_task

    out: dict[str, dict[str, Any]] = {}
    if not LONGBENCH_SLICE.is_file():
        return out
    rows: list[dict[str, Any]] = []
    for line in LONGBENCH_SLICE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    capped = limit_rows_per_task(rows, limit_per_task)
    for idx, row in enumerate(capped):
        task = str(row.get("task") or row.get("dataset") or "longbench")
        golds_raw = row.get("answers") or row.get("answer")
        if isinstance(golds_raw, str):
            golds = [golds_raw]
        elif isinstance(golds_raw, list):
            golds = [str(x) for x in golds_raw]
        else:
            golds = [str(golds_raw or "")]
        out[f"longbench.{task}.{idx}"] = {
            "golds": golds,
            "context": str(row.get("context") or ""),
            "question": str(row.get("question") or row.get("input") or ""),
        }
    return out


def load_longbench_golds(*, limit_per_task: int = 20) -> dict[str, list[str]]:
    return {
        cid: row["golds"]
        for cid, row in load_longbench_rows(limit_per_task=limit_per_task).items()
    }


def content_tokens(text: str) -> list[str]:
    return [
        t
        for t in _WORD.findall(_canon(text))
        if t not in STOP and len(t) > 1
    ]


def salient_terms(gold: str) -> list[str]:
    """Numbers + longer content tokens — better for abstractive LongBench golds."""
    canon = _canon(gold)
    nums = re.findall(r"\d+(?:[.:]\d+)*", canon)
    toks = [t for t in content_tokens(gold) if len(t) >= 3]
    # Prefer distinctive tokens (longer first).
    toks = sorted(set(toks), key=lambda t: (-len(t), t))
    out: list[str] = []
    for n in nums:
        if n not in out:
            out.append(n)
    for t in toks:
        if t not in out:
            out.append(t)
    return out[:12]


def gold_cover_ratio(gold: str, text: str) -> float:
    terms = salient_terms(gold)
    if not terms:
        ng = _canon(gold)
        return 1.0 if ng and ng in _canon(text) else 0.0
    ctext = _canon(text)
    hit = sum(1 for t in terms if t in ctext)
    return hit / len(terms)


def locate_evidence_span(passage: str, golds: list[str]) -> EvidenceSpan | None:
    """Best span in passage supporting any gold answer."""
    if not passage or not golds:
        return None
    best: EvidenceSpan | None = None
    pcanon = _canon(passage)
    # Map canonical index → original roughly via lowercased dash-normalized copy.
    passage_norm = passage.translate(_DASHES)
    plower = passage_norm.lower()

    for gold in golds:
        ng = _canon(gold)
        if len(ng) >= 6:
            needle = ng[: min(80, len(ng))]
            i = plower.find(needle)
            if i >= 0:
                end = min(len(passage_norm), i + max(len(gold), len(needle)) + 24)
                cand = EvidenceSpan(
                    start=i,
                    end=end,
                    score=1.0,
                    method="exact",
                    gold=gold,
                    text=passage_norm[i:end],
                )
                if best is None or cand.score > best.score:
                    best = cand
                continue

        terms = salient_terms(gold)
        if not terms:
            continue
        # Anchor on rarest/longest term, expand window.
        anchors = sorted(terms, key=lambda t: (-len(t), t))
        for anchor in anchors[:4]:
            start_at = 0
            while True:
                i = pcanon.find(anchor, start_at)
                if i < 0:
                    break
                # Expand ~120 chars each side in canonical space ≈ original.
                lo = max(0, i - 120)
                hi = min(len(passage_norm), i + len(anchor) + 160)
                chunk = passage_norm[lo:hi]
                score = gold_cover_ratio(gold, chunk)
                if score >= EVIDENCE_COVER_MIN:
                    cand = EvidenceSpan(
                        start=lo,
                        end=hi,
                        score=score,
                        method="anchor",
                        gold=gold,
                        text=chunk,
                    )
                    if best is None or cand.score > best.score:
                        best = cand
                start_at = i + max(1, len(anchor))
                if start_at > len(pcanon):
                    break

        # Short gold / entity-only: whole-passage cover as weak span.
        whole = gold_cover_ratio(gold, passage)
        if whole >= max(EVIDENCE_COVER_MIN, 0.6):
            # Tight span around first term hit.
            for anchor in anchors[:3]:
                i = plower.find(anchor)
                if i < 0:
                    continue
                lo = max(0, i - 40)
                hi = min(len(passage_norm), i + len(anchor) + 80)
                cand = EvidenceSpan(
                    start=lo,
                    end=hi,
                    score=whole,
                    method="entity",
                    gold=gold,
                    text=passage_norm[lo:hi],
                )
                if best is None or cand.score > best.score:
                    best = cand
                break
    return best


def evidence_in_text(span: EvidenceSpan | None, golds: list[str], text: str) -> bool:
    if not text:
        return False
    ctext = _canon(text)
    if span and span.score >= EVIDENCE_COVER_MIN:
        snip = _WS.sub(" ", span.text.strip())
        if len(snip) >= 8 and _canon(snip[:80]) in ctext:
            return True
        if gold_cover_ratio(span.text, text) >= EVIDENCE_COVER_MIN:
            return True
        if gold_cover_ratio(span.gold, text) >= EVIDENCE_COVER_MIN:
            return True
    for g in golds:
        if gold_cover_ratio(g, text) >= EVIDENCE_COVER_MIN:
            return True
        ng = _canon(g)
        if len(ng) >= 6 and ng in ctext:
            return True
    return False


def extract_tool_result_texts(messages: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            out.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                out.append(str(block))
                continue
            if block.get("type") == "tool_result":
                out.append(str(block.get("content") or ""))
            elif "text" in block:
                out.append(str(block.get("text") or ""))
            else:
                out.append(json.dumps(block, ensure_ascii=False))
    return out


def tool_payload_body(text: str) -> str:
    """Prefer JSON content field when tool_result is structured."""
    raw = str(text or "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Head-truncated JSON — best-effort extract "content":"..."
        m = re.search(r'"content"\s*:\s*"(.*)$', raw, re.DOTALL)
        if m:
            return m.group(1)
        return raw
    if isinstance(data, dict):
        body = data.get("content")
        if isinstance(body, str):
            return body
        if isinstance(data.get("matches"), list):
            return json.dumps(data.get("matches"), ensure_ascii=False)
    return raw


def has_folded_stub(text: str) -> bool:
    return "_folded_read" in text or "omitted; already read" in text.lower()


def has_budget_truncated_marker(text: str) -> bool:
    return "[budget_truncated]" in text or "budget_truncated" in text


def has_reread_pointer(texts: list[str]) -> bool:
    """Usable recovery pointer in visible tool bodies (path + offset/next_offset/hint)."""
    joined = "\n".join(texts)
    if "next_offset" in joined or "next_offset=" in joined.lower():
        return True
    if "续读" in joined or "continue with" in joined.lower():
        return True
    # Folded stub still names path + offset/end_line — weak pointer.
    for t in texts:
        if not has_folded_stub(t):
            continue
        try:
            data = json.loads(t)
        except json.JSONDecodeError:
            if '"path"' in t and ('"offset"' in t or '"next_offset"' in t):
                return True
            continue
        if isinstance(data, dict) and data.get("path"):
            if data.get("next_offset") is not None or data.get("offset") is not None:
                return True
    return False


def passage_path_for_case(run_id: str, case_id: str) -> str:
    parts = str(case_id).split(".")
    if len(parts) < 3:
        return ""
    task, idx = parts[1], parts[2]
    return f"/data/ops-l1/{run_id}/context/{task}_{idx}/sources/passage.md"


def load_envelopes(turn_id: str) -> list[tuple[int, list[dict[str, Any]]]]:
    sql = f"""
SELECT step_index::text || E'\\t' || envelope::text
FROM model_request_envelopes
WHERE turn_id = '{turn_id}'::uuid
ORDER BY step_index;
"""
    raw = _pgsql(sql)
    if raw.startswith("__error__"):
        return []
    out: list[tuple[int, list[dict[str, Any]]]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        si_s, _, rest = line.partition("\t")
        try:
            env = json.loads(rest)
        except json.JSONDecodeError:
            continue
        msgs = env.get("messages") if isinstance(env, dict) else None
        if isinstance(msgs, list):
            out.append((int(si_s), msgs))
    return out


def load_read_windows(turn_id: str) -> list[dict[str, Any]]:
    """tool.completed read_file windows (offset/end_line/path)."""
    sql = f"""
SELECT COALESCE(payload->>'path','') || E'\\t'
    || COALESCE(payload->>'offset','1') || E'\\t'
    || COALESCE(payload->>'end_line','') || E'\\t'
    || COALESCE(payload->>'chars_read','') || E'\\t'
    || COALESCE(payload->>'file_chars','') || E'\\t'
    || COALESCE(payload->>'next_offset','') || E'\\t'
    || COALESCE(payload->>'is_truncated', payload->>'truncated','')
FROM turn_events
WHERE turn_id = '{turn_id}'::uuid
  AND type = 'tool.completed'
  AND payload->>'tool_name' = 'read_file'
ORDER BY sequence;
"""
    raw = _pgsql(sql)
    if raw.startswith("__error__"):
        return []
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 7:
            parts.append("")
        path, off, end, chars, fchars, nxt, trunc = parts[:7]
        try:
            offset = int(off or "1")
        except ValueError:
            offset = 1
        try:
            end_line = int(end) if end else None
        except ValueError:
            end_line = None
        out.append(
            {
                "path": path,
                "offset": offset,
                "end_line": end_line,
                "chars_read": int(chars) if chars.isdigit() else None,
                "file_chars": int(fchars) if fchars.isdigit() else None,
                "next_offset": int(nxt) if nxt.isdigit() else None,
                "truncated": str(trunc).lower() in {"1", "true", "t", "yes"},
            }
        )
    return out


def reconstruct_raw_reads(passage: str, windows: list[dict[str, Any]]) -> list[str]:
    """Rebuild pre-budget read bodies from passage line windows."""
    if not passage:
        return []
    lines = passage.splitlines(keepends=True)
    if not lines:
        return [passage] if windows else []
    bodies: list[str] = []
    for w in windows:
        start = max(1, int(w.get("offset") or 1)) - 1
        end_line = w.get("end_line")
        if end_line is None:
            # Fallback: approximate by chars_read from start.
            chars = int(w.get("chars_read") or 0)
            chunk = "".join(lines[start:])
            bodies.append(chunk[: chars or len(chunk)])
            continue
        end = max(start, int(end_line))
        bodies.append("".join(lines[start:end]))
    return bodies


def simulate_budget_head(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[budget_truncated]"


def classify_case(
    *,
    run_id: str,
    case: dict[str, Any],
    golds: list[str],
    passage: str,
    envelopes: list[tuple[int, list[dict[str, Any]]]],
    read_windows: list[dict[str, Any]],
) -> CaseAudit:
    cid = str(case.get("case_id") or "")
    turn_id = str(case.get("turn_id") or "")
    bucket = str(case.get("bucket") or "")
    audit = CaseAudit(
        run_id=run_id,
        case_id=cid,
        bucket=bucket,
        turn_id=turn_id,
        primary="inconclusive",
        golds=[g[:120] for g in golds[:3]],
        n_reads=int(case.get("n_reads") or 0),
        read_coverage=float(case.get("read_coverage") or 0.0),
        used_next_offset=bool(case.get("used_next_offset")),
    )

    span = locate_evidence_span(passage, golds)
    if span is None or span.score < EVIDENCE_COVER_MIN:
        audit.primary = "gold_not_localizable"
        audit.notes = "cannot locate gold evidence span in passage"
        return audit

    audit.evidence_score = round(span.score, 3)
    audit.evidence_method = span.method
    audit.evidence_snip = _WS.sub(" ", span.text)[:160]
    audit.gold_in_passage = True

    raw_bodies = reconstruct_raw_reads(passage, read_windows)
    if not raw_bodies and passage:
        # No completed read windows — still allow whole-passage check for abandoned.
        raw_bodies = []

    evidence_in_raw = any(evidence_in_text(span, golds, b) for b in raw_bodies)
    # Also: span char range overlaps any reconstructed body via passage index.
    if not evidence_in_raw and raw_bodies and passage:
        for w, body in zip(read_windows, raw_bodies):
            # If span text appears in body
            if evidence_in_text(span, golds, body):
                evidence_in_raw = True
                break
            # Char-range overlap approximation using line offsets
            start = max(1, int(w.get("offset") or 1)) - 1
            lines = passage.splitlines(keepends=True)
            if not lines:
                continue
            prefix = sum(len(x) for x in lines[:start])
            end_line = w.get("end_line")
            if end_line is None:
                end_pos = prefix + len(body)
            else:
                end_pos = sum(len(x) for x in lines[: max(start, int(end_line))])
            if span.start < end_pos and span.end > prefix:
                evidence_in_raw = True
                break
    audit.evidence_in_any_raw = evidence_in_raw

    if not envelopes:
        audit.primary = "no_envelope"
        audit.notes = "model_request_envelopes missing for turn"
        return audit

    final_msgs = envelopes[-1][1]
    final_texts = extract_tool_result_texts(final_msgs)
    final_joined = "\n".join(final_texts)
    final_bodies = [tool_payload_body(t) for t in final_texts]
    audit.had_budget_truncated = any(has_budget_truncated_marker(t) for t in final_texts)
    audit.had_folded_stub = any(has_folded_stub(t) for t in final_texts)
    audit.had_reable_pointer = has_reread_pointer(final_texts)
    audit.evidence_in_final_visible = evidence_in_text(
        span, golds, "\n".join(final_bodies + [final_joined])
    )

    # Ever visible in any envelope step?
    ever_visible = False
    for _, msgs in envelopes:
        texts = extract_tool_result_texts(msgs)
        bodies = [tool_payload_body(t) for t in texts]
        if evidence_in_text(span, golds, "\n".join(bodies + texts)):
            ever_visible = True
            break

    if audit.evidence_in_final_visible:
        audit.primary = "not_assembly_loss"
        audit.notes = "evidence still in final model-visible tool bodies (reason/ability)"
        return audit

    if not evidence_in_raw and not ever_visible:
        audit.primary = "never_retrieved"
        audit.notes = "evidence span never entered a read window / tool_result"
        return audit

    # (a) trunc_window_miss: latest raw read held evidence; head budget drops it.
    if raw_bodies:
        latest_raw = raw_bodies[-1]
        latest_in_raw = evidence_in_text(span, golds, latest_raw)
        # Simulate assemble budget on a JSON-ish wrapper similar to production.
        wrapped = json.dumps(
            {
                "path": "sources/passage.md",
                "content": latest_raw,
                "offset": (read_windows[-1].get("offset") if read_windows else 1),
            },
            ensure_ascii=False,
        )
        kept = simulate_budget_head(wrapped, LATEST_READ_BUDGET)
        kept_body = tool_payload_body(kept)
        if latest_in_raw and not evidence_in_text(span, golds, kept_body + kept):
            audit.primary = "trunc_window_miss"
            audit.notes = "latest read held evidence; 32k head budget drops it"
            return audit
        # Non-latest 4k squeeze (fold_budget path) — if multi-read and earlier held it.
        if len(raw_bodies) >= 2:
            for body in raw_bodies[:-1]:
                if not evidence_in_text(span, golds, body):
                    continue
                wrapped_old = json.dumps(
                    {"path": "sources/passage.md", "content": body},
                    ensure_ascii=False,
                )
                kept_old = simulate_budget_head(wrapped_old, DEFAULT_BUDGET)
                if not evidence_in_text(span, golds, tool_payload_body(kept_old) + kept_old):
                    if audit.had_folded_stub or audit.had_budget_truncated:
                        audit.primary = "fold_budget_miss"
                        audit.notes = (
                            "earlier read held evidence; fold stub / 4k budget squeezed it out"
                        )
                        return audit

    # Visible markers: truncated window without evidence.
    if audit.had_budget_truncated and evidence_in_raw and not audit.evidence_in_final_visible:
        # Distinguish fold vs trunc: folded stub present → prefer fold_budget_miss
        if audit.had_folded_stub and audit.n_reads >= 2:
            audit.primary = "fold_budget_miss"
            audit.notes = "multi-read with folded stub; evidence absent from final window"
            return audit
        audit.primary = "trunc_window_miss"
        audit.notes = "budget_truncated in final window; evidence absent"
        return audit

    if audit.had_folded_stub and evidence_in_raw and not audit.evidence_in_final_visible:
        audit.primary = "fold_budget_miss"
        audit.notes = "folded stub present; evidence absent from final window"
        return audit

    # (c) pointer_lost: had evidence earlier / in raw, gone now, no recovery pointer.
    if (evidence_in_raw or ever_visible) and not audit.evidence_in_final_visible:
        if not audit.had_reable_pointer:
            audit.primary = "pointer_lost"
            audit.notes = "evidence lost from window with no usable re-read pointer"
            return audit
        audit.primary = "pointer_present_but_unused"
        audit.notes = "pointer remains but model did not recover evidence before answering"
        return audit

    audit.primary = "inconclusive"
    audit.notes = "could not attribute assembly loss mode"
    return audit


def load_passage(run_id: str, case_id: str, rows: dict[str, dict[str, Any]]) -> str:
    """Prefer slice context (local, complete); fall back to workspace passage.md."""
    row = rows.get(case_id) or {}
    ctx = str(row.get("context") or "")
    if len(ctx) >= 40:
        return ctx
    return _docker_cat(passage_path_for_case(run_id, case_id))


def _run_limit(run_id: str) -> int:
    manifest = _load_json(RUNS / run_id / "manifest.json")
    sp = manifest.get("sample_policy")
    if isinstance(sp, dict) and sp.get("limit"):
        try:
            return int(sp["limit"])
        except (TypeError, ValueError):
            pass
    return 20


def audit_run(run_id: str, rows: dict[str, dict[str, Any]] | None = None) -> list[CaseAudit]:
    if rows is None:
        rows = load_longbench_rows(limit_per_task=_run_limit(run_id))
    manifest = _load_json(RUNS / run_id / "manifest.json")
    cases = [
        c
        for c in (manifest.get("cases") or [])
        if isinstance(c, dict) and c.get("bucket") in TARGET_BUCKETS and c.get("turn_id")
    ]
    out: list[CaseAudit] = []
    for case in cases:
        cid = str(case.get("case_id") or "")
        turn_id = str(case.get("turn_id") or "")
        golds = list((rows.get(cid) or {}).get("golds") or [])
        passage = load_passage(run_id, cid, rows)
        envelopes = load_envelopes(turn_id)
        windows = load_read_windows(turn_id)
        out.append(
            classify_case(
                run_id=run_id,
                case=case,
                golds=golds,
                passage=passage,
                envelopes=envelopes,
                read_windows=windows,
            )
        )
    return out


def summarize(audits: list[CaseAudit]) -> dict[str, Any]:
    counts = Counter(a.primary for a in audits)
    wa = [a for a in audits if a.bucket == "wrong_answer_after_read"]
    assembly_keys = ("trunc_window_miss", "fold_budget_miss", "pointer_lost")
    assembly_n = sum(counts[k] for k in assembly_keys)
    wa_n = len(wa) or 1
    assembly_wa = sum(1 for a in wa if a.primary in assembly_keys)
    # Verdict per brief §7.7
    trunc = counts["trunc_window_miss"]
    fold = counts["fold_budget_miss"]
    ptr = counts["pointer_lost"]
    if assembly_n == 0 or assembly_wa / max(len(wa), 1) < (1 / 3):
        first_knife = "none_capability_wall"
        rule = "assembly exposure < 1/3 wrong_answer → degrade CTX-14/15/6 to open=false"
    else:
        ranked = sorted(
            [
                ("trunc_window_miss", trunc, "CTX-14"),
                ("fold_budget_miss", fold, "CTX-6"),
                ("pointer_lost", ptr, "CTX-15"),
            ],
            key=lambda x: (-x[1], x[0]),
        )
        top = ranked[0]
        first_knife = top[2] if top[1] > 0 else "none_capability_wall"
        rule = f"dominant bucket {top[0]}={top[1]} → first knife {first_knife}"

    return {
        "n_cases": len(audits),
        "n_wrong_answer": len(wa),
        "n_abandoned": sum(1 for a in audits if a.bucket == "truly_abandoned"),
        "primary_counts": dict(counts),
        "assembly_loss_n": assembly_n,
        "assembly_loss_share_of_wrong_answer": round(assembly_wa / wa_n, 3),
        "trunc_window_miss": trunc,
        "fold_budget_miss": fold,
        "pointer_lost": ptr,
        "first_knife": first_knife,
        "verdict_line": (
            f"trunc_window_miss = {trunc} · fold_budget_miss = {fold} · "
            f"pointer_lost = {ptr} → 首刀 = {first_knife}"
        ),
        "rule": rule,
    }


def write_reports(run_specs: list[str] | None = None) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    specs = list(run_specs or DEFAULT_RUNS)
    resolved: list[str] = []
    missing: list[str] = []
    for spec in specs:
        rid = resolve_run_id(spec)
        if rid:
            resolved.append(rid)
        else:
            missing.append(spec)

    all_audits: list[CaseAudit] = []
    per_run: dict[str, Any] = {}
    for rid in resolved:
        audits = audit_run(rid)
        all_audits.extend(audits)
        per_run[rid] = summarize(audits)

    summary = summarize(all_audits) if all_audits else {
        "n_cases": 0,
        "primary_counts": {},
        "verdict_line": "trunc_window_miss = 0 · fold_budget_miss = 0 · pointer_lost = 0 → 首刀 = none",
        "first_knife": "none",
        "rule": "no cases audited",
    }
    payload = {
        "ticket": "CTX-13",
        "runs_requested": specs,
        "runs_resolved": resolved,
        "runs_missing": missing,
        "per_run": per_run,
        "summary": summary,
        "cases": [asdict(a) for a in all_audits],
    }
    (OUT / "ctx13_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "ctx13_cases.json").write_text(
        json.dumps({"cases": payload["cases"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# CTX-13 · Fold evidence-loss audit",
        "",
        f"- runs resolved: {', '.join(f'`{r}`' for r in resolved) or '(none)'}",
        f"- runs missing: {', '.join(f'`{m}`' for m in missing) or '(none)'}",
        "",
        "## Verdict",
        "",
        f"`{summary.get('verdict_line')}`",
        "",
        f"- rule: {summary.get('rule')}",
        f"- assembly_loss_share_of_wrong_answer: "
        f"{summary.get('assembly_loss_share_of_wrong_answer')}",
        "",
        "## Primary counts",
        "",
        "```json",
        json.dumps(summary.get("primary_counts") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Per-run",
        "",
        "```json",
        json.dumps(per_run, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    (OUT / "ctx13_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--run",
        action="append",
        dest="runs",
        help="Run id or prefix (repeatable). Default: brief CTX-8 anchors.",
    )
    args = ap.parse_args()
    payload = write_reports(args.runs)
    print(json.dumps({k: payload[k] for k in ("runs_resolved", "runs_missing", "summary")}, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
