"""Wave 4: test_summary (W10), related_tests commands (W11), verify_receipt (W9)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.engine.state import TurnState
from app.engine.verify_receipt import (
    build_verify_receipt_text,
    note_tool_result_for_verify,
    should_inject_verify_receipt,
)
from app.structural.related_tests import related_test_paths, related_tests_for_path
from app.structural.test_summary import (
    attach_test_summary_for_run_command,
    attach_test_summary_for_run_tests,
    parse_test_summary,
)


def test_parse_pytest_summary_with_failures() -> None:
    stdout = """
============================= test session starts ==============================
collected 3 items

tests/test_a.py::test_ok PASSED
tests/test_a.py::test_bad FAILED
tests/test_a.py::test_err ERROR

________________________________ test_bad ________________________________
    def test_bad():
>       assert 1 == 2
E       AssertionError: assert 1 == 2

=========================== short test summary info ============================
FAILED tests/test_a.py::test_bad
ERROR tests/test_a.py::test_err
==================== 1 failed, 1 passed, 1 error in 0.12s ======================
"""
    summary = parse_test_summary(stdout)
    assert summary is not None
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["errors"] == 1
    assert summary["first_failures"]
    assert any("test_bad" in f["name"] for f in summary["first_failures"])


def test_parse_pytest_omits_unknown_banner() -> None:
    assert parse_test_summary("==== hello ====\nnot a test report\n") is None


def test_parse_pytest_ignores_later_coverage_banner() -> None:
    stdout = """
