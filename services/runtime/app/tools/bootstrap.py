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
                "Read a file from the workspace. Use when the path is known "
                "(including @path refs or hot_files). Prefer this over search_sources for known paths."
            ),
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=core.read_file,
        )
    )
    registry.register(
        ToolSpec(
            name="list_dir",
            description="List directory entries in the workspace",
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
            description="Propose a patch for user review (does not write file)",
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
            description="Apply an accepted patch to the workspace",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}, "new_text": {"type": "string"}},
                "required": ["path", "new_text"],
            },
            handler=core.apply_patch,
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="draft_section",
            description="Draft or update a document section",
            parameters={
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["section_id", "content"],
            },
            handler=core.draft_section,
        )
    )
    registry.register(
        ToolSpec(
            name="update_plan",
            description="Update the turn plan / todo list",
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
                                    "enum": ["pending", "in_progress", "done"],
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
            description="Create or update document outline (outline.md)",
            parameters={
                "type": "object",
                "properties": {"content": {"type": "string"}},
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
                "Prefer read_file when the source path is known. "
                "Optional path_prefix narrows to a subdirectory under sources/ "
                "(e.g. 'hr' or 'sources/hr'); rejects '..' / absolute paths. "
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
                            "Relative path; 'hr' means sources/hr. No '..' or absolute paths."
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
            description="Verify a citation against a source file",
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
            description="Search file contents in the workspace",
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
            description="Find files matching a glob pattern under a path",
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
            description="Create or overwrite a workspace file",
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
            name="edit_file",
            description="Replace a unique text span in an existing file",
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
            description="Run project tests (simulated in Phase 1)",
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
            description="Read lint/diagnostic results for workspace paths",
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
            description="Search the codebase for a query string",
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
            description="Execute a shell command (requires approval)",
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


def tool_scope(profile: ScenarioProfile, registry: ToolRegistry) -> list[ToolSpec]:
    names = list(profile.tool_names)
    if "stub_echo" not in names:
        names.append("stub_echo")
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


# Dropped late in a turn / after successful export (docs/13 S3 A19). Pure rules.
_LATE_STAGE_DROP = frozenset({"search_sources", "delegate", "remember", "recall"})


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
