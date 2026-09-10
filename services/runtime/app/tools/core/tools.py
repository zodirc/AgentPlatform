"""工具门面（facade）：统一路径解析与跨模块依赖注入。

``bootstrap`` 注册表默认从此模块 re-export 公开 handler（``read_file``、``edit_file``、
``search_sources`` 等）。部分 wrapper 在调用实现前临时 monkeypatch 子模块内的
路径/诊断/检索辅助函数，使各 ``core/*.py`` 可独立单测而不重复绑定 workspace 根。
"""

from __future__ import annotations

from app.settings import settings
from app.tools.core import edit_tools as _edit_tools
from app.tools.core import patch_tools as _patch_tools
from app.tools.core import sources_search as _sources_search
from app.tools.core.codebase_search import _lexical_codebase_hits, search_codebase
from app.tools.core.edit_tools import (
    _checks_for_edit, _file_diagnostics_issues, _finalize_checks_after_write,
    _impact_for_edit, _issue_key, edit_file as _edit_file_impl, rename_file,
    run_tests, write_file,
)
from app.tools.core.export_tools import export_document
from app.tools.core.lsp_tools import (
    _lsp_infra_failed, find_references, goto_definition, read_lints,
)
from app.tools.core.misc_tools import (
    _make_cancel_checker, check_citation, delegate, run_command, slow_tool, stub_echo,
)
from app.tools.core.patch_tools import (
    _span_apply_precheck as _span_apply_precheck_impl,
    _unified_patch_apply_precheck, apply_patch, propose_patch,
)
from app.tools.core.paths import (
    _assert_not_seed_corpus, _normalized_workspace_rel, _resolve_path,
    _workspace_root, is_seed_corpus_path,
)
from app.tools.core.read_tools import (
    _LEXICAL_BUDGET_S, _LEXICAL_MAX_FILE_BYTES, _LEXICAL_SKIP_DIR_NAMES,
    _LEXICAL_SKIP_SUFFIXES, _READ_FILE_MAX_CHARS, _coerce_optional_positive_int,
    _lexical_dir_skipped, _lexical_file_skipped, _lexical_scan_sync,
    _slice_file_by_lines, glob, grep, list_dir, read_file,
)
from app.tools.core.sources_search import (
    _apply_score_rel_for_model, _attach_filter_meta, _distinctive_query_terms,
    _finalize_search_hits_for_model, _format_source_hits, _hit_covers_query_terms,
    _hit_raw_score, _hits_cover_query_terms, _looks_like_entity_token,
    _maybe_low_score_hint, _prefer_excerpt_covering_hits,
    _run_retrieval_blocking, _search_hit_presentation_note,
    _search_sources_keyword, _tier_search_hits_for_model, _with_retrieval_audit,
    search_sources as _search_sources_impl, sync_sources_index,
)
from app.tools.core.writing_tools import (
    _LEGACY_WORK_DRAFTS, _WORK_DRAFTS, _WORK_HISTORY, _WORK_TURNS,
    _draft_file_path, _history_file_path, _is_legacy_revision_rel,
    _legacy_draft_file_path, _manifest_candidate_paths, _manifest_path,
    _prune_section_history, _read_manifest, _revision_candidate_paths,
    _revision_file_path, _section_filename, _session_scope, _turn_scope,
    _write_manifest, author_note, draft_section, note_story_delta,
    propose_chapter_openings, propose_opening_ponds, update_outline, update_plan,
)
from app.writing.signals.assemble import evaluate_writing_fragment, writing_rubric


def _span_apply_precheck(path: str, old_text: str, new_text: str):
    """门面版 span 预检：注入门面 ``_resolve_path`` 后委托 ``patch_tools``。

    参数:
        path: 工作区相对路径。
        old_text: 待替换原文 span。
        new_text: 替换后 span。

    返回:
        与 ``patch_tools._span_apply_precheck`` 相同结构的 dict。
    """
    original = _patch_tools._resolve_path
    _patch_tools._resolve_path = _resolve_path
    try:
        return _span_apply_precheck_impl(path, old_text, new_text)
    finally:
        _patch_tools._resolve_path = original


async def search_sources(*args, **kwargs):
    """门面 ``search_sources``：注入门面侧 query 分词与 keyword 实现。

    参数:
        与 ``sources_search.search_sources`` 相同（``query``/``limit``/``path_prefix`` 等）。

    返回:
        检索结果 dict（含 ``hits``/``retrieval``/``audit`` 等）。
    """
    originals = (
        _sources_search._distinctive_query_terms,
        _sources_search._search_sources_keyword,
    )
    _sources_search._distinctive_query_terms = _distinctive_query_terms
    _sources_search._search_sources_keyword = _search_sources_keyword
    try:
        return await _search_sources_impl(*args, **kwargs)
    finally:
        (
            _sources_search._distinctive_query_terms,
            _sources_search._search_sources_keyword,
        ) = originals


async def edit_file(*args, **kwargs):
    """门面 ``edit_file``：注入门面侧 ``_file_diagnostics_issues`` 绑定。

    参数:
        与 ``edit_tools.edit_file`` 相同（``path``/``old_text``/``new_text`` 等）。

    返回:
        编辑结果 dict（含 ``impact``/``checks``/``related_tests`` 等）。
    """
    original = _edit_tools._file_diagnostics_issues
    _edit_tools._file_diagnostics_issues = _file_diagnostics_issues
    try:
        return await _edit_file_impl(*args, **kwargs)
    finally:
        _edit_tools._file_diagnostics_issues = original
