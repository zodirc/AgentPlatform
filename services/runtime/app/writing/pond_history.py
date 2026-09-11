"""被「我要其他的」拒掉的开篇组：本 workspace 内累加，勾选成功后清空。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

OPENING_PONDS_REJECTED_REL = Path(".agent") / "work" / "opening_ponds_rejected.jsonl"


def _workspace(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.tenant_context import current_work_root_path

    return current_work_root_path()


def rejected_ponds_path(workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / OPENING_PONDS_REJECTED_REL


def _as_items(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [it for it in raw if isinstance(it, dict) and str(it.get("title") or "").strip()]


def append_rejected_ponds(
    group: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> None:
    items = _as_items(group.get("items"))
    if len(items) < 2:
        return
    ponds_id = str(group.get("ponds_id") or "")
    path = rejected_ponds_path(workspace_root)
    existing = load_rejected_pond_groups(workspace_root=workspace_root)
    if ponds_id and existing and str(existing[-1].get("ponds_id") or "") == ponds_id:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ponds_id": ponds_id or f"rejected-{len(existing) + 1}",
        "summary": str(group.get("summary") or ""),
        "items": items,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_rejected_pond_groups(
    *, workspace_root: Path | None = None
) -> list[dict[str, Any]]:
    path = rejected_ponds_path(workspace_root)
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    groups: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        items = _as_items(data.get("items"))
        if len(items) < 2:
            continue
        groups.append(
            {
                "ponds_id": str(data.get("ponds_id") or "rejected"),
                "summary": str(data.get("summary") or ""),
                "items": items,
            }
        )
    return groups


def load_rejected_pond_items(
    *, workspace_root: Path | None = None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in load_rejected_pond_groups(workspace_root=workspace_root):
        out.extend(group["items"])
    return out


def flatten_rejected_groups(
    groups: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in groups:
        out.extend(_as_items(group.get("items")))
    return out


def clear_rejected_ponds(*, workspace_root: Path | None = None) -> bool:
    path = rejected_ponds_path(workspace_root)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False