============================= test session starts ==============================
tests/test_a.py::test_ok PASSED
=========================== short test summary info ============================
==================== 2 passed, 1 failed in 0.12s ======================
---------- coverage: 85% -----------
============================= 85% ==============================
"""
    summary = parse_test_summary(stdout)
    assert summary is not None
    assert summary["passed"] == 2
    assert summary["failed"] == 1


def test_parse_pytest_strips_ansi_and_failed_lines_without_footer() -> None:
    colored = (
        "\x1b[31m===================== 1 failed, 2 passed in 0.08s ======================\x1b[0m\n"
    )
    summary = parse_test_summary(colored)
    assert summary is not None
    assert summary["failed"] == 1
    assert summary["passed"] == 2

    truncated = (
        "tests/test_a.py::test_ok PASSED\n"
        "FAILED tests/test_b.py::test_bad - AssertionError: boom\n"
    )
    summary = parse_test_summary(truncated)
    assert summary is not None
    assert summary["failed"] == 1
    assert any("test_bad" in f["name"] for f in summary["first_failures"])


def test_parse_unittest_failed_failures_line_is_not_pytest_nodeid() -> None:
    stdout = (
        "FAIL: test_roundtrip (astropy.io.ascii.tests.test_qdp.TestQDP)\n"
        "----------------------------------------------------------------------\n"
        "Ran 9 tests in 0.04s\n"
        "\n"
        "FAILED (failures=1)\n"
    )
    summary = parse_test_summary(stdout)
    assert summary is not None
    assert summary["provider"] == "unittest"
    assert summary["failed"] == 1
    assert summary["passed"] == 8
    assert any("test_roundtrip" in f["name"] for f in summary["first_failures"])


def test_attach_test_summary_run_tests() -> None:
    result = {
        "command": "pytest -q",
        "status": "failed",
        "stdout": "===== 1 failed, 2 passed in 0.01s =====\n",
        "stderr": "",
    }
    out = attach_test_summary_for_run_tests(result)
    assert out["test_summary"]["failed"] == 1
    assert out["test_summary"]["passed"] == 2


def test_attach_test_summary_run_command_only_when_testish() -> None:
    plain = {"command": "ls -la", "stdout": "===== 1 passed in 0.01s =====", "stderr": ""}
    assert "test_summary" not in attach_test_summary_for_run_command(
        dict(plain), command="ls -la"
    )
    testish = {
        "command": "python -m pytest tests/test_x.py -q",
        "stdout": "===== 1 passed in 0.01s =====",
        "stderr": "",
    }
    out = attach_test_summary_for_run_command(
        dict(testish), command=testish["command"]
    )
    assert out["test_summary"]["passed"] == 1


def test_projection_lookup_importers() -> None:
    from uuid import uuid4

    from app.structural.workspace_index.projection import IndexProjection
    from app.structural.workspace_index.types import FileEntry, IndexMeta, IndexStatus

    wid = uuid4()
    meta = IndexMeta(
        work_id=wid,
        owner_user_id="u1",
        status=IndexStatus.READY,
        generation=1,
    )
    proj = IndexProjection(work_id=wid, owner_user_id="u1", meta=meta)
    proj.replace_all(
        [
            FileEntry(
                path="pkg/widget.py",
                lang="python",
                content_hash="a",
                mtime_ns=1,
                size=10,
                symbols=[],
                imports=["os"],
            ),
            FileEntry(
                path="tests/test_widget.py",
                lang="python",
                content_hash="b",
                mtime_ns=1,
                size=20,
                symbols=[],
                imports=["pkg.widget", "widget"],
            ),
        ],
        meta=meta,
    )
    hits = proj.lookup_importers({"pkg.widget"}, limit=5, test_only=True)
    assert hits == ["tests/test_widget.py"]


def test_related_tests_include_command(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "widget.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_widget.py").write_text(
        "from pkg.widget import f\n\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8",
    )
    entries = related_tests_for_path("pkg/widget.py", workspace=tmp_path)
    assert entries
    assert all(isinstance(e, dict) and e.get("path") and e.get("command") for e in entries)
    assert any(e["path"].endswith("test_widget.py") for e in entries)
    assert any("pytest" in e["command"] for e in entries)
    assert related_test_paths(entries)


def _state(**kwargs) -> TurnState:
    uid = uuid4()
    base = dict(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="agent",
        max_steps=40,
        step_count=5,
    )
    base.update(kwargs)
    return TurnState(**base)


def test_verify_receipt_trigger_once_and_reserve() -> None:
    state = _state()
    note_tool_result_for_verify(
        state,
        tool_name="edit_file",
        result={
            "status": "edited",
            "impact": {"status": "ok"},
            "checks": {"status": "ok"},
            "related_tests": [
                {
                    "path": "tests/test_a.py",
                    "command": "python -m pytest tests/test_a.py -x -q",
                }
            ],
        },
    )
    assert state.verify_pending is True
    assert should_inject_verify_receipt(state, reserve_steps=10) is True
    text = build_verify_receipt_text(state)
    assert "verify_receipt:" in text
    assert "tests/test_a.py" in text
    state.verify_receipt_sent = True
    assert should_inject_verify_receipt(state, reserve_steps=10) is False


def test_verify_receipt_cleared_by_run_tests() -> None:
    state = _state()
    note_tool_result_for_verify(
        state,
        tool_name="edit_file",
        result={"status": "edited", "impact": {"status": "ok"}, "checks": {"status": "ok"}},
    )
    note_tool_result_for_verify(
        state,
        tool_name="run_tests",
        result={"status": "passed", "command": "pytest -q", "exit_code": 0},
    )
    assert state.verify_pending is False
    assert should_inject_verify_receipt(state) is False


def test_issue_repro_extract_from_problem_fence_only() -> None:
    from app.structural.issue_repro import (
        command_matches_issue_repro,
        extract_issue_repro_hints,
        obligations_met_for_command,
    )

    problem = """
