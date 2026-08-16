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


# Standard RRF dampening constant (Cormack et al. 2009).
_RRF_K = 60.0


def rrf_fusion_scores(
    events: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, int]]:
    """RRF scores + first-seen order from all ``retrieval.completed`` events.

    Each search contributes ``1/(k + rank)`` per doc (Cormack k=60). Docs found
    by several searches (or ranked high in a later, better query) outrank
    one-off early hits. Single-search Turns stay order-preserving.
    """
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for ev in events:
        if str(ev.get("type") or "") != "retrieval.completed":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        for rank, doc_id in enumerate(
            ranked_doc_ids_from_retrieval_payload(payload), start=1
        ):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank)
            if doc_id not in first_seen:
                first_seen[doc_id] = order
                order += 1
    return scores, first_seen


def merge_retrieval_rankings(events: list[dict[str, Any]]) -> list[str]:
    """RRF-fuse all retrieval.completed rankings into one merged list."""
    scores, first_seen = rrf_fusion_scores(events)
    return sorted(scores, key=lambda d: (-scores[d], first_seen[d]))


def ranking_scores(
    doc_ids: list[str],
    *,
    limit: int = 100,
    raw_scores: dict[str, float] | None = None,
) -> dict[str, float]:
    """Convert ranked ids to {doc_id: score} with higher=better for metrics_ir.

    When ``raw_scores`` is given (typically RRF fusion scores), those magnitudes
    are kept so graded qrels (SciFact) see a real score, not a rank-only
    ``limit-i`` staircase. Missing ids still get a rank fallback.
    """
    out: dict[str, float] = {}
    for i, doc_id in enumerate(doc_ids[:limit]):
        if raw_scores and doc_id in raw_scores:
            out[doc_id] = float(raw_scores[doc_id])
        else:
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
    t = (text or "").lstrip("\n").rstrip()
    if not t:
        return False
    return "@@" in t or t.startswith("--- ") or "diff --git" in t


def _normalize_unified_diff(text: str) -> str:
    """Keep unified-diff body intact (including trailing ``' \\n'`` context lines).

    ``str.strip()`` is unsafe here: git hunks often end with a blank context line
    that is a single space + newline. Stripping it makes ``patch_hunks_incomplete``
    false-positive and rejects otherwise valid SWE model_patches (astropy-12907).
    """
    if not text:
        return ""
    # Drop only bare leading newlines (not space-prefixed context).
    i = 0
    while i < len(text) and text[i] == "\n":
        i += 1
    text = text[i:]
    if not text:
        return ""
    if not text.endswith("\n"):
        text += "\n"
    return text


def _span_to_diff(path: str, old_t: str, new_t: str) -> str:
    """Build a minimal applyable unified diff from span edit old/new text."""
    if not new_t or new_t == old_t:
        return ""
    old_lines = (old_t or "").splitlines()
    new_lines = new_t.splitlines()
    old_n = len(old_lines)
    new_n = len(new_lines)
    body = [f"-{line}" for line in old_lines] + [f"+{line}" for line in new_lines]
    if not body:
        return ""
    rel = path.lstrip("./")
    if old_n == 0:
        hunk = f"@@ -0,0 +1,{new_n} @@"
        minus = "--- /dev/null"
        plus = f"+++ b/{rel}"
    elif new_n == 0:
        hunk = f"@@ -1,{old_n} +0,0 @@"
        minus = f"--- a/{rel}"
        plus = "+++ /dev/null"
    else:
        hunk = f"@@ -1,{old_n} +1,{new_n} @@"
        minus = f"--- a/{rel}"
        plus = f"+++ b/{rel}"
    parts = [
        f"diff --git a/{rel} b/{rel}",
        minus,
        plus,
        hunk,
        *body,
    ]
    return _normalize_unified_diff("\n".join(parts) + "\n")


