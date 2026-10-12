"""覆盖编码优化里原先没走到的分支，让 runtime 单测覆盖率留在 80% 以上。"""

from __future__ import annotations

import asyncio
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.settings import settings
from app.tenant_context import bind_tenant_context, reset_tenant_context


class _BytesStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self, _n: int) -> bytes:
        data, self._data = self._data, b""
        return data


def test_text_roundtrip_and_span_ladder() -> None:
    from app.tools.core.text_fidelity import (
        _find_reindent,
        _find_trailing,
        _line_offsets,
        apply_spans,
        dump_text,
        encode_preserving,
        line_of_offset,
        load_text_bytes,
        plan_spans,
        post_edit_excerpt,
    )

    plain = load_text_bytes(b"a\nb\n")
    assert plain.encoding == "utf-8" and plain.newline == "\n" and not plain.bom
    crlf = load_text_bytes(b"a\r\nb\r\nc\n")
    assert crlf.newline == "\r\n"
    assert b"\r\n" in dump_text(crlf, "a\nb\n")
    bom = load_text_bytes(b"\xef\xbb\xbfhello\n")
    assert bom.bom and dump_text(bom, "hello\n").startswith(b"\xef\xbb\xbf")
    latin = load_text_bytes(b"# coding: latin-1\n\xff")
    assert latin.encoding == "latin-1"
    assert load_text_bytes(b"\xff\xfe")["error"] == "unsupported_encoding"
    assert load_text_bytes(b"# coding: not-a-real-codec\n\xff")["error"] == "unsupported_encoding"
    mismatched = load_text_bytes(b"# coding: unicode_escape\n\xff")
    assert mismatched["error"] == "unsupported_encoding"
    assert encode_preserving(bom, "x\r\ny").startswith(b"\xef\xbb\xbf")
    assert encode_preserving(plain, "x\ny") == b"x\ny"

    planned, err = plan_spans("a a", [{"old_text": "a", "new_text": "b", "replace_all": True}], trailing_ws=False)
    assert err is None and apply_spans("a a", planned) == "b b"
    _planned, missing = plan_spans("abc", [{"old_text": "zzz", "new_text": "q"}], trailing_ws=False)
    assert missing["error"] == "old_text not found"
    _planned, empty = plan_spans("abc", [{"old_text": "", "new_text": "q"}], trailing_ws=True)
    assert empty is not None
    _planned, many = plan_spans("a a", [{"old_text": "a", "new_text": "b"}], trailing_ws=False)
    assert "matches" in many["error"]
    _planned, overlap = plan_spans(
        "abcdef",
        [{"old_text": "abc", "new_text": "X"}, {"old_text": "cde", "new_text": "Y"}],
        trailing_ws=False,
    )
    assert overlap["error"] == "overlapping edits"

    text = "def f():  \n    return 1  \n"
    old = "def f():\n    return 1\n"
    planned, err = plan_spans(text, [{"old_text": old, "new_text": "def f():\n    return 2\n"}], trailing_ws=True)
    assert err is None and planned[0].mode == "trailing_ws"
    indented = "        def f():\n            return 1\n"
    needle = "    def f():\n        return 1\n"
    replacement = "    def f():\n        return 2\n\n"
    planned, err = plan_spans(
        indented,
        [{"old_text": needle, "new_text": replacement}],
        trailing_ws=True,
        reindent=True,
    )
    assert err is None and planned[0].mode == "reindent" and planned[0].new_text.startswith("        ")
    assert _find_trailing("a\n", "   \n", replace_all=False) == []
    assert _find_reindent("a\n", "   \n", replace_all=False) == []
    assert _line_offsets([]) == [0]
    assert "1|a" in post_edit_excerpt("a\n", 1)
    assert "2|b" in post_edit_excerpt("a\nb\nc\n", 2)
    assert line_of_offset("a\nb", 2) == 2


