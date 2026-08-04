"""Pure helpers: extract L1 scores from product turn_events (no I/O)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_DOC_ID_RE = re.compile(r"([^/\\]+?)(?:\.[A-Za-z0-9]+)?$")
_CHARS_READ_HINT_RE = re.compile(r"已读\s+(\d+)\s*/\s*共\s+(\d+)\s*字符")
_LINES_SUMMARY_RE = re.compile(
    r"Read\s+.+\s+lines\s+(\d+)[–-](\d+)/(\d+)",
    re.IGNORECASE,
)


def doc_id_from_path(path: str) -> str:
    """Map materialised ``sources/<doc_id>.txt`` (or nested) back to a BEIR doc id."""
    name = Path(path or "").name
    if not name:
        return ""
    if name.endswith(".txt"):
        return name[: -len(".txt")]
    m = _DOC_ID_RE.search(name)
    return m.group(1) if m else name


def ranked_doc_ids_from_retrieval_payload(payload: dict[str, Any]) -> list[str]:
    """Prefer ``ranked`` (≤100 path+score), else ``hits``, else audit.ranked."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        doc_id = doc_id_from_path(path)
        if not doc_id or doc_id in seen:
            return
        seen.add(doc_id)
        ordered.append(doc_id)

    for key in ("ranked", "hits"):
        blob = payload.get(key)
        if not isinstance(blob, list):
            continue
        for hit in blob:
            if isinstance(hit, dict):
                _add(str(hit.get("path") or ""))
        if ordered:
            return ordered

    audit = payload.get("audit")
    if isinstance(audit, dict):
        for key in ("ranked", "entered_context", "recall_pool"):
            blob = audit.get(key)
            if not isinstance(blob, list):
                continue
            for hit in blob:
                if isinstance(hit, dict):
                    _add(str(hit.get("path") or ""))
            if ordered:
                return ordered
    return ordered


def merge_retrieval_rankings(events: list[dict[str, Any]]) -> list[str]:
    """Merge all retrieval.completed events (first-seen doc wins for RRF-like union)."""
    merged: list[str] = []
    seen: set[str] = set()
    for ev in events:
        if str(ev.get("type") or "") != "retrieval.completed":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        for doc_id in ranked_doc_ids_from_retrieval_payload(payload):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            merged.append(doc_id)
    return merged


def ranking_scores(doc_ids: list[str], *, limit: int = 100) -> dict[str, float]:
    """Convert ranked ids to {doc_id: score} with higher=better for metrics_ir."""
    out: dict[str, float] = {}
    for i, doc_id in enumerate(doc_ids[:limit]):
        out[doc_id] = float(limit - i)
    return out