def patch_from_edit_events(events: list[dict[str, Any]]) -> str:
    """Rebuild model_patch from successful ``edit_file`` / ``write_file`` tool args.

    Used when ``git_diff`` is empty or fails integrity (hunks_incomplete) so a
    clean span edit is not discarded.
    """
    chunks: list[str] = []
    seen_paths: set[str] = set()
    # Prefer last edit per path (later tools supersede earlier ones).
    last_by_path: dict[str, tuple[str, str, str]] = {}
    for ev in events:
        if str(ev.get("type") or "") != "tool.started":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        tool = str(payload.get("tool_name") or "")
        args = payload.get("arguments") or {}
        if not isinstance(args, dict):
            continue
        path = str(args.get("path") or "").strip()
        if not path or _path_is_diff_noise(path):
            continue
        # Skip absolute ops scaffolding paths outside the repo.
        if path.startswith("/") and "/ops-l1/" in path.replace("\\", "/"):
            # Keep only the basename-relative tail when it looks like a work path.
            rel = path.rsplit("/", 1)[-1]
            if rel.endswith((".py", ".c", ".h", ".js", ".ts", ".java", ".go", ".rs")):
                path = rel
            else:
                continue
        if tool == "edit_file":
            old_t = str(args.get("old_text") or args.get("old_string") or "")
            new_t = str(args.get("new_text") or args.get("new_string") or "")
            if new_t and new_t != old_t:
                last_by_path[path] = ("edit", old_t, new_t)
        elif tool == "write_file":
            content = args.get("content") or args.get("text") or args.get("new_text")
            if isinstance(content, str) and content:
                last_by_path[path] = ("write", "", content)
    for path, (kind, old_t, new_t) in last_by_path.items():
        if kind == "edit":
            synth = _span_to_diff(path, old_t, new_t)
        else:
            synth = _span_to_diff(path, "", new_t)
        if synth and not patch_hunks_incomplete(synth):
            if path not in seen_paths:
                seen_paths.add(path)
                chunks.append(synth.rstrip("\n"))
    if not chunks:
        return ""
    return _normalize_unified_diff("\n".join(chunks) + "\n")


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
                    return _normalize_unified_diff(val)
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
                        return _normalize_unified_diff(val)
            if tool in {"write_file", "edit_file", "apply_patch"}:
                path = str(args.get("path") or "")
                content = args.get("content") or args.get("new_text") or args.get("text")
                if isinstance(content, str) and (
                    path.endswith((".patch", ".diff")) or _looks_like_unified_diff(content)
                ):
                    if _looks_like_unified_diff(content) or path.endswith((".patch", ".diff")):
                        return _normalize_unified_diff(content) if content.strip() else ""
        if et == "tool.completed" and str(payload.get("tool_name") or "") == "propose_patch":
            # summary-only; ignore
            continue
    # Prefer reconstructed span edits from edit_file before assistant fences.
    edited = patch_from_edit_events(events)
    if edited:
        return edited
    # Last-resort: assistant text that embeds a unified diff fence
    text = final_assistant_text(events)
    if text:
        for marker in ("```diff", "```patch", "```"):
            if marker in text:
                body = text.split(marker, 1)[1]
                body = body.split("```", 1)[0]
                if _looks_like_unified_diff(body):
                    return _normalize_unified_diff(body)
        if _looks_like_unified_diff(text):
            return _normalize_unified_diff(text)
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
            return _normalize_unified_diff(text)
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


_DIFF_FILE_RE = re.compile(r"^\+\+\+\s+(?:b/)?(.+)$", re.M)
_TESTISH_CMD_RE = re.compile(
    r"\b(pytest|py\.test|unittest|nosetests|tox|run_tests)\b|"
    r"\bpython\s+-m\s+pytest\b|"
    r"\bpython\s+-m\s+unittest\b",
    re.IGNORECASE,
)
_PAGER_CMD_RE = re.compile(
    r"^\s*(?:cat|nl|head|tail|sed)\b",
    re.IGNORECASE,
)


def files_from_patch(patch: str) -> set[str]:
    """Paths touched by a unified diff (+++ b/ lines). Shared with D1 file_hit."""
    files: set[str] = set()
    for match in _DIFF_FILE_RE.finditer(patch or ""):
        name = match.group(1).strip()
        if name == "/dev/null":
            continue
        files.add(name.replace("\\", "/"))
    return files


def file_hit(*, model_patch: str, gold_patch: str) -> bool | None:
    """§7.7.1 D1: model∩gold files ≠ ∅. None when gold has no files (unscored)."""
    gold = files_from_patch(gold_patch)
    if not gold:
        return None
    model = files_from_patch(model_patch)
    return bool(model & gold)