def test_product_finish_acceptance_and_diff(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.engine.product_finish import (
        acceptance_gap,
        acceptance_plan_items,
        one_related_command,
        product_mode,
        work_diff_stat,
    )

    assert product_mode(SimpleNamespace(ops_eval=True, scenario_id="agent")) is False
    assert product_mode(SimpleNamespace(ops_eval=False, scenario_id="writing")) is False
    tokens = bind_tenant_context(work_root=str(tmp_path), ops_eval=True)
    try:
        assert product_mode(SimpleNamespace(ops_eval=False, scenario_id="agent")) is False
    finally:
        reset_tenant_context(tokens)
    assert product_mode(SimpleNamespace(ops_eval=False, scenario_id="agent")) is True
    chosen = one_related_command(
        SimpleNamespace(
            related_tests_union=[
                {"command": "pytest a", "path": "a"},
                3,
                "pytest short",
                {"command": "pytest b", "path": "bb"},
            ]
        )
    )
    assert chosen == "pytest b"
    assert one_related_command(SimpleNamespace(related_tests_union=[])) == ""

    fences = "\n".join(f"```\necho {index}\n```" for index in range(7))
    items = acceptance_plan_items("```\n\n```\n" + fences + "\n验收：\n验收：pytest -q\n")
    assert len(items) == 6 and items[0]["acceptance"].startswith("echo")
    mixed = acceptance_plan_items("```\n\n```\n```\necho 1\n```\n验收：\n验收：pytest -q\n")
    assert any(item["acceptance"] == "pytest -q" for item in mixed)
    capped = acceptance_plan_items("\n".join(f"验收：cmd {index}" for index in range(7)))
    assert len(capped) == 6
    state = SimpleNamespace(acceptance_commands=["pytest -q", "go test"], last_test_command="pytest -q", verify_pending=True)
    assert "go test" in acceptance_gap(state)
    assert acceptance_gap(SimpleNamespace(acceptance_commands=[], last_test_command="", verify_pending=False)) == ""
    done = SimpleNamespace(acceptance_commands=["pytest -q"], last_test_command="pytest -q", verify_pending=False)
    assert acceptance_gap(done) == ""

    tokens = bind_tenant_context(work_root=str(tmp_path))
    try:
        assert work_diff_stat(SimpleNamespace()) == ""
    finally:
        reset_tenant_context(tokens)

    root = tmp_path / "repo"
    root.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
    )
    (root / "tracked.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True, env=env)
    (root / "tracked.txt").write_text("v2\n", encoding="utf-8")
    scratch = root / ".agent" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "skip.txt").write_text("tmp\n", encoding="utf-8")
    for index in range(31):
        (root / f"u{index}.txt").write_text("x\n", encoding="utf-8")
    tokens = bind_tenant_context(work_root=str(root))
    try:
        stat = work_diff_stat(SimpleNamespace())
    finally:
        reset_tenant_context(tokens)
    assert "tracked.txt" in stat and "u0.txt" in stat and "另有" in stat

    def _boom() -> None:
        raise RuntimeError("no root")

    monkeypatch.setattr("app.tenant_context.current_work_root_path", _boom)
    assert work_diff_stat(SimpleNamespace()) == ""


@pytest.mark.asyncio
async def test_product_verify_hook_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.engine.product_finish import run_product_verify_hook

    idle = SimpleNamespace(
        ops_eval=False,
        scenario_id="agent",
        product_hook_ran=False,
        verify_pending=False,
        related_tests_union=[],
        turn_id="t",
    )
    assert await run_product_verify_hook(SimpleNamespace(ops_eval=False, scenario_id="writing")) is None
    monkeypatch.setattr(settings, "product_post_edit_hook", False)
    assert await run_product_verify_hook(idle) is None
    monkeypatch.setattr(settings, "product_post_edit_hook", True)
    idle.product_hook_ran = True
    assert await run_product_verify_hook(idle) is None
    idle.product_hook_ran = False
    assert await run_product_verify_hook(idle) is None
    idle.verify_pending = True
    assert await run_product_verify_hook(idle) is None
    idle.related_tests_union = [{"command": "pytest -q", "path": "t.py"}]

    async def _ran(**_kwargs):
        return {"status": "executed", "exit_code": 0}

    monkeypatch.setattr("app.tools.core.edit_tools.run_tests", _ran)
    result = await run_product_verify_hook(idle)
    assert result is not None and result["product_hook"] is True and idle.product_hook_ran is True