def top_ranked_hits_from_events(
    events: list[dict[str, Any]], *, limit: int = 10
) -> list[dict[str, Any]]:
    """First-seen union of retrieval.completed ranked hits (path + optional score)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ev in events:
        if str(ev.get("type") or "") != "retrieval.completed":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        ranked = payload.get("ranked")
        if not isinstance(ranked, list):
            ranked = payload.get("hits")
        if not isinstance(ranked, list):
            continue
        for hit in ranked:
            if not isinstance(hit, dict):
                continue
            path = str(hit.get("path") or "")
            doc_id = doc_id_from_path(path)
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            row: dict[str, Any] = {"path": path, "doc_id": doc_id}
            if hit.get("score") is not None:
                row["score"] = hit.get("score")
            out.append(row)
            if len(out) >= limit:
                return out
    return out


def excerpt_promote_reorder_count(events: list[dict[str, Any]]) -> int:
    """Count retrieval.completed payloads that flagged excerpt promote reorder."""
    n = 0
    for ev in events:
        if str(ev.get("type") or "") != "retrieval.completed":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, dict) and payload.get("excerpt_promote_reorder"):
            n += 1
    return n


def final_assistant_text(events: list[dict[str, Any]]) -> str:
    """Best-effort final answer text from turn events."""
    texts: list[str] = []
    for ev in events:
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if et in {"turn.completed", "message.completed", "assistant.completed"}:
            for key in ("text", "content", "output", "message"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        if et in {"turn.token", "message.delta", "assistant.delta"}:
            delta = payload.get("text") or payload.get("delta") or payload.get("content")
            if isinstance(delta, str) and delta:
                texts.append(delta)
    if texts:
        return "".join(texts).strip()
    # Fallback: last tool-less assistant-looking payload
    for ev in reversed(events):
        payload = ev.get("payload") or {}
        if isinstance(payload, dict):
            text = payload.get("text") or payload.get("content")
            if isinstance(text, str) and text.strip() and str(ev.get("type") or "").startswith(
                ("assistant", "message", "turn")
            ):
                return text.strip()
    return ""


def _looks_like_unified_diff(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return "@@" in t or t.startswith("--- ") or "diff --git" in t


def _span_to_diff(path: str, old_t: str, new_t: str) -> str:
    if not new_t or new_t == old_t:
        return ""
    return f"--- a/{path}\n+++ b/{path}\n@@\n{new_t}\n"


def patch_from_events(events: list[dict[str, Any]]) -> str:
    """Extract unified diff from patch.proposed / write_file / propose_patch args."""
    for ev in events:
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if et == "patch.proposed":
            for key in ("diff", "patch", "new_text"):
                val = payload.get(key)
                if isinstance(val, str) and _looks_like_unified_diff(val):
                    return val
            # span-style propose_patch — synthesise a minimal marker for nonempty rate
            old_t = str(payload.get("old_text") or "")
            new_t = str(payload.get("new_text") or "")
            path = str(payload.get("path") or "file")
            synth = _span_to_diff(path, old_t, new_t)
            if synth:
                return synth
        if et == "tool.started":
            tool = str(payload.get("tool_name") or "")
            args = payload.get("arguments") or {}
            if not isinstance(args, dict):
                continue
            if tool == "propose_patch":
                old_t = str(args.get("old_text") or "")
                new_t = str(args.get("new_text") or "")
                path = str(args.get("path") or "file")
                synth = _span_to_diff(path, old_t, new_t)
                if synth:
                    return synth
                for key in ("diff", "patch", "new_text"):
                    val = args.get(key)
                    if isinstance(val, str) and _looks_like_unified_diff(val):
                        return val
            if tool in {"write_file", "edit_file", "apply_patch"}:
                path = str(args.get("path") or "")
                content = args.get("content") or args.get("new_text") or args.get("text")
                if isinstance(content, str) and (
                    path.endswith((".patch", ".diff")) or _looks_like_unified_diff(content)
                ):
                    if _looks_like_unified_diff(content) or path.endswith((".patch", ".diff")):
                        return content if content.strip() else ""
        if et == "tool.completed" and str(payload.get("tool_name") or "") == "propose_patch":
            # summary-only; ignore
            continue
    # Last-resort: assistant text that embeds a unified diff fence
    text = final_assistant_text(events)
    if text:
        for marker in ("```diff", "```patch", "```"):
            if marker in text:
                body = text.split(marker, 1)[1]
                body = body.split("```", 1)[0]
                if _looks_like_unified_diff(body):
                    return body.strip() + "\n"
        if _looks_like_unified_diff(text):
            return text.strip() + "\n"
    return ""


def patch_from_work_root(work_root: str | Path) -> str:
    """Read fix.patch / patch.diff written into the Work (L1 coding fallback)."""
    root = Path(work_root)
    for name in ("fix.patch", "patch.diff", "solution.patch", "prediction.patch"):
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text.strip() and (
            _looks_like_unified_diff(text) or name.endswith((".patch", ".diff"))
        ):
            return text
    return ""


def called_tools(events: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for ev in events:
        if str(ev.get("type") or "") != "tool.started":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, dict) and payload.get("tool_name"):
            names.append(str(payload["tool_name"]))
    return names


def read_targets_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """RET-14: ordered read_file targets (path → doc_id) from tool.started.

    Eval-side only — never injects qrels into runtime. Paths may be relative
    (``sources/beir/<ds>/<id>.txt``) or absolute under a Work root.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ev in events:
        if str(ev.get("type") or "") != "tool.started":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if str(payload.get("tool_name") or "") != "read_file":
            continue
        args = payload.get("arguments") or {}
        if not isinstance(args, dict):
            continue
        path = str(args.get("path") or args.get("file") or "").strip()
        if not path:
            continue
        doc_id = doc_id_from_path(path)
        key = doc_id or path
        if key in seen:
            # Still record duplicate reads for coverage, but rank uses first-seen.
            out.append({"path": path, "doc_id": doc_id, "duplicate": True})
            continue
        seen.add(key)
        out.append({"path": path, "doc_id": doc_id, "duplicate": False})
    return out