def _command_fingerprint(payload: dict[str, Any]) -> str:
    """Normalize run_tests / run_command argv for repro_rerun equality."""
    for key in ("command", "display_command", "summary"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            return " ".join(raw.strip().split())
    argv = payload.get("argv")
    if isinstance(argv, list) and argv:
        return " ".join(str(x) for x in argv)
    return ""


def _is_testish_command(cmd: str) -> bool:
    return bool(cmd) and _TESTISH_CMD_RE.search(cmd) is not None


def _is_pager_command(cmd: str) -> bool:
    if not cmd:
        return False
    if any(ch in cmd for ch in "|><;") or "&&" in cmd:
        return False
    return bool(_PAGER_CMD_RE.match(cmd))


def evidence_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """§7.7.1 D1 process evidence from tool.completed (post-hoc; no gold).

    Wave 4: prefer structured ``has_test_summary`` / ``test_summary`` when present;
    still accept testish command fingerprints (compat with older runs).
    """
    cmd_counts: dict[str, int] = {}
    tests_before_submit = False
    n_test_summary = 0
    for ev in events:
        if str(ev.get("type") or "") != "tool.completed":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        tool = str(payload.get("tool_name") or "")
        if tool == "verify_receipt":
            continue
        if payload.get("has_test_summary") or (
            isinstance(payload.get("test_summary"), dict) and payload.get("test_summary")
        ):
            tests_before_submit = True
            n_test_summary += 1
        if tool == "run_tests":
            tests_before_submit = True
            fp = _command_fingerprint(payload) or "run_tests"
            cmd_counts[fp] = cmd_counts.get(fp, 0) + 1
            continue
        if tool != "run_command":
            continue
        fp = _command_fingerprint(payload)
        if not _is_testish_command(fp):
            continue
        tests_before_submit = True
        cmd_counts[fp] = cmd_counts.get(fp, 0) + 1
    repro_rerun = any(n >= 2 for n in cmd_counts.values())
    return {
        "repro_rerun": bool(repro_rerun),
        "tests_before_submit": bool(tests_before_submit),
        "n_testish_commands": int(sum(cmd_counts.values())),
        "n_distinct_testish_commands": int(len(cmd_counts)),
        "n_test_summary": int(n_test_summary),
    }


def csi_probes_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Wave 1+2 structural probes from tool.completed (Ops coding / §7.6).

    Relies on compact CSI fields on the event bus (impact/checks/locate_*), not
    full model tool_result JSON. Counts are per-Turn; suite rates roll up later.
    Also folds §7.7.1 D1 evidence flags (repro_rerun / tests_before_submit).
    """
    n_grep_locate = 0
    n_grep_locate_ok = 0
    n_grep_locate_failed = 0
    n_grep_locate_incomplete = 0
    n_locate_fuse_no_ws_symbol = 0
    n_locate_fuse_definition_null = 0
    n_locate_fuse_lsp_failed = 0
    n_locate_fuse_lsp_timeout = 0
    n_locate_fuse_non_definition = 0
    n_search_locate = 0
    n_search_locate_ok = 0
    n_edit = 0
    n_edit_ok = 0
    n_edit_with_impact = 0
    n_edit_with_checks = 0
    n_edit_with_related_tests = 0
    n_edit_impact_ok = 0
    n_edit_checks_ok = 0
    n_syntax_rejected = 0
    n_syntax_warning = 0
    n_span_fail = 0
    n_span_fail_with_candidates = 0
    n_pager_run_command = 0
    n_read_truncated = 0
    n_read_with_outline = 0
    # Wave 4 probes 12–14
    n_testish_tool = 0
    n_test_summary = 0
    n_verify_receipt = 0
    related_cmds: set[str] = set()
    executed_test_fps: set[str] = set()
    related_adopted = False
    test_ran_after_receipt = False
    saw_receipt = False

    for ev in events:
        if str(ev.get("type") or "") != "tool.completed":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        tool = str(payload.get("tool_name") or "")
        if tool in {"grep", "search_codebase"}:
            redirected = str(payload.get("redirected_from") or "")
            locate_status = str(payload.get("locate_status") or "")
            def_count = payload.get("definition_count")
            try:
                def_n = int(def_count) if def_count is not None else 0
            except (TypeError, ValueError):
                def_n = 0
            is_locate = tool == "search_codebase" or redirected == "grep"
            if not is_locate:
                continue
            fuse_reason = str(payload.get("locate_fuse_fail_reason") or "")
            if fuse_reason == "non_definition_query":
                n_locate_fuse_non_definition += 1
                continue
            if fuse_reason == "no_workspace_symbol_match":
                n_locate_fuse_no_ws_symbol += 1
            elif fuse_reason == "definition_null":
                n_locate_fuse_definition_null += 1
            elif fuse_reason == "lsp_failed":
                n_locate_fuse_lsp_failed += 1
            elif fuse_reason == "lsp_timeout":
                n_locate_fuse_lsp_timeout += 1
            if tool == "grep" or redirected == "grep":
                n_grep_locate += 1
                if locate_status == "failed":
                    n_grep_locate_failed += 1
                elif def_n > 0 or locate_status == "ok":
                    n_grep_locate_ok += 1
                elif payload.get("locate_incomplete") or locate_status == "incomplete":
                    n_grep_locate_incomplete += 1
            if tool == "search_codebase":
                n_search_locate += 1
                if def_n > 0 or locate_status == "ok":
                    n_search_locate_ok += 1
            continue

        if tool == "read_file":
            truncated = payload.get("truncated")
            if truncated is None:
                truncated = payload.get("is_truncated")
            if truncated is True:
                n_read_truncated += 1
                try:
                    outline_n = int(payload.get("outline_count") or 0)
                except (TypeError, ValueError):
                    outline_n = 0
                if outline_n > 0 or payload.get("outline"):
                    n_read_with_outline += 1
            continue

        if tool == "verify_receipt" or payload.get("verify_receipt") is True:
            n_verify_receipt += 1
            saw_receipt = True
            continue

        if tool in {"run_tests", "run_command"}:
            fp = _command_fingerprint(payload)
            if tool == "run_command" and (
                payload.get("redirected_from") or _is_pager_command(fp)
            ):
                n_pager_run_command += 1
            is_testish = tool == "run_tests" or _is_testish_command(fp)
            if is_testish:
                n_testish_tool += 1
                if fp:
                    executed_test_fps.add(fp)
                if saw_receipt:
                    test_ran_after_receipt = True
            if payload.get("has_test_summary") or (
                isinstance(payload.get("test_summary"), dict) and payload.get("test_summary")
            ):
                n_test_summary += 1
            continue

        if tool != "edit_file":
            continue
        n_edit += 1
        applies = payload.get("applies")
        status = str(payload.get("status") or "")
        err = str(payload.get("error") or payload.get("summary") or "")
        impact = payload.get("impact") if isinstance(payload.get("impact"), dict) else {}
        checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
        cand_n = payload.get("candidate_count")
        try:
            cand_n_i = int(cand_n) if cand_n is not None else 0
        except (TypeError, ValueError):
            cand_n_i = 0

        syntax = str(checks.get("syntax") or "")
        checks_status = str(checks.get("status") or "")
        if checks_status == "rejected" or syntax == "error" or "syntax_error" in err:
            n_syntax_rejected += 1
        if syntax == "warning":
            n_syntax_warning += 1

        span_fail = (
            applies is False
            or "old_text not found" in err
            or "matches" in err and "times" in err
            or cand_n_i > 0 and applies is False
        )
        if span_fail and checks_status != "rejected" and "syntax_error" not in err:
            n_span_fail += 1
            if cand_n_i > 0:
                n_span_fail_with_candidates += 1

        edited_ok = applies is True or (
            status == "ok" and payload.get("bytes_written") is not None and applies is not False
        )
        if not edited_ok:
            continue
        n_edit_ok += 1
        if impact:
            n_edit_with_impact += 1
            if str(impact.get("status") or "") == "ok":
                n_edit_impact_ok += 1
        if checks:
            n_edit_with_checks += 1
            if str(checks.get("status") or "") in {"ok", "timeout", "failed", "skipped"}:
                # presence on success path counts as coverage; ok is stricter
                if str(checks.get("status") or "") == "ok":
                    n_edit_checks_ok += 1
        try:
            related_n = int(payload.get("related_tests_count") or 0)
        except (TypeError, ValueError):
            related_n = 0
        if related_n > 0 or (
            isinstance(payload.get("related_tests"), list) and payload.get("related_tests")
        ):
            n_edit_with_related_tests += 1
        cmds = payload.get("related_tests_commands")
        if isinstance(cmds, list):
            for c in cmds:
                if isinstance(c, str) and c.strip():
                    related_cmds.add(" ".join(c.strip().split()))

    # Adoption: any executed testish command matches an attached related_tests command
    # (exact fingerprint or path substring overlap).
    if related_cmds and executed_test_fps:
        for rc in related_cmds:
            for fp in executed_test_fps:
                if fp == rc or rc in fp or fp in rc:
                    related_adopted = True
                    break
            if related_adopted:
                break

    evidence = evidence_from_events(events)
    return {
        "n_grep_locate": n_grep_locate,
        "n_grep_locate_ok": n_grep_locate_ok,
        "n_grep_locate_failed": n_grep_locate_failed,
        "n_grep_locate_incomplete": n_grep_locate_incomplete,
        "n_locate_fuse_no_ws_symbol": n_locate_fuse_no_ws_symbol,
        "n_locate_fuse_definition_null": n_locate_fuse_definition_null,
        "n_locate_fuse_lsp_failed": n_locate_fuse_lsp_failed,
        "n_locate_fuse_lsp_timeout": n_locate_fuse_lsp_timeout,
        "n_locate_fuse_non_definition": n_locate_fuse_non_definition,
        "n_search_locate": n_search_locate,
        "n_search_locate_ok": n_search_locate_ok,
        "n_edit": n_edit,
        "n_edit_ok": n_edit_ok,
        "n_edit_with_impact": n_edit_with_impact,
        "n_edit_with_checks": n_edit_with_checks,
        "n_edit_with_related_tests": n_edit_with_related_tests,
        "n_edit_impact_ok": n_edit_impact_ok,
        "n_edit_checks_ok": n_edit_checks_ok,
        "n_syntax_rejected": n_syntax_rejected,
        "n_syntax_warning": n_syntax_warning,
        "n_span_fail": n_span_fail,
        "n_span_fail_with_candidates": n_span_fail_with_candidates,
        "n_pager_run_command": n_pager_run_command,
        "n_read_truncated": n_read_truncated,
        "n_read_with_outline": n_read_with_outline,
        "n_testish_tool": n_testish_tool,
        "n_test_summary": n_test_summary,
        "n_verify_receipt": n_verify_receipt,
        "related_tests_adopted": bool(related_adopted),
        "verify_receipt_triggered": bool(n_verify_receipt > 0),
        "verify_receipt_then_tested": bool(test_ran_after_receipt),
        "repro_rerun": bool(evidence.get("repro_rerun")),
        "tests_before_submit": bool(evidence.get("tests_before_submit")),
    }


def csi_suite_rates(per_case: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll per-case CSI counters into suite rates (§7.6 / §7.7.1 denominators)."""
    def _sum(key: str) -> int:
        return int(sum(int(c.get(key) or 0) for c in per_case))

    grep_locate = _sum("n_grep_locate")
    grep_ok = _sum("n_grep_locate_ok")
    edit_ok = _sum("n_edit_ok")
    edit_impact = _sum("n_edit_with_impact")
    edit_checks = _sum("n_edit_with_checks")
    edit_related = _sum("n_edit_with_related_tests")
    span_fail = _sum("n_span_fail")
    span_cand = _sum("n_span_fail_with_candidates")
    read_trunc = _sum("n_read_truncated")
    read_outline = _sum("n_read_with_outline")
    buckets = [str(c.get("bucket") or "") for c in per_case]
    n_cases = len(per_case) or 1
    n_no_patch = sum(1 for b in buckets if b == "no_patch")
    n_patch_no_apply = sum(1 for b in buckets if b == "patch_no_apply")

    def _rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return float(num) / float(den)

    # D1: file_hit is bool|None per case; suite rate over scored cases only.
    file_hit_vals = [c.get("file_hit") for c in per_case if c.get("file_hit") is not None]
    file_hit_true = sum(1 for v in file_hit_vals if v is True)
    file_hit_n = len(file_hit_vals)

    repro_true = sum(1 for c in per_case if c.get("repro_rerun") is True)
    tests_true = sum(1 for c in per_case if c.get("tests_before_submit") is True)
    n_cases_scored = len(per_case)
    testish = _sum("n_testish_tool")
    test_summary = _sum("n_test_summary")
    related_adopted_n = sum(1 for c in per_case if c.get("related_tests_adopted") is True)
    cases_with_related = sum(
        1 for c in per_case if int(c.get("n_edit_with_related_tests") or 0) > 0
    )
    receipt_n = sum(1 for c in per_case if c.get("verify_receipt_triggered") is True)
    receipt_then_test_n = sum(
        1 for c in per_case if c.get("verify_receipt_then_tested") is True
    )

    return {
        "locate_fuse_ok_rate": _rate(grep_ok, grep_locate),
        "locate_fuse_n": float(grep_locate),
        "edit_impact_coverage": _rate(edit_impact, edit_ok),
        "edit_checks_coverage": _rate(edit_checks, edit_ok),
        "edit_related_tests_coverage": _rate(edit_related, edit_ok),
        "edit_ok_n": float(edit_ok),
        "syntax_reject_count": float(_sum("n_syntax_rejected")),
        "syntax_warning_passthrough_count": float(_sum("n_syntax_warning")),
        "span_fail_n": float(span_fail),
        "span_fail_with_candidates_rate": _rate(span_cand, span_fail),
        "bucket_share_no_patch": float(n_no_patch) / float(n_cases),
        "bucket_share_patch_no_apply": float(n_patch_no_apply) / float(n_cases),
        "n_grep_locate_failed": float(_sum("n_grep_locate_failed")),
        "n_grep_locate_incomplete": float(_sum("n_grep_locate_incomplete")),
        "n_locate_fuse_no_ws_symbol": float(_sum("n_locate_fuse_no_ws_symbol")),
        "n_locate_fuse_definition_null": float(_sum("n_locate_fuse_definition_null")),
        "n_locate_fuse_lsp_failed": float(_sum("n_locate_fuse_lsp_failed")),
        "n_locate_fuse_lsp_timeout": float(_sum("n_locate_fuse_lsp_timeout")),
        "n_locate_fuse_non_definition": float(_sum("n_locate_fuse_non_definition")),
        # §7.7.1 D1
        "file_hit_rate": _rate(file_hit_true, file_hit_n),
        "file_hit_n": float(file_hit_n),
        "repro_rerun_rate": _rate(repro_true, n_cases_scored) if n_cases_scored else None,
        "tests_before_submit_rate": (
            _rate(tests_true, n_cases_scored) if n_cases_scored else None
        ),
        # §7.7.3–7.7.4 Wave 3 probes
        "read_outline_coverage": _rate(read_outline, read_trunc),
        "n_read_truncated": float(read_trunc),
        "n_read_with_outline": float(read_outline),
        # §7.6 probes 12–14 (Wave 4)
        "test_summary_attach_rate": _rate(test_summary, testish),
        "n_testish_tool": float(testish),
        "n_test_summary": float(test_summary),
        "related_tests_adoption_rate": _rate(related_adopted_n, cases_with_related),
        "verify_receipt_rate": (
            _rate(receipt_n, n_cases_scored) if n_cases_scored else None
        ),
        "verify_receipt_then_test_rate": _rate(receipt_then_test_n, receipt_n),
        "n_verify_receipt": float(_sum("n_verify_receipt")),
    }


_HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s@@"
)