@pytest.mark.asyncio
async def test_background_command_poll_and_kill(tmp_path) -> None:
    from app.tools.core import background_jobs as jobs

    jobs._JOBS.clear()
    cwd = tmp_path
    missing = await jobs.background_command(
        command="",
        job_id="",
        background=False,
        kill=False,
        cwd=cwd,
        timeout_s=1,
        turn_id=None,
    )
    assert missing["status"] == "error"
    assert (await jobs.background_command(
        command="",
        job_id="nope",
        background=False,
        kill=False,
        cwd=cwd,
        timeout_s=1,
        turn_id=None,
    ))["error"] == "unknown job_id"

    started = asyncio.Event()
    release = asyncio.Event()

    async def _hang(**_kwargs):
        started.set()
        await release.wait()
        return {"status": "executed", "stdout": "ok", "summary": "done"}

    with patch("app.tools.core.shell.run_shell_command", _hang):
        first = await jobs.background_command(
            command="sleep 5",
            job_id="",
            background=True,
            kill=False,
            cwd=cwd,
            timeout_s=5,
            turn_id=None,
        )
        await started.wait()
        running = await jobs.background_command(
            command="",
            job_id=first["job_id"],
            background=False,
            kill=False,
            cwd=cwd,
            timeout_s=1,
            turn_id=None,
        )
        assert running["status"] == "running"
        await jobs.background_command(
            command="",
            job_id=first["job_id"],
            background=False,
            kill=True,
            cwd=cwd,
            timeout_s=1,
            turn_id=None,
        )
        cancelled = {}
        for _ in range(20):
            cancelled = await jobs.background_command(
                command="",
                job_id=first["job_id"],
                background=False,
                kill=False,
                cwd=cwd,
                timeout_s=1,
                turn_id=None,
            )
            if cancelled.get("summary") == "background command cancelled":
                break
            await asyncio.sleep(0.01)
        assert cancelled["status"] == "cancelled"

        release.set()
        second = await jobs.background_command(
            command="echo ok",
            job_id="",
            background=True,
            kill=False,
            cwd=cwd,
            timeout_s=5,
            turn_id=None,
        )
        task = jobs._JOBS[second["job_id"]]["task"]
        await task
        done = await jobs.background_command(
            command="",
            job_id=second["job_id"],
            background=False,
            kill=False,
            cwd=cwd,
            timeout_s=1,
            turn_id=None,
        )
        assert done["status"] == "executed" and done["stdout"] == "ok"
    jobs._JOBS.clear()


