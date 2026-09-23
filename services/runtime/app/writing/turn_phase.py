"""长篇开写相位谓词：选书 / 大纲等人 / 成章。闸与 handler 共用。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from app.writing.text_metrics import looks_like_chapter_draft, visible_chars

ContinueKind = Literal["", "new_chapter", "append_this"]

_PICK_TOKEN = re.compile(
    r"(?:按开篇候选|采用此开篇|按此开篇)[「『][^」』]+[」』]"
)
_COMMIT_POND_RE = re.compile(r"按开篇候选|采用此开篇|按此开篇")
_ALREADY_NAMED_RE = re.compile(
    r"名叫|叫[\u4e00-\u9fff]{1,8}|像.{1,10}写|风格.{0,4}是|"
    r"凡人流|系统流|克系|灵异|探案"
)
_BROWSE_RE = re.compile(r"看看|发散|几种|换个开|什么风格|先看|我要其他的|都不合适")
_MID_BOOK_RE = re.compile(
    r"续写|接着写|继续写|往下写|"
    r"第\s*[二三四五六七八九十百千零〇两\d]{1,4}\s*章|"
    r"(?:^|\b)ch([2-9]|\d{2,})\b",
    re.I,
)
_WRITE_GO_RE = re.compile(r"写第一章|开始写|成章")
_AFTER_OUTLINE_GO_RE = re.compile(
    r"^(?:继续|好|可以|开始|开始写|按这个写)[。.!！]?$"
)
_NEXT_CHAPTER_RE = re.compile(r"下一章|下章")
_APPEND_THIS_RE = re.compile(r"续写本章|把这章写完|章尾|补这章")
_BARE_CONTINUE_RE = re.compile(r"接着写|继续写|往下写|续写")
_JOB_STUB_RE = re.compile(
    r"往哪走即可|这场干什么即可|顶点可以后补|几句这场干什么即可"
)
_NOT_JOB_HEAD_RE = re.compile(
    r"这本书|主线|风格契约|开篇几章|开篇三章|章节备忘|世界契约|世界入口|当前阶段|远处"
)
_CH_ID_RE = re.compile(r"^ch(\d+)$", re.I)
OUTLINE_AWAIT_HINT = (
    "纲已写入 outline.md。世界入口和当前阶段说明读者怎么进入、这一段留下什么变化；"
    "近处章节各有一句作用。可以说写第一章、改纲，或先补当前章段。"
)
# 与 text_metrics.OUTLINE_MIN_VISIBLE 同一道「章段过薄」门槛。
NEAR_JOB_MIN = 80
NEED_OUTLINE_SUMMARY = (
    "长篇还没有当前章段。先 update_outline 写下这一章的事实，再 draft_section。"
)
NEXT_CHAPTER_NOT_APPEND = (
    "下一章用新的 section_id 写，不要 mode=append 接到上一章末尾。"
)
NEED_CHAPTER_JOB = (
    "这一章的当前章段还不够开写。给当前章节写一段开写便条："
    "写清本章主要面对的一件事，以及几项会互相影响的具体事实；"
    "前一件事发生后，人物对后一件事的判断或做法应当有所改变。"
    "不要把秘密、期限和反转并排堆成清单。不要概括世界观，不要按步骤安排正文，也不要预定章末画面。"
    "通常一百二十到二百五十字。情节还没确定的地方留白。"
)


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def _read_outline(workspace_root: Path | None = None, outline: str | None = None) -> str:
    if outline is not None:
        return outline
    path = _workspace(workspace_root) / "outline.md"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def last_chapter_num(section_ids: list[str] | None) -> int:
    best = 0
    for sid in section_ids or []:
        m = _CH_ID_RE.match(str(sid).strip())
        if m:
            best = max(best, int(m.group(1)))
    return best


def has_manuscript(*, workspace_root: Path | None = None) -> bool:
    from app.writing.manuscript import extract_section, list_section_ids, load_manuscript_doc

    doc, _rel = load_manuscript_doc(workspace_root)
    if not doc:
        return False
    for sid in list_section_ids(doc):
        if visible_chars(extract_section(doc, sid) or "") > 0:
            return True
    return False


def manuscript_section_ids(*, workspace_root: Path | None = None) -> list[str]:
    from app.writing.manuscript import list_section_ids, load_manuscript_doc

    doc, _rel = load_manuscript_doc(workspace_root)
    return list_section_ids(doc) if doc else []


def has_chapter_jobs(outline: str = "") -> bool:
    from app.writing.outline_arc import _chapter_section_id, _chapter_spans

    for title, body in _chapter_spans(outline or ""):
        head = (title or "").strip()
        if _NOT_JOB_HEAD_RE.search(head):
            continue
        sid = _chapter_section_id(head)
        if not sid and not re.search(r"^第.+章", head) and not head.lower().startswith("ch"):
            continue
        cleaned = _JOB_STUB_RE.sub("", body or "")
        if visible_chars(cleaned) >= 16:
            return True
    return False


def chapter_job_visible(outline: str, section_id: str) -> int:
    from app.writing.outline_arc import extract_outline_job

    job = extract_outline_job(outline or "", section_id)
    cleaned = _JOB_STUB_RE.sub("", job or "")
    return visible_chars(cleaned)


def has_next_chapter_job(outline: str, last_n: int) -> bool:
    nxt = f"ch{last_n + 1}" if last_n else "ch2"
    return chapter_job_visible(outline, nxt) >= NEAR_JOB_MIN


def write_intent(
    message: str,
    *,
    has_chapter_jobs_flag: bool = False,
    has_manuscript_flag: bool = False,
) -> bool:
    text = _PICK_TOKEN.sub("", message or "").strip()
    if not text:
        return False
    if looks_like_chapter_draft(text) or _WRITE_GO_RE.search(text):
        return True
    if has_chapter_jobs_flag and not has_manuscript_flag:
        return bool(_AFTER_OUTLINE_GO_RE.match(text))
    return False


def continue_kind(
    message: str,
    *,
    has_manuscript_flag: bool,
    outline: str = "",
    section_ids: list[str] | None = None,
) -> ContinueKind:
    if not has_manuscript_flag:
        return ""
    text = message or ""
    last_n = last_chapter_num(section_ids)
    if _NEXT_CHAPTER_RE.search(text) and not _APPEND_THIS_RE.search(text):
        return "new_chapter"
    if _APPEND_THIS_RE.search(text):
        return "append_this"
    if _BARE_CONTINUE_RE.search(text):
        if has_next_chapter_job(outline, last_n):
            return "new_chapter"
        return "append_this"
    return ""


def resolve_scope(
    message: str = "",
    *,
    outline: str = "",
    workspace_root: Path | None = None,
) -> str:
    from app.writing.book_scope import resolve_book_scope
    from app.writing.opening_ponds import load_committed_pond

    if _COMMIT_POND_RE.search(message or "") or load_committed_pond(
        workspace_root=workspace_root
    ):
        from app.writing.book_scope import explicit_book_scope

        named = explicit_book_scope(message)
        if named != "short":
            return "long"
    scope, _src = resolve_book_scope(
        message, outline=outline, workspace_root=workspace_root
    )
    return scope


def picking(
    message: str = "",
    *,
    outline: str = "",
    workspace_root: Path | None = None,
) -> bool:
    from app.writing.opening_ponds import load_committed_pond, wants_more_ponds
    from app.writing.outline_arc import outline_style_committed

    text = (message or "").strip()
    if wants_more_ponds(text):
        return True
    if _COMMIT_POND_RE.search(text):
        return False
    if load_committed_pond(workspace_root=workspace_root):
        return False
    if _ALREADY_NAMED_RE.search(text):
        return False
    if has_chapter_jobs(outline):
        return False
    if resolve_scope(text, outline=outline, workspace_root=workspace_root) != "long":
        return False
    if _BROWSE_RE.search(text):
        return True
    if _MID_BOOK_RE.search(text):
        return False
    return not outline_style_committed(outline or "")


def snapshot(
    message: str = "",
    *,
    workspace_root: Path | None = None,
    outline: str | None = None,
) -> dict[str, Any]:
    md = _read_outline(workspace_root, outline)
    jobs = has_chapter_jobs(md)
    prose = has_manuscript(workspace_root=workspace_root)
    ids = manuscript_section_ids(workspace_root=workspace_root) if prose else []
    scope = resolve_scope(message, outline=md, workspace_root=workspace_root)
    is_picking = picking(message, outline=md, workspace_root=workspace_root)
    intent = write_intent(
        message, has_chapter_jobs_flag=jobs, has_manuscript_flag=prose
    )
    mid = bool(_MID_BOOK_RE.search(message or ""))
    wait = (
        scope == "long"
        and not is_picking
        and not prose
        and not jobs
        and not mid
    )
    return {
        "scope": scope,
        "picking": is_picking,
        "has_manuscript": prose,
        "has_chapter_jobs": jobs,
        "write_intent": intent,
        "continue_kind": continue_kind(
            message,
            has_manuscript_flag=prose,
            outline=md,
            section_ids=ids,
        ),
        "outline_wait": wait,
        "outline_ready_wait": (
            scope == "long" and not prose and jobs and not intent
        ),
        "section_ids": ids,
        "outline": md,
    }


def should_gate_outline_wait(
    message: str = "",
    *,
    workspace_root: Path | None = None,
) -> bool:
    snap = snapshot(message, workspace_root=workspace_root)
    return bool(snap["outline_wait"] and not snap["write_intent"])


def should_await_outline_direction(
    message: str = "",
    *,
    outline: str = "",
    workspace_root: Path | None = None,
) -> bool:
    """update_outline 成功后是否停：本轮无成章意图，且纲里已经有章职。"""
    snap = snapshot(message, workspace_root=workspace_root, outline=outline)
    if snap["write_intent"] or snap["has_manuscript"] or snap["picking"]:
        return False
    if snap["scope"] != "long":
        return False
    return bool(snap["has_chapter_jobs"])


def draft_need_outline_error(
    message: str = "",
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    snap = snapshot(message, workspace_root=workspace_root)
    if not snap["outline_wait"]:
        return None
    return {
        "status": "error",
        "error": "need_outline",
        "summary": NEED_OUTLINE_SUMMARY,
    }


def _opening_section_id(message: str, snap: dict[str, Any]) -> str:
    """要新开的那一章。章尾续写、以及还没有大纲的探测稿，返回空。"""
    if snap.get("continue_kind") == "append_this" or snap.get("picking"):
        return ""
    if snap.get("scope") != "long":
        return ""
    ids = list(snap.get("section_ids") or [])
    outline = str(snap.get("outline") or "")
    from app.writing.focus import infer_focus_section_id

    focus = infer_focus_section_id(message, ids, outline=outline) or ""
    if snap.get("continue_kind") == "new_chapter":
        if focus and focus not in ids:
            return focus
        n = last_chapter_num(ids)
        return f"ch{n + 1}" if n else "ch2"
    if snap.get("has_manuscript") and focus and focus not in ids:
        return focus
    if (
        snap.get("write_intent")
        and not snap.get("has_manuscript")
        and outline.strip()
    ):
        return focus or "ch1"
    return ""


def draft_need_chapter_job_error(
    message: str = "",
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    snap = snapshot(message, workspace_root=workspace_root)
    sid = _opening_section_id(message, snap)
    if not sid:
        return None
    if chapter_job_visible(str(snap.get("outline") or ""), sid) >= NEAR_JOB_MIN:
        return None
    return {
        "status": "error",
        "error": "need_chapter_job",
        "section_id": sid,
        "summary": NEED_CHAPTER_JOB,
    }


def draft_next_chapter_append_error(
    message: str = "",
    *,
    mode: str = "",
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    if mode != "append":
        return None
    snap = snapshot(message, workspace_root=workspace_root)
    if snap["continue_kind"] != "new_chapter":
        return None
    return {
        "status": "error",
        "error": "next_chapter_not_append",
        "summary": NEXT_CHAPTER_NOT_APPEND,
    }