def patch_hunks_incomplete(patch: str) -> bool:
    """True when unified-diff hunk line counts do not match body (truncated / corrupt)."""
    text = patch or ""
    if not text.strip():
        return False
    lines = text.splitlines()
    i = 0
    saw_hunk = False
    while i < len(lines):
        m = _HUNK_HEADER_RE.match(lines[i])
        if not m:
            i += 1
            continue
        saw_hunk = True
        old_n = int(m.group(2) if m.group(2) is not None else "1")
        new_n = int(m.group(4) if m.group(4) is not None else "1")
        i += 1
        old_seen = 0
        new_seen = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ "):
                break
            if line.startswith("@@"):
                break
            if line.startswith("\\"):
                i += 1
                continue
            if line.startswith("+") and not line.startswith("+++"):
                new_seen += 1
            elif line.startswith("-") and not line.startswith("---"):
                old_seen += 1
            elif line.startswith(" ") or line == "":
                old_seen += 1
                new_seen += 1
            i += 1
        if old_seen != old_n or new_seen != new_n:
            return True
    return False if saw_hunk else False


# Pathspecs excluded from L1/harness model_patch (venv junk + platform scaffolding).
# Platform paths (``.agent/``, root ``problem.md``, ``sources/seed``) must not inflate
# nonempty/apply rates or ship multi-MB AST snapshots into SWE predictions.
_GIT_DIFF_EXCLUDE_PATHSPECS: tuple[str, ...] = (
    ":(exclude).local",
    ":(exclude).local/**",
    ":(exclude)**/.local/**",
    ":(exclude).venv",
    ":(exclude).venv/**",
    ":(exclude)**/.venv/**",
    ":(exclude)venv",
    ":(exclude)venv/**",
    ":(exclude)**/site-packages/**",
    ":(exclude)**/__pycache__/**",
    ":(exclude)**/.pytest_cache/**",
    ":(exclude)node_modules",
    ":(exclude)node_modules/**",
    ":(exclude)**/node_modules/**",
    ":(exclude).agent",
    ":(exclude).agent/**",
    ":(exclude)**/.agent/**",
    ":(exclude)problem.md",
    ":(exclude)sources/seed",
    ":(exclude)sources/seed/**",
)

