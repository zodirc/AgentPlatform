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


def apply_seed_listing(
    path: str,
    entries: list[str],
    *,
    seed_visible: bool,
    seed_present: bool,
) -> list[str]:
    """Show standing ``sources/seed/`` on isolated Works; hide when opted out.

    Isolated Work roots expose seed as a directory symlink. ``list_dir`` uses
    ``is_dir(follow_symlinks=False)``, so that entry looks like a file and the
    library walker never descends — while retrieval still hits the seed index.
    """
    rel = normalized_workspace_rel(path)
    if rel in {"", "."}:
        rel = ""
    if not seed_visible:
        if rel in {"", "sources"}:
            return [e for e in entries if e.rstrip("/") != "seed"]
        return entries
    if rel != "sources" or not seed_present:
        return entries
    out = [e for e in entries if e.rstrip("/") != "seed"]
    out.append("seed/")
    out.sort()
    return out
