"""prose 路径判定。"""

from __future__ import annotations

_PROSE_PREFIXES = ("sections/", "drafts/")


def is_prose_writing_path(path: str) -> bool:
    """是否 prose 写作路径。
    
    参数:
        path。
    
    返回:
        bool。"""
    p = (path or "").strip().replace("\\", "/").lstrip("./")
    if not p or p == "outline.md":
        return False
    if p.startswith(_PROSE_PREFIXES):
        return p.endswith(".md")
    return p in {"manuscript.md"} or p.endswith("/manuscript.md")


def section_id_from_path(path: str) -> str:
    """sections 路径→id。
    
    参数:
        path。
    
    返回:
        str。"""
    p = path.strip().replace("\\", "/").lstrip("./")
    if p.startswith("sections/") and p.endswith(".md"):
        return p.rsplit("/", 1)[-1][:-3]
    return ""
