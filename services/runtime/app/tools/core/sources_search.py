from __future__ import annotations

import asyncio
import contextvars
import logging
import re
from functools import partial
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.settings import settings
from app.tools.core.paths import _resolve_path, _workspace_root

_T = TypeVar("_T")
logger = logging.getLogger(__name__)

async def _run_retrieval_blocking(
    fn: Callable[..., _T], /, *args: Any, **kwargs: Any
) -> _T:
    """Run retrieval I/O/CPU off-loop with audit ContextVars intact."""
    context = contextvars.copy_context()
    call = partial(fn, *args, **kwargs)
    return await asyncio.to_thread(context.run, call)
async def sync_sources_index() -> dict[str, Any]:
    """Incremental sources projection (mtime dirty-set). Prefer scheduler for single-flight."""
    from app.retrieval.index_scheduler import run_sources_index_sync

    return await run_sources_index_sync(reason="api")


def _format_source_hits(hits: list[Any], *, excerpt_chars: int) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for hit in hits:
        if isinstance(hit, dict):
            excerpt = str(hit.get("excerpt") or "").strip()
            path = str(hit.get("path") or "")
            chunk_id = str(hit.get("chunk_id") or "")
            citation_id = str(hit.get("citation_id") or "")
            try:
                score = round(float(hit.get("score") or 0.0), 4)
            except (TypeError, ValueError):
                score = 0.0
            section_title = str(hit.get("section_title") or "").strip()
            line_start = hit.get("line_start")
            line_end = hit.get("line_end")
        else:
            excerpt = str(getattr(hit, "excerpt", "") or "").strip()
            path = str(getattr(hit, "path", "") or "")
            chunk_id = str(getattr(hit, "chunk_id", "") or "")
            citation_id = str(getattr(hit, "citation_id", "") or "")
            try:
                score = round(float(getattr(hit, "score", 0.0) or 0.0), 4)
            except (TypeError, ValueError):
                score = 0.0
            section_title = str(getattr(hit, "section_title", "") or "").strip()
            line_start = getattr(hit, "line_start", None)
            line_end = getattr(hit, "line_end", None)
        if len(excerpt) > excerpt_chars:
            excerpt = excerpt[:excerpt_chars] + "…"
        item: dict[str, Any] = {
            "path": path,
            "chunk_id": chunk_id,
            "excerpt": excerpt,
            "citation_id": citation_id,
            "score": score,
        }
        if section_title:
            item["section_title"] = section_title
        if line_start is not None:
            item["line_start"] = line_start
        if line_end is not None:
            item["line_end"] = line_end
        formatted.append(item)
    return formatted


def _tier_search_hits_for_model(
    hits: list[dict[str, Any]],
    *,
    detail_n: int | None = None,
) -> list[dict[str, Any]]:
    """RET-12: top-N keep excerpt; ranks below are path/title/score only.

    Applied **after** excerpt-promote so ordering still sees full excerpts.
    Does not change IR ``ranked`` construction beyond omitting unused fields —
    path+score remain on every row.
    """
    n = int(
        settings.search_sources_detail_hits if detail_n is None else detail_n
    )
    n = max(0, n)
    if n <= 0 or len(hits) <= n:
        return hits
    out: list[dict[str, Any]] = []
    for i, hit in enumerate(hits):
        if not isinstance(hit, dict):
            continue
        if i < n:
            out.append(hit)
            continue
        compact: dict[str, Any] = {
            "path": str(hit.get("path") or ""),
            "score": hit.get("score"),
        }
        title = str(hit.get("section_title") or hit.get("title") or "").strip()
        if title:
            compact["title"] = title
        chunk_id = str(hit.get("chunk_id") or "").strip()
        if chunk_id:
            compact["chunk_id"] = chunk_id
        out.append(compact)
    return out


def _search_hit_presentation_note(hits: list[dict[str, Any]]) -> str | None:
    detail_n = max(0, int(settings.search_sources_detail_hits))
    if detail_n <= 0 or len(hits) <= detail_n:
        return None
    compact_n = len(hits) - detail_n
    return (
        f"Presentation: top {detail_n} hit(s) include excerpts; "
        f"{compact_n} more listed as path/title/score only — "
        "read_file any path by rank, not only the excerpted head."
    )


