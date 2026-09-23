"""被「我要其他的」拒掉的开篇组：本 workspace 内累加，勾选成功后清空。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.writing.work_reconstruction import candidate_fingerprint

OPENING_PONDS_REJECTED_REL = Path(".agent") / "work" / "opening_ponds_rejected.jsonl"
_SLOT_ID_RE = re.compile(r"c\d{2,}")


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


def pond_title_key(item: Mapping[str, Any] | dict[str, Any]) -> str:
    return str(item.get("title") or item.get("id") or "").strip().casefold()


@dataclass
class CandidateExclude:
    ids: set[str] = field(default_factory=set)
    fingerprints: set[str] = field(default_factory=set)
    titles: set[str] = field(default_factory=set)


def _add_exclude_item(exclude: CandidateExclude, item: Mapping[str, Any]) -> None:
    sample_id = str(item.get("id") or item.get("sample_id") or "").strip()
    if sample_id and not _SLOT_ID_RE.fullmatch(sample_id):
        exclude.ids.add(sample_id)
    title = pond_title_key(item)
    if title:
        exclude.titles.add(title)
    for part in (
        item.get("raw"),
        item.get("work"),
        item.get("opening"),
        item.get("pitch"),
    ):
        fp = candidate_fingerprint(str(part or ""))
        if fp:
            exclude.fingerprints.add(fp)


def load_candidate_excludes(*, workspace_root: Path | None = None) -> CandidateExclude:
    """当前池 + 已拒池：id / 指纹 / 书名。只用于硬排除，不进 child prompt。"""
    exclude = CandidateExclude()
    from app.writing.opening_ponds import load_opening_ponds

    current = load_opening_ponds(workspace_root=workspace_root)
    if current:
        for item in current.get("items") or []:
            if isinstance(item, dict):
                _add_exclude_item(exclude, item)
    for item in load_rejected_pond_items(workspace_root=workspace_root):
        _add_exclude_item(exclude, item)
    return exclude


def seen_pond_title_keys(*, workspace_root: Path | None = None) -> set[str]:
    """当前池 + 已拒池的书名。新采样按书名硬排除。"""
    keys: set[str] = set()
    from app.writing.opening_ponds import load_opening_ponds

    current = load_opening_ponds(workspace_root=workspace_root)
    if current:
        for item in current.get("items") or []:
            if isinstance(item, dict):
                key = pond_title_key(item)
                if key:
                    keys.add(key)
    for item in load_rejected_pond_items(workspace_root=workspace_root):
        key = pond_title_key(item)
        if key:
            keys.add(key)
    return keys


def drop_seen_pond_items(
    items: Sequence[Mapping[str, Any]],
    seen: set[str],
) -> list[dict[str, Any]]:
    if not seen:
        return [dict(it) for it in items]
    out: list[dict[str, Any]] = []
    for item in items:
        key = pond_title_key(item)
        if key and key in seen:
            continue
        out.append(dict(item))
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