def test_read_registry_stale_and_fold(tmp_path) -> None:
    from app.engine.read_registry import (
        PathReadState,
        _format_ranges,
        bind_read_registry,
        deny_redundant_read,
        deserialize_read_registry,
        diff_since_read,
        disk_content_hash,
        file_changed_since_read,
        mark_registry_stale,
        note_edit_failure_allows_reread,
        note_written_hash,
        omit_read_file_content_payload,
        path_from_tool_arguments,
        remember_read_body,
        reset_read_registry,
        user_facing_policy_summary,
        write_conflicts_with_read,
    )
    from app.engine import read_registry as registry_mod

    assert deserialize_read_registry(None) == {}
    loaded = deserialize_read_registry({"": {"whole_file_complete": True}, "a.py": "nope"})
    assert loaded["a.py"].whole_file_complete is False
    assert PathReadState.from_dict(None).content_hash == ""
    assert _format_ranges([]) == "(none)"
    assert "…" in _format_ranges([(i, i) for i in range(8)])
    assert path_from_tool_arguments(None) == ""
    assert path_from_tool_arguments({"path": "./a.py"}) == "a.py"
    assert "完整读过" in user_facing_policy_summary("read_after_complete", path="a.py")
    assert "已读过" in user_facing_policy_summary("read_overlap", path="a.py")
    assert "上限" in user_facing_policy_summary("read_budget", budget=4)
    assert "策略" in user_facing_policy_summary("other")

    registry: dict[str, PathReadState] = {}
    note_edit_failure_allows_reread(registry, path="")
    note_edit_failure_allows_reread(registry, path="a.py")
    assert registry["a.py"].allow_reread_once is True
    note_written_hash(registry, path="", content_hash="abc")
    note_written_hash(registry, path="missing.py", content_hash="abc")
    note_written_hash(registry, path="a.py", content_hash="")
    note_written_hash(registry, path="a.py", content_hash="abc")
    assert registry["a.py"].content_hash == "abc" and registry["a.py"].allow_reread_once is False
    assert deny_redundant_read(registry, path="") is None
    assert deny_redundant_read({}, path="a.py") is None
    registry["a.py"].allow_reread_once = True
    assert deny_redundant_read(registry, path="a.py") is None
    registry["a.py"].allow_reread_once = False
    registry["a.py"].next_offset = 10
    assert deny_redundant_read(registry, path="a.py", offset=10) is None
    registry["a.py"].next_offset = None
    assert deny_redundant_read(registry, path="a.py", evicted_paths={"a.py"}, evicted_reread_used=set()) is None
    registry["a.py"].whole_file_complete = True
    registry["a.py"].content_hash = "stale"
    assert deny_redundant_read(registry, path="a.py") is None
    registry["a.py"].content_hash = "old"
    assert deny_redundant_read(registry, path="a.py", disk_hash="new") is None
    denied = deny_redundant_read(registry, path="a.py", disk_hash="old")
    assert denied and denied.startswith("read_after_complete")
    registry["a.py"].whole_file_complete = False
    registry["a.py"].covered_ranges = [(1, 3)]
    assert deny_redundant_read(registry, path="a.py", offset=2).startswith("read_overlap")

    assert write_conflicts_with_read("a.py") is None
    assert file_changed_since_read("a.py") is False
    target = tmp_path / "a.py"
    target.write_text("one\n", encoding="utf-8")
    tokens = bind_tenant_context(work_root=str(tmp_path))
    reg_token = bind_read_registry(registry)
    registry_mod._READ_BODIES.clear()
    try:
        digest = disk_content_hash("a.py")
        assert digest
        assert disk_content_hash("missing.py") is None
        assert disk_content_hash(".") is None
        registry["a.py"].content_hash = digest
        assert write_conflicts_with_read("a.py") is None
        assert file_changed_since_read("a.py") is False
        registry["empty.py"] = PathReadState()
        registry["stale.py"] = PathReadState(content_hash="stale")
        target.write_text("two\n", encoding="utf-8")
        mark_registry_stale(registry)
        assert registry["a.py"].content_hash == "stale"
        assert file_changed_since_read("a.py") is True
        registry["a.py"].content_hash = digest
        remember_read_body("a.py", "one\n")
        conflict = write_conflicts_with_read("a.py")
        assert conflict is not None and "changed since" in conflict["summary"]
        assert "one" in diff_since_read("a.py")
        remember_read_body("gone.py", "old")
        assert diff_since_read("gone.py") == ""
        remember_read_body("", "x")
        remember_read_body("long.py", "z" * 50_000)
        for index in range(41):
            remember_read_body(f"p{index}.py", "body")
        assert diff_since_read("nope.py") == ""
        assert file_changed_since_read("nope.py") is False
        bare: dict[str, PathReadState] = {}
        bare_token = bind_read_registry(bare)
        try:
            assert write_conflicts_with_read("a.py") is None
        finally:
            reset_read_registry(bare_token)
        empty_hash = {"a.py": PathReadState()}
        hash_token = bind_read_registry(empty_hash)
        try:
            assert write_conflicts_with_read("a.py") is None
        finally:
            reset_read_registry(hash_token)
        target.unlink()
        gone = {"a.py": PathReadState(content_hash=digest or "abc")}
        gone_token = bind_read_registry(gone)
        try:
            assert write_conflicts_with_read("a.py") is None
        finally:
            reset_read_registry(gone_token)
    finally:
        reset_read_registry(reg_token)
        reset_tenant_context(tokens)
        registry_mod._READ_BODIES.clear()

    folded = omit_read_file_content_payload(
        {
            "path": "a.py",
            "content": "HEAD" + ("m" * 400) + "TAIL",
            "offset": "bad",
            "end_line": "bad",
            "hint": "again",
        }
    )
    assert folded["_folded_read"] is True and "tail" in folded["content"] and folded["hint"] == "again"
    short = omit_read_file_content_payload({"path": "a.py", "content": "hi", "offset": 1, "end_line": 1})
    assert "tail" not in short["content"]