def _hit_raw_score(hit: dict[str, Any]) -> float:
    raw = hit.get("score_raw")
    if raw is None:
        raw = hit.get("score")
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _apply_score_rel_for_model(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """RET-15-2: expose 0–100 relative scores to the model; keep raw as score_raw.

    IR ``retrieval.completed.ranked`` must read ``score_raw`` (see agent_engine).
    Relative scale is top-1 = 100 within this result list (O(n), R3-safe).
    """
    if not settings.search_sources_score_rel or not hits:
        return hits
    top = 0.0
    for hit in hits:
        if isinstance(hit, dict):
            top = max(top, _hit_raw_score(hit))
    out: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        row = dict(hit)
        raw = _hit_raw_score(row)
        row["score_raw"] = round(raw, 4)
        if top > 0:
            row["score"] = int(round(100.0 * raw / top))
        else:
            row["score"] = 0
        out.append(row)
    return out


def _maybe_low_score_hint(
    hits: list[dict[str, Any]],
    *,
    presentation_note: str | None,
) -> str | None:
    """RET-15-2: low_score uses **raw** fusion score vs calibrated threshold."""
    if not hits or not isinstance(hits[0], dict):
        return presentation_note
    top_raw = _hit_raw_score(hits[0])
    if top_raw >= float(settings.search_sources_low_score_hint):
        return presentation_note
    top_path = str(hits[0].get("path") or "")
    low = (
        "Low relevance scores; prefer read_file on the top path "
        f"({top_path}) instead of repeating search_sources."
    )
    if presentation_note:
        return f"{low} {presentation_note}"
    return low


def _finalize_search_hits_for_model(
    hits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Apply RET-15-2 score_rel + low_score hint (raw threshold) + RET-12 note."""
    note = _search_hit_presentation_note(hits)
    # Hint against raw scores before rewriting score → relative.
    hint = _maybe_low_score_hint(hits, presentation_note=note)
    hits = _apply_score_rel_for_model(hits)
    return hits, hint


def _search_sources_keyword(
    sources: Path,
    *,
    workspace_root: Path,
    query: str,
    limit: int,
    path_prefix: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.retrieval.chunking import should_index_source
    from app.retrieval.keyword_hit import keyword_hit_from_file
    from app.retrieval.path_filter import normalize_path_prefix, path_matches_prefix

    normalized, err = normalize_path_prefix(path_prefix)
    if err:
        return [], {
            "filters": {"path_prefix": path_prefix, "applied": False, "error": err},
            "hint": err,
        }

    # Prefer distinctive tokens (entities / long words). Whitespace-AND over the
    # full claim wiped lexical recall when verbs were absent from the abstract.
    terms = _distinctive_query_terms(query)
    if not terms:
        terms = [t for t in re.split(r"\s+", query.strip()) if len(t) >= 3]
    hits: list[dict[str, Any]] = []
    excerpt_chars = settings.search_sources_excerpt_chars
    max_bytes = settings.search_sources_keyword_max_file_bytes
    budget_ms = settings.search_sources_keyword_parse_budget_ms
    for fp in sorted(sources.rglob("*")):
        if not fp.is_file() or not should_index_source(fp):
            continue
        rel = str(fp.relative_to(workspace_root))
        if normalized is not None and not path_matches_prefix(rel, normalized):
            continue
        hit = keyword_hit_from_file(
            fp,
            rel_path=rel,
            terms=terms,
            excerpt_chars=excerpt_chars,
            max_file_bytes=max_bytes,
            parse_budget_ms=budget_ms,
            require_all_terms=False,
        )
        if hit is None:
            continue
        hits.append(hit)
        if len(hits) >= limit:
            break
    meta: dict[str, Any] = {}
    if normalized is not None:
        meta["filters"] = {"path_prefix": normalized, "applied": True}
    return hits, meta


def _attach_filter_meta(payload: dict[str, Any], filter_meta: dict[str, Any]) -> dict[str, Any]:
    if not filter_meta:
        return payload
    if "filters" in filter_meta:
        payload["filters"] = filter_meta["filters"]
    if filter_meta.get("hint") and not payload.get("hint"):
        payload["hint"] = filter_meta["hint"]
    return payload


def _looks_like_entity_token(token: str) -> bool:
    """Short Latin tokens that are still real query entities (gene/drug/acronym).

    ``len >= 6`` alone drops ``ADAR1`` / ``Dicer`` / ``Admp``, which then made
    cover-check ignore rank-1 gold abstracts that literally contain those names.
    """
    if len(token) < 3:
        return False
    has_alpha = any(c.isalpha() for c in token)
    has_digit = any(c.isdigit() for c in token)
    if has_alpha and has_digit:
        return True  # ADAR1, p53, PPM1D, B12
    if token.isupper() and len(token) >= 3:
        return True  # AIRE, AMPK, DNA
    # TitleCase / CamelCase names (Dicer, Admp, Albendazole already >=6).
    if len(token) >= 4 and token[0].isupper() and any(c.islower() for c in token[1:]):
        return True
    return False


def _distinctive_query_terms(query: str) -> list[str]:
    """Tokens that must appear in a hit for ANN results to count as a cover.

    Ignores short/runtime-noise tokens so a polluted stub query cannot 'cover'
    via ``writing`` in ``sources/seed/writing/...``. Keeps short scientific
    entities (``ADAR1``, ``Dicer``) so cover does not discard true ANN gold.
    """
    stop = {
        "writing",
        "search_sources",
        "scenario_id",
        "runtime_context",
        "steps_remaining",
        "sources",
        "step",
        "query",
        "path_prefix",
    }
    _cjk = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
    terms: list[str] = []
    for t in re.split(r"[\s/\[\]=:]+", query.strip()):
        if not t or t.isdigit():
            continue
        tl = t.lower()
        if tl in stop:
            continue
        # Latin runtime noise needs length; CJK names (e.g. 张白鹿) are short but real.
        if _cjk.search(t):
            if len(t) >= 2:
                terms.append(tl)
        elif len(t) >= 6 or _looks_like_entity_token(t):
            terms.append(tl)
    if terms:
        return terms
    q = query.strip().lower()
    if _cjk.search(query) and len(q) >= 2 and q not in stop:
        return [q]
    return []


def _hit_covers_query_terms(hit: dict[str, Any], terms: list[str]) -> bool:
    from app.retrieval.keyword_hit import _term_in_text

    blob = f"{hit.get('path', '')}\n{hit.get('excerpt', '')}".lower()
    return any(_term_in_text(term, blob) for term in terms)


def _prefer_excerpt_covering_hits(
    hits: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Stable-promote hits whose truncated excerpt/path shows distinctive terms.

    Hybrid can rank a long chunk that mentions the query late above a chunk that
    shows it in the UI/timeline window; tool.completed only previews hits[0].
    """
    terms = _distinctive_query_terms(query)
    if not terms or len(hits) <= 1:
        return hits
    covered: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for hit in hits:
        if _hit_covers_query_terms(hit, terms):
            covered.append(hit)
        else:
            rest.append(hit)
    if not covered:
        return hits
    promoted = covered + rest
    # Compare hit identity (same path can still reorder across chunks).
    if [id(h) for h in promoted] != [id(h) for h in hits]:
        # P10 audit: silent reorder changes IR ranked order (RET-3).
        logger.info(
            "excerpt_promote_reorder n_hits=%s n_covered=%s n_terms=%s",
            len(hits),
            len(covered),
            len(terms),
        )
        for hit in promoted:
            if isinstance(hit, dict):
                hit["_excerpt_promote_reorder"] = True
                break
    return promoted


def _hits_cover_query_terms(hits: list[dict[str, Any]], query: str) -> bool:
    """True if at least one distinctive query token appears in a hit path or excerpt.

    Hash / weak ANN neighbors can rank unrelated seed chunks above a brand-new
    on-disk fixture; falling through to keyword keeps goldens and remounts honest.
    """
    terms = _distinctive_query_terms(query)
    if not terms:
        # No distinctive tokens — treat ANN as non-authoritative.
        return False
    return any(_hit_covers_query_terms(hit, terms) for hit in hits)


def _with_retrieval_audit(
    payload: dict[str, Any],
    *,
    captured: dict[str, Any] | None,
    excerpt_chars: int,
) -> dict[str, Any]:
    from app.retrieval.audit import finalize_audit_for_result

    hits = payload.get("hits")
    if not isinstance(hits, list):
        hits = []
    mode = str(payload.get("retrieval") or "none")
    payload["audit"] = finalize_audit_for_result(
        captured,
        hits=hits,
        excerpt_chars=excerpt_chars,
        mode=mode,
    )
    return payload


async def search_sources(
    query: str,
    limit: int = 30,
    path_prefix: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    from app.retrieval.audit import begin_audit_capture, end_audit_capture
    from app.retrieval.path_filter import filter_hits_by_path_prefix
    from app.retrieval.scenario_scope import filter_hits_by_excludes, resolve_search_path_prefix
    from app.retrieval.store import get_sources_store

    scenario_id = _kwargs.get("scenario_id")
    if scenario_id is not None:
        scenario_id = str(scenario_id).strip() or None

    effective_prefix, scope_meta = resolve_search_path_prefix(
        path_prefix, scenario_id=scenario_id
    )

    sources = _resolve_path("sources")
    if not sources.exists():
        return {"query": query, "hits": [], "summary": "No sources directory", "retrieval": "none"}

    mode = settings.retrieval_mode.lower()
    workspace_root = _workspace_root()
    excerpt_chars = settings.search_sources_excerpt_chars
    audit_token = begin_audit_capture()
    out: dict[str, Any] | None = None
    # When True, merge hybrid/vector ContextVar capture into audit; else rebuild from hits.
    use_slot_capture = False
    try:
        if mode == "keyword":
            hits, filter_meta = _search_sources_keyword(
                sources,
                workspace_root=workspace_root,
                query=query,
                limit=limit * 2,
                path_prefix=effective_prefix,
            )
            hits, exclude_meta = filter_hits_by_excludes(hits, scenario_id=scenario_id)
            hits = hits[:limit]
            hits = _tier_search_hits_for_model(hits)
            hits, score_hint = _finalize_search_hits_for_model(hits)
            out = _attach_filter_meta(
                {
                    "query": query,
                    "hits": hits,
                    "summary": f"search_sources(keyword): {len(hits)} hit(s)",
                    "retrieval": "keyword",
                    "scope": {**scope_meta, "exclude": exclude_meta},
                },
                filter_meta,
            )
            if score_hint:
                out["hint"] = score_hint
            use_slot_capture = False
        else:
            # Hot path: load + search only. Never store.sync() here (A9 / docs/13 S2).
            from app.retrieval.tenant_visibility import filter_hits_for_tenant

            index_meta: dict[str, Any] = {
                "synced_on_query": False,
                "index_via_worker": settings.index_via_worker,
            }
            # Over-fetch when filtering so prefix/tenant cuts do not starve top-k.
            fetch_limit = limit * 3 if effective_prefix else limit * 2
            try:
                from app.retrieval.audit import record_lane_depth_meta

                record_lane_depth_meta(
                    requested_limit=limit,
                    over_fetch_multiplier=float(fetch_limit) / float(max(limit, 1)),
                )
                store = await _run_retrieval_blocking(
                    get_sources_store, work_root=_workspace_root()
                )
                # JSON needs its persisted index loaded once. Pgvector searches the
                # database directly once its schema is ready, so it never materializes
                # the complete source_chunks table on a request.
                if not bool(getattr(store, "is_ready", False)):
                    await _run_retrieval_blocking(store.load)
                raw_hits = await _run_retrieval_blocking(
                    store.search, query, limit=fetch_limit, mode=mode
                )
                raw_hits = filter_hits_for_tenant(raw_hits)
                retrieval = mode if mode in {"vector", "hybrid"} else "hybrid"
            except OSError:
                index_meta["error"] = "vector_index_unavailable"
                raw_hits = []
                retrieval = mode if mode in {"vector", "hybrid"} else "hybrid"

            resolved: dict[str, Any] | None = None
            ann_uncovered_hits: list[dict[str, Any]] | None = None
            ann_uncovered_meta: dict[str, Any] | None = None
            ann_uncovered_exclude: dict[str, Any] | None = None
            ann_excerpt_promote = False
            if raw_hits:
                filtered, filter_meta = filter_hits_by_path_prefix(
                    raw_hits, path_prefix=effective_prefix
                )
                filtered, exclude_meta = filter_hits_by_excludes(
                    filtered, scenario_id=scenario_id
                )
                if filter_meta.get("filters", {}).get("error"):
                    resolved = _attach_filter_meta(
                        {
                            "query": query,
                            "hits": [],
                            "summary": "search_sources: invalid path_prefix",
                            "retrieval": retrieval,
                            "index": index_meta,
                            "scope": {**scope_meta, "exclude": exclude_meta},
                        },
                        filter_meta,
                    )
                    use_slot_capture = True
                else:
                    formatted = _format_source_hits(
                        filtered[:limit], excerpt_chars=excerpt_chars
                    )
                    # RET-7: promote is optional; default on for backward-compatible behavior.
                    if settings.search_sources_excerpt_promote:
                        hits = _prefer_excerpt_covering_hits(formatted, query)
                    else:
                        hits = formatted
                    excerpt_promote = bool(
                        hits
                        and isinstance(hits[0], dict)
                        and hits[0].pop("_excerpt_promote_reorder", False)
                    )
                    covers = bool(hits) and _hits_cover_query_terms(hits, query)
                    # RET-12: tier after promote + cover check (cover needs excerpts).
                    hits = _tier_search_hits_for_model(hits)
                    if covers:
                        hits, score_hint = _finalize_search_hits_for_model(hits)
                        resolved = {
                            "query": query,
                            "hits": hits,
                            "summary": f"search_sources({retrieval}): {len(hits)} hit(s)",
                            "retrieval": retrieval,
                            "index": index_meta,
                            "scope": {**scope_meta, "exclude": exclude_meta},
                        }
                        if excerpt_promote:
                            resolved["excerpt_promote_reorder"] = True
                        _attach_filter_meta(resolved, filter_meta)
                        if score_hint:
                            resolved["hint"] = score_hint
                        use_slot_capture = True
                    elif hits:
                        # Cover miss: try keyword first (seed/hash pollution). If
                        # keyword also empty, keep ANN — do not wipe rank-1 gold.
                        index_meta["ann_missed_query_terms"] = True
                        ann_uncovered_hits = hits
                        ann_uncovered_meta = filter_meta
                        ann_uncovered_exclude = exclude_meta
                        ann_excerpt_promote = excerpt_promote
                    else:
                        index_meta["prefix_empty_after_filter"] = True

            if resolved is None:
                # Empty/stale index or uncovered ANN: keyword filesystem scan.
                index_meta["index_lag"] = True
                index_meta["hint"] = (
                    "Vector index empty or lagging; search used keyword fallback. "
                    "Rebuild via sync_sources_index / worker upload path — not on query."
                )
                hits, filter_meta = _search_sources_keyword(
                    sources,
                    workspace_root=workspace_root,
                    query=query,
                    limit=limit * 2,
                    path_prefix=effective_prefix,
                )
                hits, exclude_meta = filter_hits_by_excludes(hits, scenario_id=scenario_id)
                hits = hits[:limit]
                hits = _tier_search_hits_for_model(hits)
                if hits:
                    hits, score_hint = _finalize_search_hits_for_model(hits)
                    resolved = _attach_filter_meta(
                        {
                            "query": query,
                            "hits": hits,
                            "summary": f"search_sources(keyword-fallback): {len(hits)} hit(s)",
                            "retrieval": "keyword-fallback",
                            "index": index_meta,
                            "hint": index_meta["hint"],
                            "scope": {**scope_meta, "exclude": exclude_meta},
                        },
                        filter_meta,
                    )
                    if score_hint:
                        resolved["hint"] = f"{resolved.get('hint')}; {score_hint}"
                    use_slot_capture = False
                elif ann_uncovered_hits:
                    # Keyword found nothing; keep ANN ranking (SciFact claim≠abstract).
                    kept, score_hint = _finalize_search_hits_for_model(
                        list(ann_uncovered_hits)
                    )
                    index_meta["kept_ann_despite_cover_miss"] = True
                    index_meta.pop("index_lag", None)
                    index_meta["hint"] = (
                        "ANN hits retained after cover-term miss; keyword fallback empty."
                    )
                    resolved = _attach_filter_meta(
                        {
                            "query": query,
                            "hits": kept,
                            "summary": (
                                f"search_sources({retrieval}): {len(kept)} hit(s)"
                            ),
                            "retrieval": retrieval,
                            "index": index_meta,
                            "hint": index_meta["hint"],
                            "scope": {
                                **scope_meta,
                                "exclude": ann_uncovered_exclude or {},
                            },
                        },
                        ann_uncovered_meta or {},
                    )
                    if ann_excerpt_promote:
                        resolved["excerpt_promote_reorder"] = True
                    if score_hint:
                        resolved["hint"] = f"{resolved.get('hint')}; {score_hint}"
                    use_slot_capture = True
                else:
                    hits, score_hint = _finalize_search_hits_for_model(hits)
                    resolved = _attach_filter_meta(
                        {
                            "query": query,
                            "hits": hits,
                            "summary": f"search_sources(keyword-fallback): {len(hits)} hit(s)",
                            "retrieval": "keyword-fallback",
                            "index": index_meta,
                            "hint": index_meta["hint"],
                            "scope": {**scope_meta, "exclude": exclude_meta},
                        },
                        filter_meta,
                    )
                    if score_hint:
                        resolved["hint"] = f"{resolved.get('hint')}; {score_hint}"
                    use_slot_capture = False
            out = resolved
    finally:
        captured = end_audit_capture(audit_token)

    assert out is not None
    return _with_retrieval_audit(
        out,
        captured=captured if use_slot_capture else None,
        excerpt_chars=excerpt_chars,
    )
