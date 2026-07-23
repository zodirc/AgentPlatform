"""Golden fixture + assertion helpers extracted from scripts/eval_run.py (docs/29)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def sequence_contains(events: list[str], required: list[str]) -> bool:
    idx = 0
    for need in required:
        while idx < len(events) and events[idx] != need:
            idx += 1
        if idx >= len(events):
            return False
        idx += 1
    return True


def sequence_equals(events: list[str], required: list[str]) -> bool:
    return events == required


def _ensure_runtime_writable(path: Path) -> None:
    """API often runs as root (docker.sock); runtime is uid 1000 — make ops trees writable."""
    try:
        path.chmod(0o777)
    except OSError:
        pass


def _ensure_parents_writable(path: Path, *, stop_at: Path) -> None:
    """chmod every directory from ``path`` up to ``stop_at`` (inclusive of path if dir)."""
    stop = stop_at.resolve()
    current = path.resolve() if path.exists() else path
    # Walk parents of the target file/dir.
    cursor = current if current.is_dir() else current.parent
    while True:
        try:
            cursor.relative_to(stop)
        except ValueError:
            break
        _ensure_runtime_writable(cursor)
        if cursor == stop:
            break
        if cursor.parent == cursor:
            break
        cursor = cursor.parent


def apply_fixtures(workspace: Path, case: dict[str, Any]) -> None:
    fixtures = case.get("fixtures", {}) or {}
    for item in fixtures.get("workspace", []) or []:
        rel = item["path"]
        content = item.get("content", "")
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _ensure_parents_writable(target.parent, stop_at=workspace)
        target.write_text(content, encoding="utf-8")
        try:
            target.chmod(0o666)
        except OSError:
            pass

    setup = case.get("setup", {}) or {}
    chars = setup.get("large_file_chars")
    if chars:
        target = workspace / "large_file.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        _ensure_parents_writable(target.parent, stop_at=workspace)
        target.write_text("A" * int(chars) + "\n", encoding="utf-8")
        try:
            target.chmod(0o666)
        except OSError:
            pass


def prepare_ops_workspace(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for directory in (workspace, workspace / "sections", workspace / "sources", workspace / "exports"):
        directory.mkdir(parents=True, exist_ok=True)
        _ensure_runtime_writable(directory)
    if workspace.parent.exists():
        _ensure_runtime_writable(workspace.parent)
    _ensure_runtime_writable(workspace)


def read_workspace_file(workspace: Path, rel: str) -> str | None:
    if any(ch in rel for ch in "*?[]"):
        matches = sorted(
            workspace.glob(rel),
            key=lambda p: p.stat().st_mtime if p.is_file() else 0.0,
            reverse=True,
        )
        for target in matches:
            if target.is_file():
                return target.read_text(encoding="utf-8", errors="replace")
        return None
    target = (workspace / rel).resolve()
    try:
        target.relative_to(workspace.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8", errors="replace")


def first_patch_id(artifacts: list) -> str:
    for art in artifacts:
        if isinstance(art, dict) and art.get("patch_id"):
            return str(art["patch_id"])
    raise AssertionError("no patch_id in turn artifacts")


def assert_events(case_id: str, events: list[str], event_asserts: dict[str, Any]) -> None:
    if "sequence_equals" in event_asserts:
        if not sequence_equals(events, event_asserts["sequence_equals"]):
            raise AssertionError(
                f"{case_id}: expected {event_asserts['sequence_equals']}, got {events}"
            )
    if "sequence_contains" in event_asserts:
        if not sequence_contains(events, event_asserts["sequence_contains"]):
            raise AssertionError(f"{case_id}: missing subsequence in {events}")
    for forbidden in event_asserts.get("sequence_not_contains", []) or []:
        if forbidden in events:
            raise AssertionError(f"{case_id}: forbidden event {forbidden}")


def assert_event_payload_fields(
    case_id: str,
    event_records: list[dict[str, Any]],
    event_payload_assert: dict[str, Any],
) -> None:
    for event_type, expected_fields in event_payload_assert.items():
        matched = [r for r in event_records if r.get("type") == event_type]
        if not matched:
            raise AssertionError(f"{case_id}: missing event {event_type} for payload assert")
        payload = matched[0].get("payload") or {}
        if isinstance(payload, str):
            import json

            payload = json.loads(payload)
        for key, expected in expected_fields.items():
            if payload.get(key) != expected:
                raise AssertionError(
                    f"{case_id}: {event_type} payload[{key!r}]={payload.get(key)!r} != {expected!r}"
                )


def assert_tool(case_id: str, view: dict[str, Any], tool_assert: dict[str, Any]) -> None:
    timeline = view.get("tool_timeline", []) or []
    needle = tool_assert.get("result_matches", "")
    tool_name = tool_assert.get("name", "")
    expected_retrieval = tool_assert.get("retrieval")
    matched = False
    retrieval_matched = expected_retrieval is None
    name_seen = False
    for item in timeline:
        if item.get("tool_name") != tool_name:
            continue
        name_seen = True
        summary = str(item.get("summary", ""))
        if needle and re.search(needle, summary, re.S):
            matched = True
        elif not needle:
            matched = True
    if expected_retrieval:
        allowed = (
            {expected_retrieval}
            if isinstance(expected_retrieval, str)
            else set(expected_retrieval)
        )
        for artifact in view.get("artifacts", []) or []:
            if artifact.get("type") == "retrieval" and artifact.get("mode") in allowed:
                retrieval_matched = True
                break
    if tool_name and not name_seen:
        raise AssertionError(f"{case_id}: tool {tool_name!r} missing from tool_timeline")
    if needle and not matched:
        raise AssertionError(f"{case_id}: tool {tool_name!r} missing result match {needle!r}")
    forbidden_result = tool_assert.get("result_not_matches", "")
    if forbidden_result:
        for item in timeline:
            if tool_name and item.get("tool_name") != tool_name:
                continue
            if re.search(forbidden_result, str(item.get("summary", "")), re.S):
                raise AssertionError(
                    f"{case_id}: tool {tool_name!r} unexpectedly matched {forbidden_result!r}"
                )
    if expected_retrieval and not retrieval_matched:
        raise AssertionError(
            f"{case_id}: tool {tool_name!r} missing retrieval mode {expected_retrieval!r}"
        )
    for name in tool_assert.get("forbidden_names") or []:
        if name in {item.get("tool_name") for item in timeline}:
            raise AssertionError(f"{case_id}: forbidden tool {name!r} in tool_timeline")
    max_calls = tool_assert.get("max_calls") or {}
    if max_calls:
        counts: dict[str, int] = {}
        for item in timeline:
            name = item.get("tool_name")
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
        for name, limit in max_calls.items():
            if counts.get(name, 0) > int(limit):
                raise AssertionError(
                    f"{case_id}: tool {name!r} called {counts.get(name, 0)} > max {limit}"
                )


def assert_workspace(case_id: str, workspace: Path, specs: list[dict[str, Any]]) -> None:
    for ws in specs:
        content = read_workspace_file(workspace, ws["path"])
        if content is None:
            raise AssertionError(f"{case_id}: missing workspace file {ws['path']}")
        if "matches" in ws and not re.search(ws["matches"], content, re.S):
            raise AssertionError(f"{case_id}: workspace {ws['path']} does not match {ws['matches']}")
        if "not_matches" in ws and re.search(ws["not_matches"], content, re.S):
            raise AssertionError(
                f"{case_id}: workspace {ws['path']} unexpectedly matches {ws['not_matches']}"
            )


def assert_output(case_id: str, view: dict[str, Any], output_assert: dict[str, Any]) -> None:
    if "matches" not in output_assert:
        return
    output = view.get("latest_output") or ""
    if not re.search(output_assert["matches"], output, re.S):
        raise AssertionError(f"{case_id}: output does not match {output_assert['matches']!r}")


UNSUPPORTED_COMMANDS = frozenset(
    {
        "ws.stream",
        "wait-index",
        "admin.create-provider",
        "session-turns",
    }
)