# Exact worktree-root paths that are platform overlays, not repo edits.
_PLATFORM_DIFF_NOISE_FILES: frozenset[str] = frozenset(
    {
        "problem.md",
        "sources/seed",
    }
)


def _path_is_diff_noise(path: str) -> bool:
    """True for env/install/platform pollution that must not enter SWE model_patch."""
    p = path.replace("\\", "/")
    # Do not use str.lstrip("./") — that strips any leading '.' chars and
    # turns ``.agent/…`` into ``agent/…`` (false negative).
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    if not p:
        return False
    if p in _PLATFORM_DIFF_NOISE_FILES or p.startswith("sources/seed/"):
        return True
    parts = p.split("/")
    noise_dirs = {
        ".local",
        ".venv",
        "venv",
        "site-packages",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".agent",
    }
    return any(part in noise_dirs for part in parts)


def filter_unified_diff_noise(diff: str) -> str:
    """Drop file sections whose path is install/venv/platform noise (safety net after git)."""
    text = _normalize_unified_diff(diff or "")
    if not text:
        return ""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            # ``diff --git a/foo b/foo`` — take path after `` b/`` when present.
            rest = line[len("diff --git ") :].rstrip("\n")
            path = ""
            if " b/" in rest:
                path = rest.split(" b/", 1)[-1].strip()
            elif rest.startswith("a/") and " " in rest:
                path = rest.split(" ", 1)[0][2:]
            skip = _path_is_diff_noise(path)
            block = [line]
            i += 1
            while i < len(lines) and not lines[i].startswith("diff --git "):
                block.append(lines[i])
                i += 1
            if not skip:
                out.extend(block)
            continue
        # Orphan lines (rare) — keep unless clearly under a noise path header.
        out.append(line)
        i += 1
    return _normalize_unified_diff("".join(out))


