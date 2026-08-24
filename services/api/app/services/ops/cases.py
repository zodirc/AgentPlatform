"""Ops Golden/CI 评测用例 YAML 目录与加载。

从 ``settings.ops_eval_golden_dir``（或 dev fallback ``eval/golden``）扫描
``*.yaml``，支持 scenario/phase/tag 过滤。
"""

from __future__ import annotations
from typing import Any

import yaml

from app.settings import settings


def golden_root() -> Path:
    """解析 Golden 用例根目录（compose 或 dev fallback）。

    返回:
        存在的目录 Path；均不存在时返回配置路径（可能非目录）。
    """
    path = Path(settings.ops_eval_golden_dir)
    if path.is_dir():
        return path
    # Dev fallback: repo layout when running api outside compose.
    candidates = [
        Path(__file__).resolve().parents[5] / "eval" / "golden",
        Path("/app/eval/golden"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return path


def list_cases(
    *,
    scenario: str | None = None,
    phase: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """列出 Golden YAML 用例摘要。

    参数:
        scenario: 过滤 ``scenario_id``。
        phase: 过滤 ``phase`` 字段。
        tag: 要求 tags 包含该字符串。

    返回:
        case dict 列表（id/path/scenario_id/phase/tags 等）。
    """
    root = golden_root()
    if not root.is_dir():
        return []
    cases: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        case_id = str(data.get("id") or path.stem)
        tags = [str(t) for t in (data.get("tags") or [])]
        scenario_id = str(data.get("scenario_id") or "")
        phase_val = data.get("phase")
        phase_str = str(phase_val) if phase_val is not None else ""
        if scenario and scenario_id != scenario:
            continue
        if phase and phase_str != phase:
            continue
        if tag and tag not in tags:
            continue
        cases.append(
            {
                "id": case_id,
                "path": str(path.relative_to(root)),
                "scenario_id": scenario_id,
                "phase": phase_str,
                "tags": tags,
                "description": str(data.get("description") or ""),
                "model_mode": data.get("model_mode"),
            }
        )
    return cases


def load_case(case_id: str) -> tuple[Path, dict[str, Any]]:
    """按 id 加载单个 Golden 用例 YAML。

    参数:
        case_id: 用例 ``id`` 或文件 stem。

    返回:
        ``(yaml_path, parsed_dict)``。

    异常:
        FileNotFoundError: 未找到匹配用例。
    """
    root = golden_root()
    for path in root.rglob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if str(data.get("id") or path.stem) == case_id:
            return path, data
    raise FileNotFoundError(f"case not found: {case_id}")
