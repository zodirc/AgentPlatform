"""Work-surface visibility — shared by Web list API and agent ``list_dir``."""

from __future__ import annotations


def normalized_workspace_rel(path: str) -> str:
    return str(path or "").strip().lstrip("/").replace("\\", "/")


def is_work_surface_hidden(path: str) -> bool:
    """Harness / WN1 pending — on disk for known-path tools; hidden from directory listings."""
    rel = normalized_workspace_rel(path)
    if rel == ".agent" or rel.startswith(".agent/"):
        return True
    if rel == "sources/cards/pending" or rel.startswith("sources/cards/pending/"):
        return True
    return False


def filter_work_surface_list_entries(parent: str, entries: list[str]) -> list[str]:
    parent_rel = normalized_workspace_rel(parent)
    if parent_rel in {"", "."}:
        parent_rel = ""
    out: list[str] = []
    for entry in entries:
        name = entry.rstrip("/")
        full = name if not parent_rel else f"{parent_rel}/{name}"
        if is_work_surface_hidden(full):
            continue
        out.append(entry)
    return out
