"""Work-scoped manuscript index for writing turns (docs/23 WW2).

Pure filesystem metadata — no LLM. Hard-capped for R1–R3.
"""

from __future__ import annotations

from pathlib import Path

from app.settings import settings
from app.writing.manuscript import (
    confirmed_manuscript_rel,
    draft_manuscript_rel,
    list_section_ids,
    manuscript_mode,
)


def _list_md_names(dir_path: Path) -> list[str]:
    if not dir_path.is_dir():
        return []
    names: list[str] = []
    for p in sorted(dir_path.iterdir()):
        if p.is_file() and p.suffix == ".md" and not p.name.startswith("."):
            names.append(p.name)
    return names


def _file_note(root: Path, rel: str) -> str:
    path = root / rel
    if not path.is_file():
        return f"`{rel}` (missing)"
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    ids: list[str] = []
    try:
        ids = list_section_ids(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        pass
    if ids:
        shown = ", ".join(ids[:12])
        extra = f" (+{len(ids) - 12})" if len(ids) > 12 else ""
        return f"`{rel}` ({size} bytes; sections: {shown}{extra})"
    return f"`{rel}` ({size} bytes)"


def build_work_index(
    *,
    workspace_root: Path | None = None,
    max_chars: int | None = None,
    message: str = "",
) -> str:
    """Return a short markdown block describing the current work tree."""
    root = Path(workspace_root or settings.workspace_root).resolve()
    budget = max_chars if max_chars is not None else settings.writing_work_index_max_chars
    budget = max(200, int(budget))
    mode = manuscript_mode()
    ms = confirmed_manuscript_rel()
    draft_ms = draft_manuscript_rel()

    outline = root / "outline.md"
    sections = _list_md_names(root / "sections")
    drafts = _list_md_names(root / "drafts")

    lines = [
        "## Work index",
        (
            f"Default layout **{mode}**: chapters append into `{ms}` "
            f"(draft: `{draft_ms}`). Optional split files under `sections/`."
            if mode == "monofile"
            else "Layout **sections**: one file per chapter under `sections/` and `drafts/`."
        ),
        "Sessions are conversation threads over this work — not chapter owners.",
    ]
    if outline.is_file():
        try:
            size = outline.stat().st_size
        except OSError:
            size = 0
        lines.append(f"- outline: `outline.md` ({size} bytes)")
    else:
        lines.append("- outline: (missing)")

    lines.append(f"- manuscript: {_file_note(root, ms)}")
    lines.append(f"- manuscript draft: {_file_note(root, draft_ms)}")

    if sections:
        joined = ", ".join(f"`sections/{n}`" for n in sections[:16])
        extra = f" (+{len(sections) - 16} more)" if len(sections) > 16 else ""
        lines.append(f"- split confirmed: {joined}{extra}")

    other_drafts = [n for n in drafts if n != Path(draft_ms).name]
    if other_drafts:
        joined = ", ".join(f"`drafts/{n}`" for n in other_drafts[:12])
        lines.append(f"- split drafts: {joined}")

    if mode == "monofile":
        from app.writing.occupy import manuscript_is_occupied, wants_new_piece

        draft_text = ""
        draft_path = root / draft_ms
        if draft_path.is_file():
            try:
                draft_text = draft_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        if wants_new_piece(message) and manuscript_is_occupied(draft_text):
            lines.append(
                "Prior draft is a different story. First `draft_section` this Turn "
                "uses occupy=fresh: archives to `drafts/archive/`, then writes only "
                "the new piece at `ch1`. Do not append as a later chapter."
            )
        else:
            lines.append(
                f"Continue writing with `draft_section` (appends/replaces a chapter heading in `{draft_ms}`); "
                f"promote into `{ms}` via `propose_patch`. Read only the chapter you need — not the whole book."
            )
    else:
        lines.append(
            "Continue a chapter with `read_file` on its draft or section path; "
            "promote into `sections/` via `propose_patch`."
        )
    text = "\n".join(lines)
    if len(text) <= budget:
        return text
    return text[: budget - 1].rstrip() + "…"


def format_work_index_block(
    *,
    workspace_root: Path | None = None,
    max_chars: int | None = None,
    message: str = "",
) -> str:
    return build_work_index(
        workspace_root=workspace_root,
        max_chars=max_chars,
        message=message,
    )
