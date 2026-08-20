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
                "Read a file from the workspace (preferred over any shell paging). "
                "Omit limit unless the file is very large. Summary (complete) / "
                "whole_file_complete=true means the whole file is in hand — stop reading "
                "that path this Turn (runtime enforces this). Tail windows that reach EOF "
                "use (eof_from_offset), not (complete). If truncated=true, continue with "
                "next_offset only; code files also include an outline of defs/classes to "
                "navigate without blind paging. Never head/tail/sed/cat. Optional offset "
                "(1-based) / limit for large files. For manuscript.md / draft manuscript, "
                "pass section_id to load one chapter (default lists chapters only); set "
                "full=true only for whole-book review."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {
                        "type": "integer",
                        "description": "1-based start line (default 1). Use next_offset from a truncated read to continue.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to return from offset. Omit to read until EOF or the char budget.",
                    },
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
                "List one directory's entries (names only). Use only for a specific "
                "subdirectory you already care about. Do NOT list '.' / repo root to "
                "tour the project — read the issue/problem.md and use "
                "goto_definition/grep/glob instead. For content search use grep — not list_dir."
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
                "Queue a surgical edit for UI diff / accept flow (writing / intel): old_text "
                "must be an exact unique span; new_text replaces only that span. Does NOT "
                "modify the file by itself — status stays pending until apply_patch or user "
                "accept (writing may auto-apply). Prechecks applyability (unique span; git "
                "apply --check when the worktree is a git repo) and returns status=error with "
                "apply_check_error if it would not apply — re-read and retry, do not resend "
                "the same span. Not available in agent mode — use edit_file there."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "summary": {"type": "string"},
                    "fragment": {
                        "type": "string",
                        "enum": [
                            "plot_progress",
                            "worldview_texture",
                            "climax_beat",
                            "battle_action",
                            "dialogue_dyad",
                            "mixed",
                        ],
                        "description": "Scene fragment type for writing_signals on applied prose",
                    },
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
                "drafts/manuscript.md (visible work-surface draft; append new chapters / "
                "replace same section_id). "
                "If the user asked for a new standalone piece (写一篇 / 写个故事, not 续写) "
                "and the file already holds another story, pass occupy=fresh on the first "
                "call this Turn (archives the old file to drafts/archive/, then writes only "
                "this story). Inferred from the user text when occupy is omitted. "
                "Pass layout=sections for one-file-per-chapter under drafts/. "
                "Promote into manuscript.md via propose_patch. History stays under "
                ".agent/work/history/. A second full draft of the same long section "
                "in one Turn is rejected — patch writing_signals.repair_span instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "content": {"type": "string"},
                    "fragment": {
                        "type": "string",
                        "enum": [
                            "plot_progress",
                            "worldview_texture",
                            "climax_beat",
                            "battle_action",
                            "dialogue_dyad",
                            "mixed",
                        ],
                        "description": "Scene fragment type for writing_signals weights",
                    },
                    "layout": {
                        "type": "string",
                        "enum": ["monofile", "sections"],
                        "description": "Override WRITING_MANUSCRIPT_MODE for this call",
                    },
                    "occupy": {
                        "type": "string",
                        "enum": ["upsert", "fresh"],
                        "description": (
                            "fresh: archive the occupied manuscript and write only this "
                            "section. upsert: keep other chapters. Omit to infer from "
                            "the user text (写一篇 vs 续写)."
                        ),
                    },
                },
                "required": ["section_id", "content"],
            },
            handler=core.draft_section,
        )
    )
    registry.register(
        ToolSpec(
            name="writing_rubric",
            description=(
                "Returns platform dimension weights and penalty/reward keys for a fragment type. "
                "Does not score prose — use evaluate_writing_fragment or draft_section after writing. "
                "Account style leans are in Settings → 写作风格."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "fragment": {
                        "type": "string",
                        "enum": [
                            "plot_progress",
                            "worldview_texture",
                            "climax_beat",
                            "battle_action",
                            "dialogue_dyad",
                            "mixed",
                        ],
                    },
                    "section_id": {
                        "type": "string",
                        "description": "Optional chapter id for outline duty",
                    },
                },
                "required": ["fragment"],
            },
            handler=core.writing_rubric,
        )
    )
    registry.register(
        ToolSpec(
            name="evaluate_writing_fragment",
            description=(
                "Heuristic reward/penalty score for a prose fragment (account weights from Settings). "
                "Pass text or section_id. Persists cross-session history. "
                "Prefer draft_section which embeds the same writing_signals block."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "fragment": {
                        "type": "string",
                        "enum": [
                            "plot_progress",
                            "worldview_texture",
                            "climax_beat",
                            "battle_action",
                            "dialogue_dyad",
                            "mixed",
                        ],
                    },
                    "text": {"type": "string", "description": "Prose to score"},
                    "section_id": {
                        "type": "string",
                        "description": "Read chapter from manuscript if text omitted",
                    },
                },
                "required": ["fragment"],
            },
            handler=core.evaluate_writing_fragment,
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
                "writing fact corpus; sources/seed/intel/{_demo,vendor,ioc}/ for threat-intel "
                "lab notes / ATT&CK / galaxy cards (vendor may be empty until "
                "`make intel-corpus-fetch`); sources/cards/ is pinned style/character material — "
                "do not search cards here; user uploads may appear under other sources/ trees "
                "(e.g. hr/, legal/, writing/). "
                "Prefer read_file when the source path is known. "
                "Optional path_prefix narrows to a subdirectory under sources/ "
                "(e.g. 'seed/writing/dramas', 'seed/intel', 'hr', or 'sources/hr'); "
                "rejects '..' / absolute paths. "
                "When omitted, ScenarioProfile may apply a default prefix (intel → seed/intel). "
                "Original fiction (立一个故事, no named drama/film): prefer path_prefix "
                "'seed/writing/periods' for texture; do not imitate drama 主线剧情. "
                "First search: pass the user's information need / claim nearly verbatim as `query` "
                "(same wording and order). Do NOT compress into a keyword bag or synonym rewrite "
                "on the first call — hybrid search already handles phrasing. "
                "Default: at most **two** searches per topic (verbatim first; optional one rephrase). "
                "If the first call returns any on-topic paths, stop searching and `read_file` the "
                "top hits — do not burn the remaining budget on synonym cascades. "
                "A second search is only for clearly empty / off-topic first hits; keep distinctive "
                "entities. Prefer a larger limit (e.g. 30–100) when you need broad recall. "
                "Do not invent documents. For content questions, call this before list_dir inventory."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search text. First call: copy the user's information need nearly "
                            "verbatim. At most one follow-up rephrase if hits were empty/off-topic; "
                            "otherwise read_file top paths instead of searching again."
                        ),
                    },
                    "limit": {"type": "integer", "default": 30},
                    "path_prefix": {
                        "type": "string",
                        "description": (
                            "Optional directory under sources/ to restrict search. "
                            "Relative path; 'seed/writing/persons' or 'hr' means that tree. "
                            "Original fiction: 'seed/writing/periods'. "
                            "Omit to use ScenarioProfile default when configured "
                            "(intel defaults to seed/intel). "
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
                "Regex/search file contents for exact error strings, unique literals, or "
                "regex patterns. Bare symbol/class/function names are redirected to "
                "search_codebase (Locate via language server) — do not use this tool to "
                "bypass structural locate. Use glob for filenames; do not use shell find/rg."
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
                "for symbol Locate use search_codebase."
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
                "Do NOT use for edits to an existing file (including HTML/JS games) — use "
                "edit_file for unique spans (writing may use propose_patch). Full rewrite only "
                "when the user explicitly asks to replace the whole file. Requires approval "
                "in agent mode."
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
                "Default surgical edit for agent mode: replace a unique exact span "
                "(old_text → new_text) in an existing file after approval. Prefer this over "
                "write_file for existing files. On successful code edits the result includes "
                "impact.references (same sensor as find_references), checks "
                "(pre-write syntax gate + incremental diagnostics / new_issues), and when "
                "found related_tests entries ({path, command} — copy command into "
                "run_command / run_tests). Introduced syntax errors are rejected without "
                "writing. If "
                "the span is missing or not unique, the result includes candidates/lines — "
                "adjust the span (or read_file once); do not resend blindly. Still call "
                "read_lints for cross-file coverage."
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
                "Allowed launchers only: pytest, python -m pytest, npm|pnpm|yarn test, "
                "npx vitest|jest, go test. Other commands → use run_command (requires approval). "
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
                "Read lint/diagnostic results (language server + CLI) for workspace paths. "
                "Required after edit_file / write_file on code — pass the affected file "
                "path(s), not the whole repo by default. Fix new issues before claiming done. "
                "Not a substitute for run_tests."
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
            name="goto_definition",
            description=(
                "Precision definition jump via the language server (path/line/col hints). "
                "Cold-start symbol locate normally goes through search_codebase (same "
                "definition sensor). Use this when you already have a file anchor or need "
                "a disambiguated multi-hop jump. Not optional when refining a known symbol."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol name (primary input)"},
                    "path": {
                        "type": "string",
                        "description": "Optional file path hint to disambiguate",
                    },
                    "line": {"type": "integer", "description": "Optional 1-based line hint"},
                    "col": {"type": "integer", "description": "Optional 1-based column hint"},
                },
                "required": ["symbol"],
            },
            handler=core.goto_definition,
            timeout_s=15.0,
        )
    )
    registry.register(
        ToolSpec(
            name="find_references",
            description=(
                "Precision reference scan via the language server. Successful edit_file on "
                "code already attaches impact.references (same sensor) — call this to deepen "
                "or pre-scan before a signature change. Optional path/line/col disambiguate. "
                "Results may be capped — follow pointers. Lexical grep hits are not references."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol name (primary input)"},
                    "path": {
                        "type": "string",
                        "description": "Optional file path hint to disambiguate",
                    },
                    "line": {"type": "integer", "description": "Optional 1-based line hint"},
                    "col": {"type": "integer", "description": "Optional 1-based column hint"},
                },
                "required": ["symbol"],
            },
            handler=core.find_references,
            timeout_s=15.0,
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
                "Primary Locate tool for coding: symbol-shaped queries resolve via the language "
                "server (same definition sensor as goto_definition) and return definitions[]. "
                "Empty definitions with lexical hits means locate_incomplete=true — not a "
                "finished Locate. Non-symbol queries (error strings / phrases) stay lexical. "
                "Not embedding search. Use glob for filenames; read_file when the path is known."
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
                "Prefer context_refs/paths over pasting large text into context. "
                "For dependent follow-ups, pass prior artifact_refs / artifacts/collab/ paths. "
                "Result may include artifact_refs for the next handoff."
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
                        "description": (
                            "Workspace-relative file paths the sub-agent should read "
                            "(handoff / shared blackboard)"
                        ),
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
            # Whole nested AgentEngine (model + tools). Default tool timeout 60s
            # is too short for edit/verify workers (live: notes.py timed out).
            timeout_s=max(300.0, float(settings.tool_default_timeout_seconds)),
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
                "builds, installs, or non-standard checks whose stdout is needed. "
                "Sandbox limits writable FS to the work root; outbound network stays on. "
                "exit_code!=0 means the command ran and failed — inspect stderr; do not "
                "blame the OS sandbox for 'no network'. Child env is allowlisted (no API keys "
                "unless the platform injects them). Never put secrets in the command string. "
                "FORBIDDEN as a substitute for read_file / grep / goto_definition: do not run "
                "cat, head, tail, sed -n, awk, less, wc, find, rg, or grep just to page or "
                "search source — use read_file, the grep tool, or goto_definition. "
                "Those shell commands remain OK inside real build/install/test pipelines. "
                "Prefer run_tests for the standard test suite; prefer edit_file/"
                "write_file for file changes — do not use shell redirection to write code."
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
    from app.tools.core import intel_enrich as intel_tools

    registry.register(
        ToolSpec(
            name="enrich_ioc",
            description=(
                "Enrich an IOC (IP, domain, hash, URL) from the local stub/seed IOC cards. "
                "Read-only; no outbound network and no containment actions. "
                "Prefer this first for structured reputation; then lookup_indicator / "
                "search_sources for corpus evidence."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "indicator": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["auto", "ip", "domain", "hash", "url"],
                        "default": "auto",
                    },
                },
                "required": ["indicator"],
            },
            handler=intel_tools.enrich_ioc,
        )
    )
    registry.register(
        ToolSpec(
            name="lookup_indicator",
            description=(
                "Exact local lookup for an IOC, ATT&CK id, actor/malware name under "
                "sources/seed/intel (and fixture IOC cards). No embeddings, no network, "
                "no index rebuild — use for precise keys before semantic search_sources."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "indicator": {"type": "string"},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["indicator"],
            },
            handler=intel_tools.lookup_indicator,
            timeout_s=8.0,
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

# After「按此执行」, Plan consent covers file mutations — no per-edit approval (docs/25 §2.4).
# Shell/exec stays on the normal approval path (still high-risk / not implied by a checklist).
_PLAN_EXECUTING_WAIVE_APPROVAL = ON_WRITE_TOOLS | frozenset({"rename_file"})


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
        # Plan executing: user already approved the checklist — waive file-write gates.
        if phase == "executing" and name in _PLAN_EXECUTING_WAIVE_APPROVAL:
            requires = False
        specs.append(replace(base, requires_approval=requires))
    return specs


def late_stage_tools_disabled(
    *,
    step_count: int,
    max_steps: int,
    delivery: dict | None,
) -> bool:
    """True when late-stage search/memory tools should be runtime-gated (C2)."""
    delivery_ok = isinstance(delivery, dict) and str(delivery.get("delivery_status", "")) in {
        "ok",
        "warning",
    }
    remaining = max_steps - step_count
    late = step_count >= 8 and remaining <= 6
    return bool(delivery_ok or late)


def stage_tool_runtime_blocked(
    tool_name: str,
    *,
    step_count: int,
    max_steps: int,
    delivery: dict | None,
) -> bool:
    """Runtime gate for tools that used to be removed from the schema."""
    if tool_name not in _LATE_STAGE_DROP:
        return False
    return late_stage_tools_disabled(
        step_count=step_count, max_steps=max_steps, delivery=delivery
    )


def stage_tool_scope(specs: list[ToolSpec], *, step_count: int, max_steps: int, delivery: dict | None) -> list[ToolSpec]:
    """Optionally shrink tools JSON in late steps (legacy); default is no-op (C2).

    Prefer ``stage_tool_runtime_blocked`` so the tools schema stays cache-stable.
    """
    from app.settings import settings

    if not bool(getattr(settings, "stage_tool_scope_mutate_schema", False)):
        return specs
    if not late_stage_tools_disabled(
        step_count=step_count, max_steps=max_steps, delivery=delivery
    ):
        return specs
    return [spec for spec in specs if spec.name not in _LATE_STAGE_DROP]
