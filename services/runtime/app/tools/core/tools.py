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
from app.tools.core.kb_audit import audit_knowledge_base
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
    _write_manifest, draft_section, update_outline, update_plan,
)


def _span_apply_precheck(path: str, old_text: str, new_text: str):
    original = _patch_tools._resolve_path
    _patch_tools._resolve_path = _resolve_path
    try:
        return _span_apply_precheck_impl(path, old_text, new_text)
    finally:
        _patch_tools._resolve_path = original


async def search_sources(*args, **kwargs):
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
    original = _edit_tools._file_diagnostics_issues
    _edit_tools._file_diagnostics_issues = _file_diagnostics_issues
    try:
        return await _edit_file_impl(*args, **kwargs)
    finally:
        _edit_tools._file_diagnostics_issues = original