def patch_from_git_diff(work_root: str | Path, *, base_ref: str = "HEAD") -> str:
    """Prefer real worktree changes (A-3): full diff vs ``base_ref``, including untracked."""
    import os
    import subprocess
    import tempfile

    root = Path(work_root)
    ref = (base_ref or "HEAD").strip() or "HEAD"
    # api often extracts as root while materialize chowns the tree to uid 1000;
    # without safe.directory, git returns empty / "dubious ownership" → false no_patch.
    _safe = ["-c", "safe.directory=*"]
    _pathspecs = [".", *_GIT_DIFF_EXCLUDE_PATHSPECS]

    def _run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        # text=True alone uses locale encoding and raises UnicodeDecodeError on
        # binary blobs that land in ``git diff`` (agent may write/download non-UTF8).
        # That used to escape the L1 except path when retrying patch_from_git_diff
        # and fail the whole coding suite (``invalid continuation byte`` at multi-MB offset).
        return subprocess.run(
            ["git", *_safe, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=str(root),
            env=env,
        )

    # Temp index: read-tree base + add -A → diff --cached captures tracked + untracked
    # without mutating the real index / worktree staging state.
    try:
        with tempfile.NamedTemporaryFile(prefix="agent-git-idx-", delete=False) as fh:
            idx_path = fh.name
        try:
            env = {**os.environ, "GIT_INDEX_FILE": idx_path}
            read = _run(["read-tree", ref], env=env)
            if read.returncode == 0:
                _run(["add", "-A", "--", *_pathspecs], env=env)
                proc = _run(
                    ["diff", "--cached", "--no-color", "--", *_pathspecs], env=env
                )
                text = filter_unified_diff_noise(proc.stdout or "")
                if text and _looks_like_unified_diff(text):
                    return text
        finally:
            Path(idx_path).unlink(missing_ok=True)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        pass

    # Fallback: tracked unstaged + staged only.
    try:
        proc = _run(["diff", "--no-color", ref, "--", *_pathspecs])
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return ""
    text = filter_unified_diff_noise(proc.stdout or "")
    if text and _looks_like_unified_diff(text):
        return text
    try:
        proc2 = _run(["diff", "--cached", "--no-color", "--", *_pathspecs])
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return ""
    text2 = filter_unified_diff_noise(proc2.stdout or "")
    if text2 and _looks_like_unified_diff(text2):
        return text2
    return ""


def edited_paths_from_events(events: list[dict[str, Any]]) -> list[str]:
    """Relative repo paths touched by successful edit_file / write_file tools."""
    out: list[str] = []
    seen: set[str] = set()
    for ev in events:
        if str(ev.get("type") or "") != "tool.started":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if str(payload.get("tool_name") or "") not in {"edit_file", "write_file"}:
            continue
        args = payload.get("arguments") or {}
        if not isinstance(args, dict):
            continue
        path = str(args.get("path") or "").strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if not path or path.startswith("/") or _path_is_diff_noise(path):
            continue
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def patch_from_baseline_diff(
    work_root: str | Path,
    events: list[dict[str, Any]] | None = None,
    *,
    base_ref: str = "HEAD",
) -> str:
    """Repair path: rebuild a real per-file unified diff against the checkout baseline.

    Used when the whole-tree ``git diff`` came back empty or with corrupt hunks
    although the agent did edit files. Baseline content is ``git show REF:path``;
    the worktree file is compared via ``git diff --no-index`` so hunk offsets,
    ``\\ No newline`` markers and binary detection are git-exact — unlike the
    older whole-file ``@@ -1,N`` span synth which rarely applied onto the base
    commit and silently discarded real work as ``no_patch``.
    """
    import os
    import subprocess
    import tempfile

    root = Path(work_root)
    ref = (base_ref or "HEAD").strip() or "HEAD"
    _safe = ["-c", "safe.directory=*"]

    def _git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *_safe, "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    # Candidate paths: dirty worktree state ∪ edit-event targets.
    paths: list[str] = []
    seen: set[str] = set()
    try:
        status = _git("status", "--porcelain")
        if status.returncode == 0:
            for line in (status.stdout or "").splitlines():
                if len(line) < 4:
                    continue
                rel = line[3:].strip().strip('"')
                if " -> " in rel:  # rename: take the new side
                    rel = rel.split(" -> ", 1)[1].strip().strip('"')
                rel = rel.replace("\\", "/")
                if rel and not _path_is_diff_noise(rel) and rel not in seen:
                    seen.add(rel)
                    paths.append(rel)
    except (OSError, subprocess.TimeoutExpired):
        pass
    for rel in edited_paths_from_events(events or []):
        if rel not in seen:
            seen.add(rel)
            paths.append(rel)
    if not paths:
        return ""

    chunks: list[str] = []
    for rel in paths:
        current = root / rel
        if current.is_dir():
            continue
        show = _git("show", f"{ref}:{rel}")
        has_baseline = show.returncode == 0
        has_current = current.is_file()
        if not has_baseline and not has_current:
            continue
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                prefix="ap-baseline-",
                suffix=Path(rel).suffix or ".txt",
                delete=False,
                encoding="utf-8",
            ) as fh:
                if has_baseline:
                    fh.write(show.stdout or "")
                left = fh.name
        except OSError:
            continue
        try:
            left_arg = left if has_baseline else os.devnull
            right_arg = str(current) if has_current else os.devnull
            proc = _git(
                "diff", "--no-index", "--no-color", "--", left_arg, right_arg
            )
        except (OSError, subprocess.TimeoutExpired):
            Path(left).unlink(missing_ok=True)
            continue
        finally:
            Path(left).unlink(missing_ok=True)
        # --no-index: 0 = identical, 1 = differences, >1 = error.
        if proc.returncode != 1 or not (proc.stdout or "").strip():
            continue
        body = proc.stdout
        if "Binary files" in body and "@@" not in body:
            continue
        fixed: list[str] = []
        for line in body.splitlines():
            if line.startswith("diff --git "):
                fixed.append(f"diff --git a/{rel} b/{rel}")
            elif line.startswith("--- "):
                fixed.append("--- /dev/null" if "/dev/null" in line else f"--- a/{rel}")
            elif line.startswith("+++ "):
                fixed.append("+++ /dev/null" if "/dev/null" in line else f"+++ b/{rel}")
            else:
                fixed.append(line)
        chunk = _normalize_unified_diff("\n".join(fixed) + "\n")
        if chunk and not patch_hunks_incomplete(chunk):
            chunks.append(chunk.rstrip("\n"))
    if not chunks:
        return ""
    return filter_unified_diff_noise(
        _normalize_unified_diff("\n".join(chunks) + "\n")
    )