def read_doc_ids_from_events(events: list[dict[str, Any]]) -> list[str]:
    """Unique first-seen doc ids from read_file targets (RET-14)."""
    ids: list[str] = []
    seen: set[str] = set()
    for row in read_targets_from_events(events):
        doc_id = str(row.get("doc_id") or "")
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        ids.append(doc_id)
    return ids


def gold_read_case_stats(
    *,
    ranked_doc_ids: list[str],
    read_doc_ids: list[str],
    gold_doc_ids: set[str] | list[str],
) -> dict[str, Any]:
    """Per-query gold ∩ ranked ∩ read intersections (RET-14 · eval offline/L2)."""
    gold = {str(g) for g in gold_doc_ids if g}
    ranked = [str(d) for d in ranked_doc_ids if d]
    read = [str(d) for d in read_doc_ids if d]
    ranked_set = set(ranked)
    read_set = set(read)
    gold_on_ranked = sorted(gold & ranked_set)
    gold_read = sorted(gold & read_set)
    gold_on_ranked_but_unread = sorted(set(gold_on_ranked) - read_set)
    read_ranks: list[int] = []
    for doc_id in read:
        if doc_id in ranked_set:
            read_ranks.append(ranked.index(doc_id) + 1)
    return {
        "n_gold": len(gold),
        "n_ranked": len(ranked),
        "n_read_docs": len(read_set),
        "gold_on_ranked": gold_on_ranked,
        "gold_read": gold_read,
        "gold_on_ranked_but_unread": gold_on_ranked_but_unread,
        "read_any_gold": bool(gold_read),
        "gold_on_ranked_n": len(gold_on_ranked),
        "gold_read_n": len(gold_read),
        "gold_on_ranked_but_unread_n": len(gold_on_ranked_but_unread),
        "read_target_ranks": read_ranks,
        # weak_hits split: present on ranked but never read vs absent from ranked
        "failure_slice": (
            "no_gold"
            if not gold
            else (
                "gold_absent_from_ranked"
                if not gold_on_ranked
                else (
                    "gold_on_ranked_but_unread"
                    if gold_on_ranked_but_unread and not gold_read
                    else (
                        "gold_read"
                        if gold_read
                        else "gold_on_ranked_partial"
                    )
                )
            )
        ),
    }


def search_queries_from_events(events: list[dict[str, Any]]) -> list[str]:
    """Ordered queries passed to search_sources / search_codebase."""
    out: list[str] = []
    for ev in events:
        if str(ev.get("type") or "") != "tool.started":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        tool = str(payload.get("tool_name") or "")
        if tool not in {"search_sources", "search_codebase"}:
            continue
        args = payload.get("arguments") or {}
        if not isinstance(args, dict):
            continue
        q = args.get("query") or args.get("q") or args.get("text")
        if isinstance(q, str) and q.strip():
            out.append(q.strip())
    return out


