"""Section-scoped span replace for monofile / per-chapter drafts."""

from __future__ import annotations

from app.writing.manuscript import extract_section, list_section_ids, upsert_section


def replace_span_in_manuscript(
    document: str,
    *,
    section_id: str,
    old_text: str,
    new_text: str,
) -> str | None:
    """Replace ``old_text`` within one chapter body; dedupe all in-section hits."""
    old = old_text or ""
    if not old:
        return None
    body = ""
    if section_id and section_id in list_section_ids(document):
        body = extract_section(document, section_id) or ""
    else:
        body = document
    if old not in body:
        return None
    count = body.count(old)
    new_body = body.replace(old, new_text or "", 1 if count == 1 else count)
    if section_id and section_id in list_section_ids(document):
        return upsert_section(document, section_id, new_body)
    return new_body


def span_replaceable_in_manuscript(
    document: str,
    *,
    section_id: str,
    old_text: str,
) -> bool:
    old = old_text or ""
    if not old:
        return False
    if section_id and section_id in list_section_ids(document):
        body = extract_section(document, section_id) or ""
        return old in body
    return old in document