@pytest.mark.asyncio
async def test_file_diagnostics_and_cross_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.structural.types import Issue
    from app.tools.core.edit_tools import _cross_file_diagnostics, _file_diagnostics_issues, _generic_lint_line

    assert _generic_lint_line("not a diagnostic", default_path="a.py") is None
    parsed = _generic_lint_line("a.go:2:3: unused", default_path="a.go")
    assert parsed is not None and parsed.line == 2

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "a.go").write_text("package p\n", encoding="utf-8")
    tokens = bind_tenant_context(work_root=str(tmp_path))

    async def _ruff(_paths, cwd, timeout_s):
        return "not-a-line\na.py:1:1: F401 unused"

    async def _lsp(*_args, **_kwargs):
        return {
            "issues": [
                Issue(
                    path="a.py",
                    line=1,
                    col=1,
                    severity="warning",
                    message="shadow",
                    provider="pyright",
                    code="reportUnused",
                    sources=("lsp",),
                )
            ],
            "meta": {"cold_start": True, "provider": "pyright"},
        }

    try:
        monkeypatch.setattr("app.structural.ruff_resident.ruff_concise", _ruff)
        monkeypatch.setattr("app.structural.adapters.get_diagnostics", _lsp)
        issues, meta = await _file_diagnostics_issues("a.py", timeout_s=2)
        assert issues and meta["cold_start"] is True and "pyright" in meta["provider"]

        async def _lsp_plain(*_args, **_kwargs):
            return {
                "issues": [
                    Issue(
                        path="a.py",
                        line=1,
                        col=1,
                        severity="warning",
                        message="only",
                        provider="lsp",
                        code="",
                        sources=("lsp",),
                    )
                ],
                "meta": {"degraded_reason": "partial"},
            }

        monkeypatch.setattr("app.structural.adapters.get_diagnostics", _lsp_plain)
        _issues, meta = await _file_diagnostics_issues("a.py", timeout_s=2)
        assert meta["degraded_reason"] == "partial" and meta["provider"] == "lsp+ruff"

        async def _argv(**_kwargs):
            return {"stdout": "noise\na.go:1:1: vet", "stderr": "a.go:2:1: extra"}

        monkeypatch.setattr("app.tools.core.shell.run_argv_command", _argv)
        issues, meta = await _file_diagnostics_issues("a.go", timeout_s=2)
        assert any(issue.path.endswith("a.go") or issue.line for issue in issues)
        assert meta["language"] == "go"

        monkeypatch.setattr("app.structural.adapters.get_diagnostics", _lsp)
        monkeypatch.setattr("app.structural.languages.linter_argv_for", lambda _language, _path: [])
        _issues, meta = await _file_diagnostics_issues("a.go", timeout_s=2)
        assert meta["degraded_reason"] == "linter_unavailable"

        async def _timeout(*_args, **_kwargs):
            raise asyncio.TimeoutError

        monkeypatch.setattr("app.structural.languages.linter_argv_for", lambda *_a, **_k: ["go", "vet", "a.go"])
        monkeypatch.setattr("app.tools.core.shell.run_argv_command", _timeout)
        _issues, meta = await _file_diagnostics_issues("a.go", timeout_s=0.01)
        assert "timeout" in (meta["degraded_reason"] or "")

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr("app.structural.ruff_resident.ruff_concise", _boom)
        monkeypatch.setattr("app.structural.adapters.get_diagnostics", _timeout)
        _issues, meta = await _file_diagnostics_issues("a.py", timeout_s=2)
        assert meta["degraded_reason"] == "timeout_or_error:lsp"

        monkeypatch.setattr("app.structural.adapters.get_diagnostics", _boom)
        _issues, meta = await _file_diagnostics_issues("a.py", timeout_s=2)
        assert meta["degraded_reason"].startswith("lsp_error")

        async def _diag(path, **_kwargs):
            if path == "bad.py":
                raise RuntimeError("nope")
            return [], {}

        monkeypatch.setattr("app.tools.core.edit_tools._file_diagnostics_issues", _diag)

        class _Loc:
            def to_dict(self) -> dict[str, str]:
                return {"path": "b.py"}

        same = await _cross_file_diagnostics([_Loc()], old_text="def a():\n    pass\n", new_text="def a():\n    pass\n", turn_id=None)
        assert same == []
        locs = [_Loc(), "skip", {"path": ""}, {"path": "bad.py"}, *({"path": f"f{i}.py"} for i in range(6))]
        rows = await _cross_file_diagnostics(
            locs,
            old_text="def a():\n    pass\n",
            new_text="def b(x):\n    pass\n",
            turn_id=None,
        )
        assert any(row.get("suggestion") == "read_lints" for row in rows)
        assert len(rows) <= 5
    finally:
        reset_tenant_context(tokens)