ascii.qdp assumes commands are upper case; QDP is not case sensitive and accepts "read serr 1 2".
### Expected behavior
```
read serr 1 2
1 0.5 1 0.5
```
>>> from astropy.table import Table
>>> Table.read('test.qdp', format='ascii.qdp')
"""
    hints = extract_issue_repro_hints(problem)
    assert hints["assets"]
    assert hints["need_casefold"] is True
    assert "read serr 1 2" in hints["assets"][0]
    assert "1 0.5 1 0.5" in hints["assets"][0]
    # Must not invent lowercase NO — not present in the issue sample.
    assert "no" not in hints["required_tokens"]
    assert not command_matches_issue_repro(
        "python -m pytest astropy/io/ascii/tests/test_qdp.py -q",
        hints["markers"],
        required_tokens=hints["required_tokens"],
        assets=hints["assets"],
    )
    # Token-only command (missing data rows) must not cover the asset.
    assert not command_matches_issue_repro(
        'python -c "print(\'read serr 1 2\')"',
        hints["markers"],
        required_tokens=hints["required_tokens"],
        assets=hints["assets"],
    )
    repro = (
        'python -c "from astropy.table import Table; '
        "open('t.qdp','w').write('read serr 1 2\\n1 0.5 1 0.5\\n'); "
        'Table.read(\'t.qdp\', format=\'ascii.qdp\')"'
    )
    assert command_matches_issue_repro(
        repro,
        hints["markers"],
        required_tokens=hints["required_tokens"],
        assets=hints["assets"],
    )
    # Casefold claim: sample already lower — still require an explicit fold transform.
    assert obligations_met_for_command(repro, hints) is False
    repro_cf = (
        'python -c "from astropy.table import Table; '
        "body='read serr 1 2\\n1 0.5 1 0.5\\n'; "
        "open('t.qdp','w').write(body.lower()); "
        'Table.read(\'t.qdp\', format=\'ascii.qdp\')"'
    )
    assert obligations_met_for_command(repro_cf, hints) is True


def test_issue_repro_roundtrip_required_for_write_header_rows() -> None:
    from app.structural.issue_repro import (
        extract_issue_repro_hints,
        obligations_met_for_command,
    )

    problem = """
Please support header rows in RestructuredText output
>>> tbl.write(sys.stdout, format="ascii.rst", header_rows=["name", "unit"])
TypeError: RST.__init__() got an unexpected keyword argument 'header_rows'
"""
    hints = extract_issue_repro_hints(problem)
    assert hints["need_roundtrip"] is True
    assert "header_rows" in hints["roundtrip_kwargs"]
    assert any("ascii.rst" in f for f in hints["roundtrip_formats"])
    write_only = (
        'python -c "t.write(\'o.txt\', format=\'ascii.rst\', '
        'header_rows=[\'name\',\'unit\'])"'
    )
    assert obligations_met_for_command(write_only, hints) is False
    roundtrip = (
        'python -c "from astropy.table import Table, QTable; import astropy.units as u; '
        "t=QTable({'wave':[350,950]*u.nm}); "
        "t.write('o.txt', format='ascii.rst', header_rows=['name','unit']); "
        "Table.read('o.txt', format='ascii.rst', header_rows=['name','unit'])\""
    )
    assert obligations_met_for_command(roundtrip, hints) is True


def test_issue_repro_fail_signal_blocks_clearing() -> None:
    from app.structural.issue_repro import (
        extract_issue_repro_hints,
        is_clearing_repro_result,
    )

    problem = """
