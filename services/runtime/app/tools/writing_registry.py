"""写作工具注册表。不经过 ``tools.py`` 的全量聚合。"""

from __future__ import annotations

from typing import Any

from app.skills.loader import load_skill
from app.tools.core.export_tools import export_document
from app.tools.core.memory_file import forget as file_forget
from app.tools.core.memory_file import recall as file_recall
from app.tools.core.memory_file import remember as file_remember
from app.tools.core.read_tools import glob, grep, list_dir, read_file
from app.tools.core.rename_tools import rename_file
from app.tools.core.patch_tools import propose_patch
from app.tools.core.writing_tools import (
    author_state,
    draft_section,
    editor_report,
    propose_book_candidates,
    propose_chapter_openings,
    propose_retcon,
    reread_book,
    update_outline,
    update_plan,
)
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.writing_specs import SPECS

_HOST_OMIT = frozenset({"search_sources", "check_citation", "delegate"})


async def _search_sources(**kwargs: Any) -> dict[str, Any]:
    from app.tools.core.sources_search import search_sources

    return await search_sources(**kwargs)


async def _check_citation(**kwargs: Any) -> dict[str, Any]:
    from app.tools.core.misc_tools import check_citation

    return await check_citation(**kwargs)


async def _delegate(**kwargs: Any) -> dict[str, Any]:
    from app.tools.core.misc_tools import delegate

    return await delegate(**kwargs)


async def _remember(**kwargs: Any) -> dict[str, Any]:
    from app.tools.core.memory import remember

    return await remember(**kwargs)


async def _recall(**kwargs: Any) -> dict[str, Any]:
    from app.tools.core.memory import recall

    return await recall(**kwargs)


async def _forget(**kwargs: Any) -> dict[str, Any]:
    from app.tools.core.memory import forget

    return await forget(**kwargs)


def build_writing_registry(*, host: bool = False) -> ToolRegistry:
    """构建写作注册表。

    ``host=True`` 时不注册检索、引用校验、子代理，记忆走文件后端。
    """
    remember = file_remember if host else _remember
    recall = file_recall if host else _recall
    forget = file_forget if host else _forget
    handlers = {
        "read_file": read_file,
        "list_dir": list_dir,
        "grep": grep,
        "glob": glob,
        "rename_file": rename_file,
        "propose_patch": propose_patch,
        "draft_section": draft_section,
        "update_outline": update_outline,
        "propose_book_candidates": propose_book_candidates,
        "update_plan": update_plan,
        "export_document": export_document,
        "remember": remember,
        "recall": recall,
        "forget": forget,
        "load_skill": load_skill,
        "author_state": author_state,
        "reread_book": reread_book,
        "propose_retcon": propose_retcon,
        "editor_report": editor_report,
        "propose_chapter_openings": propose_chapter_openings,
        "search_sources": _search_sources,
        "check_citation": _check_citation,
        "delegate": _delegate,
    }
    registry = ToolRegistry()
    for name, spec in SPECS.items():
        if host and name in _HOST_OMIT:
            continue
        registry.register(
            ToolSpec(
                name=name,
                description=spec["description"],
                parameters=spec["parameters"],
                handler=handlers[name],
                requires_approval=bool(spec["requires_approval"]),
                timeout_s=float(spec["timeout_s"]),
            )
        )
    return registry
