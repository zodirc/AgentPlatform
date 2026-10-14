"""当前作品上最近一次 Plan 与待定修订。两只接头用它核对意图里的 id。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PLAN_REL = Path(".agent") / "work" / "turn_plan.json"
_PATCHES_REL = Path(".agent") / "work" / "pending_patches.json"


def _root(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.tenant_context import current_work_root_path

    return current_work_root_path()


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, body: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def save_turn_plan(plan: dict[str, Any], *, workspace_root: Path | None = None) -> None:
    plan_id = str(plan.get("plan_id") or "").strip()
    if not plan_id:
        return
    _write(
        _root(workspace_root) / _PLAN_REL,
        {
            "plan_id": plan_id,
            "items": plan.get("items") if isinstance(plan.get("items"), list) else [],
            "summary": str(plan.get("summary") or ""),
            "awaiting_consent": bool(plan.get("awaiting_consent")),
        },
    )


def load_turn_plan(*, workspace_root: Path | None = None) -> dict[str, Any] | None:
    data = _read(_root(workspace_root) / _PLAN_REL)
    if not data or not str(data.get("plan_id") or "").strip():
        return None
    return data


def remember_pending_patch(patch: dict[str, Any], *, workspace_root: Path | None = None) -> None:
    patch_id = str(patch.get("patch_id") or "").strip()
    if not patch_id or str(patch.get("status") or "") != "pending":
        return
    path = _root(workspace_root) / _PATCHES_REL
    data = _read(path) or {}
    rows = data.get("patches")
    patches = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    patches = [row for row in patches if str(row.get("patch_id") or "") != patch_id]
    patches.append(
        {
            "patch_id": patch_id,
            "path": str(patch.get("path") or ""),
            "old_text": str(patch.get("old_text") or ""),
            "summary": str(patch.get("summary") or ""),
            "status": "pending",
        }
    )
    _write(path, {"patches": patches})


def drop_pending_patch(
    *,
    patch_id: str = "",
    path: str = "",
    old_text: str = "",
    workspace_root: Path | None = None,
) -> None:
    file_path = _root(workspace_root) / _PATCHES_REL
    data = _read(file_path)
    if not data:
        return
    rows = data.get("patches")
    patches = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    kept: list[dict[str, Any]] = []
    for row in patches:
        same_id = patch_id and str(row.get("patch_id") or "") == patch_id
        same_span = path and str(row.get("path") or "") == path and str(row.get("old_text") or "") == old_text
        if same_id or same_span:
            continue
        kept.append(row)
    _write(file_path, {"patches": kept})


def latest_pending_patch(*, workspace_root: Path | None = None) -> dict[str, Any] | None:
    data = _read(_root(workspace_root) / _PATCHES_REL)
    if not data:
        return None
    rows = data.get("patches")
    if not isinstance(rows, list):
        return None
    pending = [row for row in rows if isinstance(row, dict) and str(row.get("patch_id") or "").strip()]
    return pending[-1] if pending else None


def pending_patch(patch_id: str, *, workspace_root: Path | None = None) -> dict[str, Any] | None:
    wanted = str(patch_id or "").strip()
    if not wanted:
        return None
    data = _read(_root(workspace_root) / _PATCHES_REL)
    if not data:
        return None
    rows = data.get("patches")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("patch_id") or "") == wanted:
            return row
    return None
