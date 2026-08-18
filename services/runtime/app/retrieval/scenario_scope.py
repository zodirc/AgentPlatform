"""Scenario-scoped retrieval policy (Profile-driven; not AgentEngine branches).

Frozen at tool time via ``scenario_id`` kwargs from ToolExecutor.
Does not sync indexes or call the model — filter/default only (docs/13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.retrieval.path_filter import normalize_path_prefix, path_matches_prefix


@dataclass(frozen=True)
class RetrievalPolicy:
    """Declarative scope from ScenarioProfile.retrieval."""

    default_path_prefix: str | None = None
    exclude_path_prefixes: tuple[str, ...] = ()
    section_title_prior: str | None = None


def policy_from_mapping(raw: dict[str, Any] | None) -> RetrievalPolicy:
    data = raw if isinstance(raw, dict) else {}
    default = data.get("default_path_prefix")
    default_s = str(default).strip() if default is not None else ""
    excludes_raw = data.get("exclude_path_prefixes") or []
    excludes: list[str] = []
    if isinstance(excludes_raw, list):
        for item in excludes_raw:
            s = str(item).strip()
            if s:
                excludes.append(s)
    prior_raw = data.get("section_title_prior")
    if isinstance(prior_raw, bool):
        prior = "texture" if prior_raw else ""
    else:
        prior = str(prior_raw or "").strip()
    return RetrievalPolicy(
        default_path_prefix=default_s or None,
        exclude_path_prefixes=tuple(excludes),
        section_title_prior=prior or None,
    )


def load_retrieval_policy(scenario_id: str | None) -> RetrievalPolicy:
    if not scenario_id:
        return RetrievalPolicy()
    try:
        from app.scenarios.registry import ScenarioRegistry

        profile = ScenarioRegistry.get(str(scenario_id))
    except (ValueError, KeyError):
        return RetrievalPolicy()
    return policy_from_mapping(getattr(profile, "retrieval", None) or {})


def resolve_search_path_prefix(
    path_prefix: str | None,
    *,
    scenario_id: str | None,
) -> tuple[str | None, dict[str, Any]]:
    """Resolve effective path_prefix for search_sources.

    - ``path_prefix is None`` (model omitted) → Profile default (if any)
    - otherwise → caller value (``\"\"`` clears to unscoped under sources/)
    """
    policy = load_retrieval_policy(scenario_id)
    meta: dict[str, Any] = {
        "scenario_id": scenario_id or "",
        "default_path_prefix": policy.default_path_prefix,
        "exclude_path_prefixes": list(policy.exclude_path_prefixes),
    }
    if path_prefix is None and policy.default_path_prefix:
        meta["applied_default"] = True
        return policy.default_path_prefix, meta
    meta["applied_default"] = False
    return path_prefix, meta


def normalize_exclude_prefixes(excludes: tuple[str, ...] | list[str]) -> list[str]:
    out: list[str] = []
    for raw in excludes:
        normalized, err = normalize_path_prefix(str(raw))
        if err or not normalized:
            continue
        out.append(normalized)
    return out


def path_is_excluded(path: str, exclude_prefixes: list[str]) -> bool:
    for pref in exclude_prefixes:
        if path_matches_prefix(path, pref):
            return True
    return False


def filter_hits_by_excludes(
    hits: list[Any],
    *,
    scenario_id: str | None,
) -> tuple[list[Any], dict[str, Any]]:
    """Drop hits under Profile exclude_path_prefixes (e.g. writing hides seed/intel)."""
    policy = load_retrieval_policy(scenario_id)
    prefixes = normalize_exclude_prefixes(policy.exclude_path_prefixes)
    meta: dict[str, Any] = {
        "exclude_path_prefixes": prefixes,
        "applied": bool(prefixes),
    }
    if not prefixes:
        return hits, meta
    filtered: list[Any] = []
    for hit in hits:
        path = getattr(hit, "path", None)
        if path is None and isinstance(hit, dict):
            path = hit.get("path")
        if path_is_excluded(str(path or ""), prefixes):
            continue
        filtered.append(hit)
    meta["removed"] = len(hits) - len(filtered)
    return filtered, meta
