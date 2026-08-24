
"""Work 表面可见性：Web list API 与 agent list_dir 共享过滤规则。"""

from __future__ import annotations


def normalized_workspace_rel(path: str) -> str:
    """作用：规范化为无前导斜杠的 POSIX 相对路径。"""
    return str(path or "").strip().lstrip("/").replace("\\", "/")


def is_work_surface_hidden(path: str) -> bool:
    """作用：is_work_surface_hidden 公开 API。

参数：
    ``path``"""
    rel = normalized_workspace_rel(path)
    if rel == ".agent" or rel.startswith(".agent/"):
        return True
    if rel == "sources/cards/pending" or rel.startswith("sources/cards/pending/"):
        return True
    return False


def filter_work_surface_list_entries(parent: str, entries: list[str]) -> list[str]:
    """作用：过滤 list_dir 结果，隐藏 harness 内部路径。"""
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
    """作用：apply_seed_listing 公开 API。

参数：
    ``path``、``entries``"""
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