def patch_apply_check(work_root: str | Path, patch: str) -> bool | None:
    """Return True/False if patch applies to **clean HEAD**; None if git unavailable.

    Must not only ``git apply --check`` on a dirty worktree when ``patch`` came from
    ``git diff`` of that same tree — the change is already present, so a forward
    check fails (false ``patch_no_apply``). SWE harness applies onto the base
    commit.

    Strategy:
    1. Reject incomplete hunks.
    2. ``git apply --reverse --check`` on the worktree (succeeds when tree == HEAD+patch).
    3. Detached ``git worktree`` at HEAD + forward ``git apply --check`` (needs a real
       git dir — plain ``git archive`` + apply is too permissive without ``.git``).
    """
    import subprocess
    import tempfile

    if not (patch or "").strip():
        return False
    if patch_hunks_incomplete(patch):
        return False
    root = Path(work_root)
    patch_text = patch if patch.endswith("\n") else patch + "\n"
    _safe = ["-c", "safe.directory=*"]

    def _write_patch() -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".patch", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(patch_text)
            return fh.name

    def _git(*args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *_safe, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    try:
        path = _write_patch()
        try:
            rev = _git("-C", str(root), "apply", "--reverse", "--check", path)
            if rev.returncode == 0:
                return True
        finally:
            Path(path).unlink(missing_ok=True)

        with tempfile.TemporaryDirectory(prefix="patch-apply-wt-") as td:
            td_path = Path(td) / "wt"
            add = _git(
                "-C",
                str(root),
                "worktree",
                "add",
                "--detach",
                str(td_path),
                "HEAD",
                timeout=120,
            )
            if add.returncode != 0:
                return None
            path = _write_patch()
            try:
                proc = _git("-C", str(td_path), "apply", "--check", path)
                ok = proc.returncode == 0
            finally:
                Path(path).unlink(missing_ok=True)
                _git(
                    "-C",
                    str(root),
                    "worktree",
                    "remove",
                    "--force",
                    str(td_path),
                )
            return ok
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None