def search_limits_from_events(
    events: list[dict[str, Any]],
    *,
    default_limit: int | None = 30,
) -> list[int | None]:
    """Ordered ``limit`` args from ``search_sources`` tool.started events.

    Missing/invalid limit → ``default_limit`` (schema default). Non-search tools ignored.
    """
    out: list[int | None] = []
    for ev in events:
        if str(ev.get("type") or "") != "tool.started":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if str(payload.get("tool_name") or "") != "search_sources":
            continue
        args = payload.get("arguments") or {}
        if not isinstance(args, dict):
            out.append(default_limit)
            continue
        raw = args.get("limit")
        if raw is None or raw == "":
            out.append(default_limit)
            continue
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            out.append(default_limit)
    return out


def ranked_lengths_from_events(events: list[dict[str, Any]]) -> list[int]:
    """Per ``retrieval.completed`` ranked length (prefer ranked list, else hit_count)."""
    out: list[int] = []
    for ev in events:
        if str(ev.get("type") or "") != "retrieval.completed":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        ranked = payload.get("ranked")
        if isinstance(ranked, list) and ranked:
            out.append(len(ranked))
            continue
        hc = payload.get("hit_count")
        if isinstance(hc, (int, float)):
            out.append(int(hc))
            continue
        hits = payload.get("hits")
        if isinstance(hits, list):
            out.append(len(hits))
        else:
            out.append(0)
    return out


def depth_audit_from_events(
    events: list[dict[str, Any]],
    *,
    default_limit: int | None = 30,
) -> dict[str, Any]:
    """RET-6/RET-10 per-query depth fields for FiQA / merge-list / lane attribution."""
    limits = search_limits_from_events(events, default_limit=default_limit)
    ranked_lengths = ranked_lengths_from_events(events)
    merged = merge_retrieval_rankings(events)
    lane_rows = lane_depth_from_events(events)
    # Aggregate lane depths across searches in the turn (max per field — pool capacity).
    vector_ns = [int(r.get("vector_n") or 0) for r in lane_rows]
    bm25_ns = [int(r.get("bm25_n") or 0) for r in lane_rows]
    union_ns = [int(r.get("union_n") or 0) for r in lane_rows]
    two_level_ns = [int(r.get("two_level_doc_n") or 0) for r in lane_rows]
    top_ks = [
        int(r["lane_top_k"])
        for r in lane_rows
        if isinstance(r.get("lane_top_k"), (int, float))
    ]
    over_fetchs = [
        float(r["over_fetch_multiplier"])
        for r in lane_rows
        if isinstance(r.get("over_fetch_multiplier"), (int, float))
    ]
    out: dict[str, Any] = {
        "search_limits": limits,
        "ranked_lengths": ranked_lengths,
        "n_search_depth": len(limits),
        "merged_len": len(merged),
        "max_limit": max((L for L in limits if isinstance(L, int)), default=None),
        "min_limit": min((L for L in limits if isinstance(L, int)), default=None),
        # RET-10
        "lane_vector_n": max(vector_ns) if vector_ns else None,
        "lane_bm25_n": max(bm25_ns) if bm25_ns else None,
        "lane_union_n": max(union_ns) if union_ns else None,
        "two_level_doc_n": max(two_level_ns) if two_level_ns else None,
        "lane_top_k": max(top_ks) if top_ks else None,
        "over_fetch_multiplier": max(over_fetchs) if over_fetchs else None,
        "lane_depth_searches": lane_rows,
    }
    return out


