"""Promote eval thinking JSONL out of the SWE worktree."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID


def coding_case_done_message(
    *,
    done: int,
    total: int,
    iid: str,
    status: str,
    bucket: str | None = None,
    patch_source: str | None = None,
    steps: int | None = None,
    elapsed_s: float | None = None,
    error: str | None = None,
) -> str:
    """Stable log line for Ops live parse (steps / elapsed_s per instance)."""
    parts = [f"[L1] coding {done}/{total} {iid} status={status}"]
    if bucket:
        parts.append(f"bucket={bucket}")
    if patch_source:
        parts.append(f"patch_source={patch_source}")
    if steps is not None:
        parts.append(f"steps={int(steps)}")
    if elapsed_s is not None:
        parts.append(f"elapsed_s={float(elapsed_s):.1f}")
    if error:
        parts.append(f"error={str(error)[:160]}")
    return " ".join(parts)


def _thinking_sidecar_src(work_root: Path | str, turn_id: UUID | str) -> Path:
    return Path(work_root) / ".agent" / "thinking" / f"{turn_id}.jsonl"


def promote_thinking_sidecar(
    *,
    session_dir: Path,
    iid: str,
    turn_id: UUID | str,
    work_root: Path | str,
) -> Path | None:
    """Copy eval thinking JSONL out of the worktree before cleanup."""
    src = _thinking_sidecar_src(work_root, turn_id)
    if not src.is_file() or src.stat().st_size <= 0:
        return None
    dest_dir = Path(session_dir) / "thinking"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{iid}.jsonl"
    with src.open(encoding="utf-8") as fh, dest.open("w", encoding="utf-8") as out:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            row["instance_id"] = iid
            row["turn_id"] = str(turn_id)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    return dest if dest.is_file() and dest.stat().st_size > 0 else None


def assemble_thinking_jsonl(session_dir: Path) -> Path | None:
    parts = sorted((Path(session_dir) / "thinking").glob("*.jsonl"))
    if not parts:
        return None
    out = Path(session_dir) / "thinking.jsonl"
    with out.open("w", encoding="utf-8") as dest:
        for part in parts:
            dest.write(part.read_text(encoding="utf-8"))
    return out if out.is_file() and out.stat().st_size > 0 else None