### Bug
```
>>> Table.read('bad.txt', format='ascii.qdp')
Traceback (most recent call last):
  ...
ValueError: Unrecognized QDP command 'no'
```
### Expected behavior
Should accept the command without raising.
"""
    hints = extract_issue_repro_hints(problem)
    assert any("ValueError" in s for s in hints["fail_signals"])
    ok = {
        "status": "ok",
        "exit_code": 0,
        "summary": "sweb.eval (reused): ok",
        "stdout": "",
        "stderr": "",
    }
    assert is_clearing_repro_result(ok, fail_signals=hints["fail_signals"]) is True
    still_broken = {
        "status": "ok",
        "exit_code": 0,
        "summary": "sweb.eval (reused): ok",
        "stderr": "ValueError: Unrecognized QDP command 'no'",
    }
    assert (
        is_clearing_repro_result(still_broken, fail_signals=hints["fail_signals"])
        is False
    )


def test_issue_repro_receipt_after_green_repo_tests() -> None:
    from app.engine.verify_receipt import mark_verify_receipt_injected

    state = _state()
    state.issue_repro_loaded = True
    state.issue_repro_markers = ["read serr 1 2"]
    state.issue_repro_required_tokens = ["read serr 1 2"]
    state.issue_repro_commands = []
    note_tool_result_for_verify(
        state,
        tool_name="edit_file",
        result={"status": "edited", "impact": {"status": "ok"}, "checks": {"status": "ok"}},
    )
    note_tool_result_for_verify(
        state,
        tool_name="run_tests",
        result={
            "status": "passed",
            "command": "python -m pytest astropy/io/ascii/tests/test_qdp.py -q",
            "exit_code": 0,
            "test_summary": {"passed": 8, "failed": 0, "errors": 0},
        },
    )
    assert state.verify_pending is False
    assert state.issue_repro_armed is True
    assert should_inject_verify_receipt(state, reserve_steps=10) is True
    text = build_verify_receipt_text(state)
    assert "required_tokens" in text
    assert "read serr" in text
    kind = mark_verify_receipt_injected(state)
    assert kind == "issue_repro"
    assert state.issue_repro_receipt_sent is True
    assert should_inject_verify_receipt(state) is False


def test_issue_repro_pre_edit_does_not_satisfy() -> None:
    state = _state()
    state.issue_repro_loaded = True
    state.issue_repro_markers = ["read serr 1 2"]
    state.issue_repro_required_tokens = ["read serr 1 2"]
    state.issue_repro_commands = []
    note_tool_result_for_verify(
        state,
        tool_name="run_command",
        result={
            "status": "ok",
            "command": (
                'python -c "open(\'t.qdp\',\'w\').write('
                "'read serr 1 2\\n1 0.5\\n'); print('ok')\""
            ),
            "exit_code": 0,
            "summary": "sweb.eval (reused): ok",
        },
    )
    assert state.issue_repro_satisfied is True
    note_tool_result_for_verify(
        state,
        tool_name="edit_file",
        result={"status": "edited", "impact": {"status": "ok"}, "checks": {"status": "ok"}},
    )
    assert state.issue_repro_satisfied is False
    assert state.issue_repro_edits_since >= 1
    note_tool_result_for_verify(
        state,
        tool_name="run_tests",
        result={
            "status": "passed",
            "command": "python -m pytest tests/test_qdp.py -q",
            "exit_code": 0,
            "test_summary": {"passed": 8, "failed": 0, "errors": 0},
        },
    )
    assert state.issue_repro_armed is True
    assert should_inject_verify_receipt(state, reserve_steps=10) is True


def test_issue_repro_post_edit_success_satisfies() -> None:
    state = _state()
    state.issue_repro_loaded = True
    state.issue_repro_markers = ["read serr 1 2"]
    state.issue_repro_required_tokens = ["read serr 1 2"]
    state.issue_repro_armed = True
    state.issue_repro_edits_since = 1
    note_tool_result_for_verify(
        state,
        tool_name="run_command",
        result={
            "status": "ok",
            "command": (
                'python -c "open(\'t.qdp\',\'w\').write('
                "'read serr 1 2\\n1 0.5\\n'); print('ok')\""
            ),
            "exit_code": 0,
            "summary": "sweb.eval (reused): ok",
        },
    )
    assert state.issue_repro_satisfied is True
    assert state.issue_repro_edits_since == 0
    assert should_inject_verify_receipt(state) is False


def test_issue_repro_failed_match_does_not_satisfy() -> None:
    state = _state()
    state.issue_repro_loaded = True
    state.issue_repro_required_tokens = ["read serr 1 2"]
    state.issue_repro_markers = ["read serr 1 2"]
    state.issue_repro_armed = True
    note_tool_result_for_verify(
        state,
        tool_name="run_command",
        result={
            "status": "ok",
            "command": 'python -c "print(\'read serr 1 2\')"',
            "summary": "sweb.eval failed (exit 1): boom",
        },
    )
    assert state.issue_repro_satisfied is False


def test_issue_repro_still_showing_fail_signal_does_not_satisfy() -> None:
    state = _state()
    state.issue_repro_loaded = True
    state.issue_repro_assets = ["read serr 1 2\n1 0.5 1 0.5"]
    state.issue_repro_markers = ["read serr 1 2"]
    state.issue_repro_fail_signals = ["ValueError: Unrecognized QDP command"]
    state.issue_repro_armed = True
    state.issue_repro_edits_since = 1
    note_tool_result_for_verify(
        state,
        tool_name="run_command",
        result={
            "status": "ok",
            "exit_code": 0,
            "command": (
                'python -c "open(\'t.qdp\',\'w\').write('
                "'read serr 1 2\\n1 0.5 1 0.5\\n')\""
            ),
            "summary": "sweb.eval (reused): ok",
            "stderr": "ValueError: Unrecognized QDP command 'READ'",
        },
    )
    assert state.issue_repro_satisfied is False


def test_verify_receipt_skips_low_remaining_steps() -> None:
    state = _state(step_count=35, max_steps=40)
    note_tool_result_for_verify(
        state,
        tool_name="edit_file",
        result={"status": "edited", "impact": {"status": "ok"}, "checks": {"status": "ok"}},
    )
    assert should_inject_verify_receipt(state, reserve_steps=10) is False


def test_verify_receipt_skips_non_code_edit() -> None:
    state = _state()
    note_tool_result_for_verify(
        state,
        tool_name="edit_file",
        result={
            "status": "edited",
            "impact": {"status": "skipped", "reason": "non_code_path"},
            "checks": {"status": "skipped"},
        },
    )
    assert state.verify_pending is False


@pytest.mark.asyncio
async def test_agent_engine_injects_verify_receipt_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.engine.agent_engine import AgentEngine
    from app.model.gateway import ModelResponse
    from app.tools.registry import ToolSpec

    class FakeGateway:
        def __init__(self) -> None:
            self.n = 0

        async def stream(self, *, messages, tools):
            self.n += 1
            if self.n == 1:
                yield ModelResponse(
                    text="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "edit_file",
                            "input": {
                                "path": "mod.py",
                                "old_text": "a",
                                "new_text": "b",
                            },
                        }
                    ],
                )
            elif self.n == 2:
                yield ModelResponse(text="done without tests")
            else:
                yield ModelResponse(text="done after receipt")

    async def fake_edit(**_kwargs):
        return {
            "status": "edited",
            "path": "mod.py",
            "impact": {"status": "ok"},
            "checks": {"status": "ok", "new_issues": []},
            "related_tests": [
                {
                    "path": "tests/test_mod.py",
                    "command": "python -m pytest tests/test_mod.py -x -q",
                }
            ],
            "related_tests_count": 1,
            "summary": "Edited mod.py",
        }

    spec = ToolSpec(
        name="edit_file",
        description="edit",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
        handler=fake_edit,
        requires_approval=False,
    )

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        return None

    async def check_cancel():
        return False, False

    monkeypatch.setattr(
        "app.engine.agent_engine.settings.verify_receipt_reserve_steps", 2
    )
    engine = AgentEngine(
        gateway=FakeGateway(),
        tools=[spec],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=check_cancel,
    )
    state = _state(max_steps=10, step_count=0)
    summary = await engine.run(state)
    assert state.verify_receipt_sent is True
    receipt_msgs = [
        m
        for m in state.messages
        if m.get("role") == "user"
        and any(
            "verify_receipt:" in str(b.get("text", ""))
            for b in (m.get("content") or [])
            if isinstance(b, dict)
        )
    ]
    assert len(receipt_msgs) == 1
    assert summary == "done after receipt"
