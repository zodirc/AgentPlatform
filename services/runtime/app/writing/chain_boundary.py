"""最小写作链的数据边界。运行时不从快照目录读提示。

回滚点是本文件描述的接口，加上 scenarios/writing/templates 里的现行提示。
"""

from __future__ import annotations

WRITER_SEES = (
    "user_message",
    "chapter_facts",
    "previous_tail",
    "confirmed_canon",
    "confirmed_voice",
    "length_and_format",
)

WRITER_HIDES = (
    "rewards",
    "penalties",
    "net_signal",
    "commitment",
    "fragment_obligation",
    "detector_names",
    "repair_lecture",
    "spine",
    "stage_abstract",
    "serial_subtype",
)

CANON_FACT_FIELDS = (
    "id",
    "kind",
    "subject",
    "text",
    "source_section",
    "evidence",
    "status",
    "certainty",
)

CANON_KINDS = (
    "character",
    "relation",
    "object",
    "rule",
    "promise",
    "speech",
    "guess",
    "state",
)

VOICE_MARK_FIELDS = (
    "section_id",
    "kind",
    "excerpt",
    "note",
    "scope",
    "paired_excerpt",
    "source",
)

EDITOR_REPORT_FIELDS = (
    "section_id",
    "flags",
    "keep",
    "telemetry",
)

REVISION_REQUEST_FIELDS = (
    "original",
    "context",
    "problem",
    "confirmed_voice",
    "candidates",
)

TOOL_PHASES = {
    "writer": ("draft_section", "read_file", "propose_patch", "update_outline"),
    "editor": ("read_file", "grep", "glob", "editor_report"),
    "revision": ("read_file", "grep", "glob"),
}
