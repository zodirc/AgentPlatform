"""L1 agent-path prompts (round1 A-1/A-2/A-3). Kept free of api imports for unit tests."""

from __future__ import annotations

from typing import Any


def retrieval_prompt(*, arm: str, qtext: str, limit_k: int) -> str:
    """free = natural task (SCORECARD); forced = L2 Index-plane diagnostic."""
    if arm == "forced":
        return (
            "You are evaluating retrieval on a local sources library. "
            f"Call search_sources exactly once with query={qtext!r} "
            f"and limit={limit_k}. Do not invent documents. "
            "After the tool result, reply with OK."
        )
    return (
        "Answer the following information need using the local sources library "
        "in this Work. Search the library for supporting evidence and cite what "
        "you find. Do not invent documents.\n\n"
        f"Information need: {qtext}"
    )


def context_prompt(*, arm: str, question: str) -> str:
    """free = unrestricted reads; oracle = explicit read-complete instruction."""
    if arm == "oracle":
        return (
            "The passage is at sources/passage.md. Read the material completely "
            "before answering (you may call read_file multiple times and use "
            "offset / next_offset to continue). Then answer with a short phrase "
            "only.\n\n"
            f"Question: {question}"
        )
    return (
        "The relevant material is in sources/passage.md in this Work. "
        "Use whatever reading strategy you need (read_file segments, grep, etc.), "
        "then answer with a short phrase only.\n\n"
        f"Question: {question}"
    )


def coding_prompt(inst: dict[str, Any], *, has_repo: bool) -> str:
    iid = inst.get("instance_id")
    repo = inst.get("repo")
    if has_repo:
        return (
            f"SWE-bench instance {iid} ({repo}).\n"
            "The repository is checked out in this Work at the base commit. "
            "problem.md restates the issue. Reproduce if helpful, locate the bug, "
            "edit files to fix it, and run tests when useful. Do not use network. "
            "Do not invent a patch without inspecting the tree.\n"
        )
    return (
        f"SWE-bench instance {iid} ({repo}).\n"
        "This Work has NO repository checkout — only problem.md.\n"
        "Do NOT list empty dirs, glob the whole tree, or use network/curl.\n"
        "Read problem.md once, then write a best-effort unified diff to "
        "fix.patch via write_file (preferred), or propose_patch with "
        "old_text/new_text spans. End the turn when fix.patch exists.\n"
    )


def limit_rows_per_task(
    rows: list[dict[str, Any]], limit_per_task: int
) -> list[dict[str, Any]]:
    """Cap LongBench samples per task (not a global head slice)."""
    if limit_per_task <= 0:
        return rows
    counts: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for row in rows:
        task = str(row.get("task") or row.get("dataset") or "longbench")
        n = counts.get(task, 0)
        if n >= limit_per_task:
            continue
        counts[task] = n + 1
        out.append(row)
    return out