def lane_depth_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per ``retrieval.completed`` audit.lane_depth rows (RET-10)."""
    out: list[dict[str, Any]] = []
    for ev in events:
        if str(ev.get("type") or "") != "retrieval.completed":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        audit = payload.get("audit")
        if not isinstance(audit, dict):
            continue
        lane = audit.get("lane_depth")
        if isinstance(lane, dict) and lane:
            out.append(dict(lane))
    return out


def turn_failure_message_from_events(events: list[dict[str, Any]]) -> str:
    """Best-effort message from the latest ``turn.failed`` payload."""
    for ev in reversed(events):
        if str(ev.get("type") or "") != "turn.failed":
            continue
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        return str(
            (payload or {}).get("message")
            or (payload or {}).get("reason")
            or (payload or {}).get("error")
            or ""
        )
    return ""


def failure_class_from_events(events: list[dict[str, Any]]) -> str | None:
    """``infra_channel`` when turn failed on provider/channel instability; else None."""
    from official_bench.l2_probes import (
        INFRA_CHANNEL_BUCKET,
        is_infra_channel_failure,
    )

    msg = turn_failure_message_from_events(events)
    if is_infra_channel_failure(msg):
        return INFRA_CHANNEL_BUCKET
    return None


def terminal_state_from_events(events: list[dict[str, Any]]) -> str:
    for ev in reversed(events):
        et = str(ev.get("type") or "")
        if et == "turn.completed":
            return "completed"
        if et == "turn.cancelled":
            return "cancelled"
        if et == "turn.failed":
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            reason = str(
                (payload or {}).get("message")
                or (payload or {}).get("reason")
                or (payload or {}).get("error")
                or ""
            )
            low = reason.lower()
            # Provider channel timeouts stay ``failed`` (infra), not step_timeout.
            from official_bench.l2_probes import is_infra_channel_failure

            if is_infra_channel_failure(reason):
                return "failed"
            if "stall" in low:
                return "stall"
            if "timeout" in low or "step_timeout" in low:
                return "step_timeout"
            return "failed"
    return "unknown"


def step_count_from_events(events: list[dict[str, Any]]) -> int:
    n = 0
    for ev in events:
        if str(ev.get("type") or "") == "step.started":
            n += 1
    return n


def read_file_stats_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """n_reads / read_bytes / continue-reads / last offset / truncation (CTX-9).

    ``tool.completed`` does **not** carry full ``content`` (bus size). Prefer
    explicit ``chars_read`` / ``file_chars`` / ``next_offset`` on the payload
    (runtime ≥ CTX-9 fix). Fall back to summary/hint parsing for older events.
    """
    n_reads = 0
    read_bytes = 0
    used_next_offset = False
    truncation_hits = 0
    continue_reads = 0
    last_read_offset: int | None = None
    file_chars_seen: int | None = None
    for ev in events:
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        tool = str(payload.get("tool_name") or "")
        if et == "tool.started" and tool == "read_file":
            n_reads += 1
            args = payload.get("arguments") or {}
            if isinstance(args, dict):
                off = args.get("offset")
                if off not in (None, 0, "0"):
                    used_next_offset = True
                    continue_reads += 1
                    try:
                        last_read_offset = int(off)
                    except (TypeError, ValueError):
                        pass
                elif args.get("next_offset") not in (None, 0, "0"):
                    used_next_offset = True
                    continue_reads += 1
        if et == "tool.completed" and tool == "read_file":
            # Primary: light coverage fields on the event (no full content).
            chunk = _chars_read_from_tool_completed(payload)
            read_bytes += chunk
            fc = payload.get("file_chars")
            if isinstance(fc, (int, float)) and int(fc) > 0:
                file_chars_seen = max(file_chars_seen or 0, int(fc))
            if payload.get("is_truncated") or payload.get("truncated"):
                truncation_hits += 1
            nxt = payload.get("next_offset")
            if nxt not in (None, 0, "0", ""):
                used_next_offset = True
                try:
                    last_read_offset = int(nxt)
                except (TypeError, ValueError):
                    pass
            off = payload.get("offset")
            if off not in (None, 0, "0", "") and last_read_offset is None:
                try:
                    last_read_offset = int(off)
                except (TypeError, ValueError):
                    pass
            # Legacy: some emitters put a nested result dict (tests / older paths).
            result = payload.get("result") or payload.get("output")
            if isinstance(result, dict):
                text = str(result.get("content") or result.get("text") or "")
                if text and chunk == 0:
                    read_bytes += len(text)
                if result.get("next_offset") not in (None, 0, "0"):
                    used_next_offset = True
                    try:
                        last_read_offset = int(result["next_offset"])
                    except (TypeError, ValueError):
                        pass
                if "[budget_truncated]" in text or "budget_truncated" in text:
                    truncation_hits += 1
            # Truncation markers in summary text
            summary = str(payload.get("summary") or "")
            if "truncated" in summary.lower() or "[budget_truncated]" in summary:
                truncation_hits += 1
        # Also scan assistant/tool text blobs for truncation marker
        for key in ("text", "content", "output", "message"):
            val = payload.get(key)
            if isinstance(val, str) and "[budget_truncated]" in val:
                truncation_hits += 1
    out: dict[str, Any] = {
        "n_reads": n_reads,
        "read_bytes": read_bytes,
        "used_next_offset": used_next_offset,
        "truncation_hits": truncation_hits,
        "continue_reads": continue_reads,
        "last_read_offset": last_read_offset,
    }
    if file_chars_seen is not None:
        out["file_chars"] = file_chars_seen
    return out


def _chars_read_from_tool_completed(payload: dict[str, Any]) -> int:
    """Best-effort chars for one read_file completion (CTX-9)."""
    raw = payload.get("chars_read")
    if isinstance(raw, (int, float)) and int(raw) >= 0:
        return int(raw)
    # Nested result (tests)
    result = payload.get("result")
    if isinstance(result, dict):
        if isinstance(result.get("chars_read"), (int, float)):
            return int(result["chars_read"])
        text = result.get("content") or result.get("text")
        if isinstance(text, str) and text:
            return len(text)
    # Hint / summary: 「已读 X / 共 Y 字符」
    for key in ("summary", "hint"):
        blob = str(payload.get(key) or "")
        m = _CHARS_READ_HINT_RE.search(blob)
        if m:
            return int(m.group(1))
    # Last resort: rough estimate from line span in English summary (~80 chars/line).
    summary = str(payload.get("summary") or "")
    m2 = _LINES_SUMMARY_RE.search(summary)
    if m2:
        start, end, _total = (int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        n_lines = max(0, end - start + 1)
        return n_lines * 80
    return 0


def ran_tests_from_events(events: list[dict[str, Any]]) -> bool:
    tools = set(called_tools(events))
    return bool(tools & {"run_tests", "run_command"})


def patch_from_git_diff(work_root: str | Path, *, base_ref: str = "HEAD") -> str:
    """Prefer real worktree changes (A-3): ``git diff`` against clean tree / base."""
    import subprocess

    root = Path(work_root)
    if not (root / ".git").exists() and not (root / ".git").is_file():
        # May be a checkout without nested .git if using --git-dir; try plain diff
        pass
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "--no-color"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    text = (proc.stdout or "").strip()
    if text and _looks_like_unified_diff(text):
        return text + "\n"
    # staged
    try:
        proc2 = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--no-color"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    text2 = (proc2.stdout or "").strip()
    if text2 and _looks_like_unified_diff(text2):
        return text2 + "\n"
    _ = base_ref  # reserved for explicit base comparisons
    return ""


def patch_apply_check(work_root: str | Path, patch: str) -> bool | None:
    """Return True/False if ``git apply --check`` works; None if git unavailable."""
    import subprocess
    import tempfile

    if not (patch or "").strip():
        return False
    root = Path(work_root)
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8") as fh:
            fh.write(patch)
            path = fh.name
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "apply", "--check", path],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        finally:
            Path(path).unlink(missing_ok=True)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.returncode == 0
