"""场景（Scenario）驱动的检索策略（RAG 查询侧过滤/默认，不改索引）。

English: Scenario-driven retrieval policy (query-side filters; does not mutate index).

职责：从 ScenarioProfile.retrieval 解析 path 默认前缀、排除前缀、section 优先。
在 RAG 链路中的位置：``search_sources`` 解析 prefix、过滤 hits、writing 重排之前。
不同步索引、不调用模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.retrieval.path_filter import normalize_path_prefix, path_matches_prefix


@dataclass(frozen=True)
class RetrievalPolicy:
    """ScenarioProfile.retrieval 的声明式策略快照。"""
    default_path_prefix: str | None = None
    exclude_path_prefixes: tuple[str, ...] = ()
    section_title_prior: str | None = None


def policy_from_mapping(raw: dict[str, Any] | None) -> RetrievalPolicy:
    """从 profile 子 dict 构造 ``RetrievalPolicy``。

    English: Parse ScenarioProfile.retrieval mapping into a frozen policy snapshot.

    参数:
        raw: ``retrieval`` 子 dict；非 dict 视为空策略。

    返回:
        含 default_path_prefix / exclude_path_prefixes / section_title_prior 的快照。
    """
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
    """按 scenario_id 加载策略；未知场景返回空策略。

    English: Load retrieval policy from ScenarioRegistry; unknown id → empty policy.

    参数:
        scenario_id: 场景 id；None/未知/缺失 profile 时返回默认空 ``RetrievalPolicy``。
    """
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
    """解析 ``search_sources`` 的有效 path_prefix 与元信息。

    English: Resolve effective path_prefix (model arg or profile default) with meta.

    参数:
        path_prefix: 模型传入；None 时应用 profile 默认。
        scenario_id: 当前场景 id。

    返回:
        ``(effective_prefix, meta)``；meta 含 ``applied_default`` 等审计字段。
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
    """规范化排除前缀列表，非法项跳过。

    English: Normalize exclude path prefixes via normalize_path_prefix; drop invalid.
    """
    out: list[str] = []
    for raw in excludes:
        normalized, err = normalize_path_prefix(str(raw))
        if err or not normalized:
            continue
        out.append(normalized)
    return out


def path_is_excluded(path: str, exclude_prefixes: list[str]) -> bool:
    """路径是否落在任一 exclude 前缀下。

    English: True when path matches any exclude prefix (path_matches_prefix).
    """
    for pref in exclude_prefixes:
        if path_matches_prefix(path, pref):
            return True
    return False


def filter_hits_by_excludes(
    hits: list[Any],
    *,
    scenario_id: str | None,
) -> tuple[list[Any], dict[str, Any]]:
    """按 profile ``exclude_path_prefixes`` 过滤 hits（如 writing 隐藏 seed）。

    English: Drop retrieval hits under excluded prefixes; meta reports removed count.

    参数:
        hits: 检索 hit 对象或 dict 列表（需有 ``path``）。
        scenario_id: 用于加载 profile 排除前缀。

    返回:
        ``(filtered_hits, meta)``。
    """
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