def test_provider_discovery_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from app.structural import providers

    monkeypatch.setattr(providers.shutil, "which", lambda name: "/usr/bin/gopls" if name == "gopls" else None)
    found = providers.discover_provider("go")
    assert found is not None and found.argv[0] == "/usr/bin/gopls"
    monkeypatch.setattr(providers.shutil, "which", lambda _name: None)
    assert providers.discover_provider("go") is None

    def _based(name: str) -> str | None:
        return "/bin/basedpyright-langserver" if name == "basedpyright-langserver" else None

    monkeypatch.setattr(providers.shutil, "which", _based)
    based = providers.discover_python_provider()
    assert based is not None and based.argv[0].endswith("basedpyright-langserver")

    def _jedi(name: str) -> str | None:
        return "/bin/jedi-language-server" if name == "jedi-language-server" else None

    monkeypatch.setattr(providers.shutil, "which", _jedi)
    jedi = providers.discover_python_provider()
    assert jedi is not None and jedi.name == "jedi"

    monkeypatch.setattr(providers.shutil, "which", lambda _name: None)
    module = sys.modules.pop("jedi_language_server", None)
    try:
        import types

        sys.modules["jedi_language_server"] = types.ModuleType("jedi_language_server")
        bundled = providers.discover_python_provider()
        assert bundled is not None and bundled.argv[-1] == "jedi_language_server"
        sys.modules.pop("jedi_language_server", None)

        real_import = __import__

        def _hide(name, *args, **kwargs):
            if name == "jedi_language_server":
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _hide)
        assert providers.discover_python_provider() is None
    finally:
        if module is not None:
            sys.modules["jedi_language_server"] = module
        else:
            sys.modules.pop("jedi_language_server", None)
    assert providers.initialization_options("pyright")["python"]["analysis"]["diagnosticMode"] == "openFilesOnly"
    assert providers.initialization_options("other") == {}


def test_exec_config_paths() -> None:
    from app.tools.core.paths import is_exec_config_path, write_path_block

    blocked = write_path_block(".git/config")
    assert blocked is not None and blocked["error"] == "metadata_path"
    assert is_exec_config_path("package.json") is True
    assert is_exec_config_path(".github/workflows/ci.yml") is True
    assert is_exec_config_path("src/app.py") is False


@pytest.mark.asyncio
async def test_shell_tail_truncation_and_egress(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core.shell import (
        MAX_OUTPUT_CHARS,
        _execute_via_egress,
        bind_command_output_sink,
        reset_command_output_sink,
        run_shell_command,
    )

    monkeypatch.setenv("TOOL_SANDBOX", "off")
    monkeypatch.setenv("ALLOW_UNSANDBOXED_EXEC", "true")
    monkeypatch.setattr(settings, "egress_host_allowlist", "")
    seen: list[str] = []

    async def _sink(text: str) -> None:
        seen.append(text)

    proc = MagicMock()
    proc.pid = 1
    proc.returncode = 0
    proc.stdout = _BytesStream(b"x" * (MAX_OUTPUT_CHARS + 5))
    proc.stderr = _BytesStream(b"y" * (MAX_OUTPUT_CHARS + 5))
    proc.wait = AsyncMock(return_value=0)
    token = bind_command_output_sink(_sink)
    try:
        with patch("app.tools.core.shell.asyncio.create_subprocess_shell", AsyncMock(return_value=proc)):
            result = await run_shell_command(command="echo hi", cwd=tmp_path, timeout_s=5)
    finally:
        reset_command_output_sink(token)
    assert result["is_truncated"] is True and seen

    async def _no_fetch(*_args, **_kwargs):
        raise AssertionError("proxy must not run")

    monkeypatch.setattr("app.policy.egress.proxy_request", _no_fetch)
    denied = await _execute_via_egress(["curl", "https://example.com/a"], display="curl")
    assert denied is not None and denied["status"] == "failed"
    assert "example.com" in str(denied.get("egress_denied") or denied.get("summary"))


@pytest.mark.asyncio
async def test_authorized_http_fetch_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core.http_fetch import bind_fetch_authorized, http_fetch, reset_fetch_authorized

    monkeypatch.setattr(settings, "egress_host_allowlist", "")

    class _Response:
        status_code = 204
        text = "body"

    async def _proxy(*_args, **_kwargs):
        return _Response()

    monkeypatch.setattr("app.policy.egress.proxy_request", _proxy)
    token = bind_fetch_authorized(True)
    try:
        ok = await http_fetch(
            url="https://example.com/a",
            state=SimpleNamespace(window_taint="user", messages=[], turn_user_text=""),
        )
    finally:
        reset_fetch_authorized(token)
    assert ok["status"] == "ok"
