"""Pure helpers: extract L1 scores from product turn_events (no I/O)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_DOC_ID_RE = re.compile(r"([^/\\]+?)(?:\.[A-Za-z0-9]+)?$")


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


def terminal_state_from_events(events: list[dict[str, Any]]) -> str:
    for ev in reversed(events):
        et = str(ev.get("type") or "")
        if et == "turn.completed":
            return "completed"
        if et == "turn.cancelled":
            return "cancelled"
        if et == "turn.failed":
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            reason = str((payload or {}).get("reason") or (payload or {}).get("error") or "")
            low = reason.lower()
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
    """n_reads / read_bytes / used_next_offset / truncation_hits from tool traffic."""
    n_reads = 0
    read_bytes = 0
    used_next_offset = False
    truncation_hits = 0
    for ev in events:
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        tool = str(payload.get("tool_name") or "")
        if et == "tool.started" and tool == "read_file":
            n_reads += 1
            args = payload.get("arguments") or {}
            if isinstance(args, dict) and (
                args.get("offset") not in (None, 0, "0")
                or args.get("next_offset") not in (None, 0, "0")
            ):
                used_next_offset = True
        if et == "tool.completed" and tool == "read_file":
            result = payload.get("result") or payload.get("output") or payload.get("text")
            if isinstance(result, dict):
                text = str(result.get("content") or result.get("text") or "")
                if result.get("next_offset") not in (None, 0, "0"):
                    used_next_offset = True
            else:
                text = str(result or "")
            read_bytes += len(text)
            if "[budget_truncated]" in text or "budget_truncated" in text:
                truncation_hits += 1
        # Also scan assistant/tool text blobs for truncation marker
        for key in ("text", "content", "output", "message"):
            val = payload.get(key)
            if isinstance(val, str) and "[budget_truncated]" in val:
                truncation_hits += 1
    return {
        "n_reads": n_reads,
        "read_bytes": read_bytes,
        "used_next_offset": used_next_offset,
        "truncation_hits": truncation_hits,
    }


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
