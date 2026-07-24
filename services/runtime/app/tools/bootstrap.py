from __future__ import annotations

from dataclasses import replace

from app.scenarios.registry import ScenarioProfile
from app.settings import settings
from app.tools.core import tools as core
from app.tools.registry import ON_WRITE_TOOLS, ToolRegistry, ToolSpec


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="read_file",
            description=(
                "Read a file from the workspace. For manuscript.md / draft manuscript, "
                "pass section_id to load one chapter (default lists chapters only); "
                "set full=true only for whole-book review."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "section_id": {
                        "type": "string",
                        "description": "Chapter id inside monofile manuscript (e.g. ch3)",
                    },
                    "full": {
                        "type": "boolean",
                        "description": "Read entire manuscript (review only)",
                    },
                },
                "required": ["path"],
            },
            handler=core.read_file,
        )
    )
    registry.register(
        ToolSpec(
            name="list_dir",
            description=(
                "List one directory's entries (names only). Use to discover structure "
                "before read/write. Prefer drilling into a subdirectory over listing '.' "
                "again. For content search use grep/glob/search_codebase — not list_dir."
            ),
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
            handler=core.list_dir,
        )
    )
    registry.register(
        ToolSpec(
            name="propose_patch",
            description=(
                "Propose a surgical edit: old_text must be an exact unique span in the "
                "current file; new_text replaces only that span (not the whole file). "
                "Prefer this over write_file for existing files. If apply fails, "
                "read_file and retry with a corrected unique span — do not resend blindly."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            handler=core.propose_patch,
        )
    )
    registry.register(
        ToolSpec(
            name="apply_patch",
            description=(
                "Apply an accepted patch. When old_text is set, replaces that unique span; "
                "otherwise writes new_text as the full file"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "new_text": {"type": "string"},
                    "old_text": {"type": "string"},
                    "force_full_replace": {"type": "boolean"},
                },
                "required": ["path", "new_text"],
            },
            handler=core.apply_patch,
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="draft_section",
            description=(
                "Draft or update a chapter. Default monofile: upserts a marked block in "
                ".agent/work/drafts/manuscript.md (append new chapters / replace same section_id). "
                "Pass layout=sections for one-file-per-chapter under .agent/work/drafts/"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "content": {"type": "string"},
                    "layout": {
                        "type": "string",
                        "enum": ["monofile", "sections"],
                        "description": "Override WRITING_MANUSCRIPT_MODE for this call",
                    },
                },
                "required": ["section_id", "content"],
            },
            handler=core.draft_section,
        )
    )
    registry.register(
        ToolSpec(
            name="update_plan",
            description=(
                "Update the visible turn plan / todo checklist. "
                "Call when starting a multi-step task and again whenever a step "
                "begins (status=in_progress) or finishes (status=done|completed). "
                "Replace the full items list each time so the UI stays accurate. "
                "During Plan executing phase, skipping status updates is a failure."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": [
                                        "pending",
                                        "in_progress",
                                        "done",
                                        "completed",
                                        "cancelled",
                                    ],
                                },
                            },
                        },
                    },
                    "summary": {"type": "string"},
                },
                "required": ["items"],
            },
            handler=core.update_plan,
        )
    )
    registry.register(
        ToolSpec(
            name="update_outline",
            description=(
                "Create or update outline.md. Prefer mode=append for long outlines / "
                "batch continuation; replace requires the full outline (or force=true)"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "append"],
                        "default": "replace",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Allow replace that shrinks a large existing outline",
                    },
                },
                "required": ["content"],
            },
            handler=core.update_outline,
        )
    )
    registry.register(
        ToolSpec(
            name="search_sources",
            description=(
                "Hybrid search over workspace sources/ (BM25 + vector). "
                "Library layout (narrow with path_prefix when the type is known): "
                "sources/seed/writing/{persons,periods,dramas,novels,movie}/ for standing "
                "fact corpus; sources/cards/ is pinned style/character material — do not "
                "search cards here; user uploads may appear under other sources/ trees "
                "(e.g. hr/, legal/, writing/). "
                "Prefer read_file when the source path is known. "
                "Optional path_prefix narrows to a subdirectory under sources/ "
                "(e.g. 'seed/writing/dramas', 'hr', or 'sources/hr'); rejects '..' / absolute paths. "
                "Avoid repeating the same query; use at most a few searches per topic."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "path_prefix": {
                        "type": "string",
                        "description": (
                            "Optional directory under sources/ to restrict search. "
                            "Relative path; 'seed/writing/persons' or 'hr' means that tree. "
                            "No '..' or absolute paths."
                        ),
                    },
                },
                "required": ["query"],
            },
            handler=core.search_sources,
        )
    )
    registry.register(
        ToolSpec(
            name="check_citation",
            description=(
                "Verify that a citation_id appears in / is supported by the given source "
                "file. Use after drafting with [cite:…] markers; do not invent citations."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "citation_id": {"type": "string"},
                    "source_path": {"type": "string"},
                },
                "required": ["citation_id", "source_path"],
            },
            handler=core.check_citation,
        )
    )
    registry.register(
        ToolSpec(
            name="grep",
            description=(
                "Regex/search file contents under a path (default '.'). Prefer for exact "
                "symbols, strings, or error text. Use search_codebase for broader semantic "
                "queries; use glob to find files by name pattern."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["pattern"],
            },
            handler=core.grep,
        )
    )
    registry.register(
        ToolSpec(
            name="glob",
            description=(
                "Find files by glob pattern under a path (e.g. '**/*.py', 'src/**/test_*.ts'). "
                "Use when you need paths by name/extension. For content matches use grep; "
                "for semantic discovery use search_codebase."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "limit": {"type": "integer", "default": 100},
                },
                "required": ["pattern"],
            },
            handler=core.glob,
        )
    )
    registry.register(
        ToolSpec(
            name="write_file",
            description=(
                "Create a new file or intentionally overwrite an entire file with content. "
                "Do NOT use for small edits to existing files — use propose_patch or "
                "edit_file instead. Confirm the path with list_dir/glob first when unsure. "
                "Requires approval in agent mode."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=core.write_file,
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="rename_file",
            description=(
                "Rename or move an existing workspace file (path → new_path). "
                "Use for rename-only requests; do NOT export, rewrite, or invent titles. "
                "Fails if destination exists unless overwrite=true. Seed corpus is read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Current relative path",
                    },
                    "new_path": {
                        "type": "string",
                        "description": "Destination relative path (new name and/or folder)",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Replace destination if it already exists",
                        "default": False,
                    },
                },
                "required": ["path", "new_path"],
            },
            handler=core.rename_file,
        )
    )
    registry.register(
        ToolSpec(
            name="edit_file",
            description=(
                "Replace a unique exact text span in an existing file (old_text → new_text). "
                "Same surgical contract as propose_patch; requires approval. Prefer "
                "propose_patch when the UI diff / accept flow matters; use edit_file for "
                "direct in-place edits. If span is missing or not unique, read_file and retry."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            handler=core.edit_file,
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="run_tests",
            description=(
                "Run the project's test command (default pytest -q). Call before claiming "
                "a coding task is done when tests exist, or when the user asks to verify. "
                "Prefer this over ad-hoc run_command for the standard test suite. "
                "Requires approval unless profile overrides."
            ),
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string", "default": "pytest -q"}},
            },
            handler=core.run_tests,
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="read_lints",
            description=(
                "Read lint/diagnostic results for workspace paths (default '.'). "
                "Call after write_file / edit_file / propose_patch on code; fix new issues "
                "you introduced before claiming done. Not a substitute for run_tests."
            ),
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
            handler=core.read_lints,
        )
    )
    registry.register(
        ToolSpec(
            name="export_document",
            description=(
                "Export an explicit ordered set of sections into one markdown file. "
                "Use current_draft for this turn's drafts or confirmed for accepted sections."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "section_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "source": {
                        "type": "string",
                        "enum": ["confirmed", "current_draft"],
                        "default": "current_draft",
                    },
                    "output_path": {
                        "type": "string",
                        "default": "exports/document.md",
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["novel-zh", "essay", "none"],
                        "default": "novel-zh",
                        "description": "Export structure lint profile (docs/14 D6)",
                    },
                },
                "required": ["section_ids"],
            },
            handler=core.export_document,
        )
    )
    registry.register(
        ToolSpec(
            name="search_codebase",
            description=(
                "Semantic / hybrid search over the workspace codebase for a natural-language "
                "or keyword query. Use when the path is unknown or you need related symbols. "
                "Prefer grep for exact string/regex matches; prefer glob for filename patterns; "
                "prefer read_file when the path is already known."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
            handler=core.search_codebase,
        )
    )
    registry.register(
        ToolSpec(
            name="delegate",
            description=(
                "Delegate a sub-task to a specialized sub-agent. "
                "Prefer context_refs/paths (workspace relative paths) over pasting large text into context."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "agent_type": {"type": "string", "default": "explore"},
                    "context": {
                        "type": "string",
                        "default": "",
                        "description": "Short optional notes; keep brief. Prefer context_refs for files.",
                    },
                    "context_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Workspace-relative file paths the sub-agent should read",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Alias of context_refs",
                    },
                },
                "required": ["task"],
            },
            handler=core.delegate,
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="slow_tool",
            description="Simulated long-running tool for cancel tests",
            parameters={
                "type": "object",
                "properties": {"duration_ms": {"type": "integer", "default": 5000}},
            },
            handler=core.slow_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="stub_echo",
            description="Phase 0 compatibility stub tool",
            parameters={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
            handler=core.stub_echo,
        )
    )
    registry.register(
        ToolSpec(
            name="run_command",
            description=(
                "Execute a shell command in the workspace (requires approval). Use for "
                "builds, custom scripts, or non-standard checks. Prefer read_file/grep/glob "
                "for reading files; prefer run_tests for the standard test suite; prefer "
                "write_file/propose_patch/edit_file for file changes — do not use shell "
                "redirection to write code."
            ),
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            handler=core.run_command,
            requires_approval=True,
            timeout_s=settings.tool_default_timeout_seconds,
        )
    )
    from app.tools.core import memory as memory_tools

    registry.register(
        ToolSpec(
            name="remember",
            description=(
                "Store a preference or durable note in a separate memory namespace "
                "(not the sources RAG index). Call only when the user asks to remember."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "namespace": {
                        "type": "string",
                        "default": "prefs",
                        "description": "Logical bucket such as prefs|style|project",
                    },
                    "importance": {"type": "number", "default": 0.5},
                },
                "required": ["text"],
            },
            handler=memory_tools.remember,
        )
    )
    registry.register(
        ToolSpec(
            name="recall",
            description=(
                "On-demand recall from memory namespaces. Do not call every turn — "
                "only when preferences/past notes are relevant."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "namespace": {"type": "string", "default": "prefs"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            handler=memory_tools.recall,
        )
    )
    from app.tools.core import records as record_tools

    registry.register(
        ToolSpec(
            name="search_records",
            description=(
                "Search business/record tables (stub until backends are wired). "
                "Rule-routed channels with per-channel timeouts; not for sources RAG."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "channel": {"type": "string", "default": "auto"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            handler=record_tools.search_records,
        )
    )
    return registry


# Dropped late in a turn / after successful export (docs/13 S3 A19). Pure rules.
_LATE_STAGE_DROP = frozenset({"search_sources", "delegate", "remember", "recall"})

# Plan planning phase: checklist only — no retrieve/write/exec (docs/25 consent gate).
PLANNING_TOOL_ALLOWLIST = frozenset(
    {
        "update_plan",
        "stub_echo",
    }
)


def tool_scope(
    profile: ScenarioProfile,
    registry: ToolRegistry,
    *,
    plan_phase: str | None = None,
) -> list[ToolSpec]:
    """Filter tools by scenario profile; optionally harden for Plan planning phase."""
    names = list(profile.tool_names)
    if "stub_echo" not in names:
        names.append("stub_echo")
    phase = (plan_phase or "").strip().lower() or None
    if phase == "planning":
        names = [n for n in names if n in PLANNING_TOOL_ALLOWLIST]
        # Ensure plan tool is always present when planning.
        if "update_plan" not in names and registry.get("update_plan") is not None:
            names.append("update_plan")
    specs: list[ToolSpec] = []
    for name in names:
        base = registry.get(name)
        if base is None:
            continue
        requires = base.requires_approval
        override = profile.approval_overrides.get(name)
        if override == "always":
            requires = True
        elif override == "never":
            requires = False
        elif override == "on_write":
            requires = name in ON_WRITE_TOOLS
        specs.append(replace(base, requires_approval=requires))
    return specs


def stage_tool_scope(specs: list[ToolSpec], *, step_count: int, max_steps: int, delivery: dict | None) -> list[ToolSpec]:
    """Shrink tools JSON in late steps; no LLM routing."""
    delivery_ok = isinstance(delivery, dict) and str(delivery.get("delivery_status", "")) in {
        "ok",
        "warning",
    }
    remaining = max_steps - step_count
    late = step_count >= 8 and remaining <= 6
    if not delivery_ok and not late:
        return specs
    return [spec for spec in specs if spec.name not in _LATE_STAGE_DROP]
