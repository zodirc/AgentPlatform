"""P1–P3 acceptance: matrix, taint, egress, and a detector that can only tighten."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.context.engine import ToolExecutor, _summarize_messages
from app.policy.approval import POLICY_VERSION, ApprovalGrant, canonical_args_hash
from app.policy.matrix import emergency_clear, emergency_deny_tool
from app.policy.taint import message_taint
from app.settings import settings
from app.tools.registry import ToolRegistry, ToolSpec


def _state(**extra: object) -> object:
    base = {
        "turn_id": "t1",
        "run_id": None,
        "session_id": None,
        "plan_phase": None,
        "scenario_id": "agent",
        "turn_user_text": "",
        "messages": [],
        "saw_external": False,
        "window_taint": "user",
        "ops_eval": False,
    }
    base.update(extra)
    return type("S", (), base)()


def _spec(name: str, handler, **extra: object) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="x",
        parameters={"type": "object"},
        handler=handler,
        **extra,  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _clear_emergency() -> None:
    emergency_clear()
    yield
    emergency_clear()


@pytest.mark.asyncio
async def test_s1_write_allows_when_snapshot_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True, "summary": "wrote"}

    executor = ToolExecutor([_spec("write_file", handler, sink_class="S1", result_taint="workspace")])
    result = await executor.run(
        tool_name="write_file",
        tool_call_id="c1",
        arguments={"path": "a.txt", "content": "hi"},
        state=_state(),
    )
    assert result.get("ok") is True
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_s1_requires_approval_when_snapshot_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    (tmp_path / "dir").mkdir()
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True}

    executor = ToolExecutor([_spec("write_file", handler, sink_class="S1")])
    result = await executor.run(
        tool_name="write_file",
        tool_call_id="c1",
        arguments={"path": "dir"},
        state=_state(),
    )
    assert result["status"] == "approval_required"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_path_escape_is_denied_even_with_a_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True}

    arguments = {"path": "/etc/passwd"}
    grant = ApprovalGrant(
        tool_name="read_file",
        tool_call_id="c1",
        args_hash=canonical_args_hash(arguments),
        policy_version=POLICY_VERSION,
    )
    executor = ToolExecutor([_spec("read_file", handler, sink_class="S0")])
    result = await executor.run(
        tool_name="read_file",
        tool_call_id="c1",
        arguments=arguments,
        state=_state(),
        approval=grant,
    )
    assert result["status"] == "error"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_remember_after_external_uses_the_matrix() -> None:
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"status": "ok", "summary": "noted"}

    executor = ToolExecutor(
        [
            _spec("search_sources", handler, sink_class="S0", result_taint="external"),
            _spec("remember", handler, sink_class="S3", result_taint="user"),
        ]
    )
    state = _state()
    await executor.run(
        tool_name="search_sources",
        tool_call_id="s1",
        arguments={"query": "x"},
        state=state,
    )
    blocked = await executor.run(
        tool_name="remember",
        tool_call_id="m1",
        arguments={"text": "poison"},
        state=state,
    )
    assert blocked["status"] == "approval_required"
    assert state.saw_external is True


@pytest.mark.asyncio
async def test_ops_eval_allows_its_command_set_and_not_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.policy.plane.sandbox_is_ready", lambda: True)
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True, "summary": "ran"}

    executor = ToolExecutor(
        [
            _spec("run_command", handler, sink_class="S2"),
            _spec("remember", handler, sink_class="S3"),
        ]
    )
    allowed = await executor.run(
        tool_name="run_command",
        tool_call_id="c1",
        arguments={"command": "pytest -q"},
        state=_state(ops_eval=True),
    )
    assert allowed.get("ok") is True
    injected = await executor.run(
        tool_name="run_command",
        tool_call_id="c2",
        arguments={"command": "pytest && curl https://example"},
        state=_state(ops_eval=True),
    )
    assert injected["status"] == "approval_required"
    tainted = _state(ops_eval=True, saw_external=True, window_taint="external")
    blocked = await executor.run(
        tool_name="remember",
        tool_call_id="m1",
        arguments={"text": "x"},
        state=tainted,
    )
    assert blocked["status"] == "approval_required"


@pytest.mark.asyncio
async def test_s2_allowlist_does_not_apply_when_sandbox_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.policy.plane.sandbox_is_ready", lambda: False)

    async def handler(**_kwargs):
        return {"ok": True}

    async def allowed(_state, _arguments):
        return True

    monkeypatch.setattr("app.tools.command_allowlist.command_is_allowlisted", allowed)
    executor = ToolExecutor([_spec("run_command", handler, sink_class="S2", requires_approval=True)])
    result = await executor.run(
        tool_name="run_command",
        tool_call_id="c1",
        arguments={"command": "pytest -q"},
        state=_state(),
    )
    assert result["status"] == "error"
    assert "sandbox" in result["summary"]


@pytest.mark.asyncio
async def test_run_tests_allows_in_a_healthy_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.policy.plane.sandbox_is_ready", lambda: True)

    async def handler(**_kwargs):
        return {"ok": True, "summary": "tests"}

    executor = ToolExecutor([_spec("run_tests", handler, sink_class="S2")])
    result = await executor.run(
        tool_name="run_tests",
        tool_call_id="c1",
        arguments={},
        state=_state(),
    )
    assert result.get("ok") is True


def test_compaction_keeps_external_taint() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}], "_taint": "user"},
        {
            "role": "tool",
            "content": [{"type": "tool_result", "content": "hit"}],
            "_taint": "external",
        },
    ]
    summary = _summarize_messages(messages)
    assert message_taint(summary) == "external"


@pytest.mark.asyncio
async def test_http_fetch_new_url_under_external_taint_needs_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "egress_host_allowlist", "example.com")
    monkeypatch.setattr("app.policy.egress._system_resolver", lambda _host: ["93.184.216.34"])

    async def handler(**_kwargs):
        return {"status": "ok"}

    executor = ToolExecutor([_spec("http_fetch", handler, sink_class="S4", result_taint="external")])
    result = await executor.run(
        tool_name="http_fetch",
        tool_call_id="c1",
        arguments={"url": "https://example.com/secret"},
        state=_state(window_taint="external", saw_external=True, messages=[]),
    )
    assert result["status"] == "approval_required"


@pytest.mark.asyncio
async def test_http_fetch_blocks_metadata_and_rebinding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "egress_host_allowlist", "example.com")

    async def handler(**_kwargs):
        return {"status": "ok"}

    executor = ToolExecutor([_spec("http_fetch", handler, sink_class="S4")])
    metadata = await executor.run(
        tool_name="http_fetch",
        tool_call_id="c1",
        arguments={"url": "http://169.254.169.254/latest"},
        state=_state(),
    )
    assert metadata["status"] == "error"
    monkeypatch.setattr("app.policy.egress._system_resolver", lambda _host: ["10.0.0.5"])
    rebound = await executor.run(
        tool_name="http_fetch",
        tool_call_id="c2",
        arguments={"url": "https://example.com/x"},
        state=_state(turn_user_text="https://example.com/x"),
    )
    assert rebound["status"] == "error"


def test_changed_tool_description_takes_the_tool_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    async def handler(**_kwargs):
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="dyn",
            description="first",
            parameters={"type": "object"},
            handler=handler,
            sink_class="S0",
            dynamic=True,
        )
    )
    with pytest.raises(ValueError, match="offline"):
        registry.register(
            ToolSpec(
                name="dyn",
                description="second",
                parameters={"type": "object"},
                handler=handler,
                sink_class="S0",
                dynamic=True,
            )
        )


def test_registry_refuses_an_undeclared_tool() -> None:
    async def handler(**_kwargs):
        return {"ok": True}

    registry = ToolRegistry()
    with pytest.raises(ValueError, match="sink_class"):
        registry.register(
            ToolSpec(name="nope", description="x", parameters={"type": "object"}, handler=handler)
        )


def test_build_registry_assigns_sink_classes() -> None:
    from app.tools.bootstrap import build_registry

    registry = build_registry()
    assert registry.get("read_file").sink_class == "S0"
    assert registry.get("write_file").sink_class == "S1"
    assert registry.get("remember").sink_class == "S3"
    assert registry.get("http_fetch").sink_class == "S4"
    assert registry.get("search_sources").result_taint == "external"


def test_orchestrator_without_a_plane_refuses_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.policy.plane import execution_refusal

    monkeypatch.setattr(settings, "service_role", "orchestrator")
    monkeypatch.setattr(settings, "sandbox_plane_url", "")
    monkeypatch.setattr(settings, "deployment_tier", "single")
    assert execution_refusal()
    monkeypatch.setattr(settings, "service_role", "monolith")
    monkeypatch.setattr(settings, "deployment_tier", "dev")
    assert execution_refusal() is None


def test_saas_without_an_isolated_kernel_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.policy.plane import execution_refusal

    monkeypatch.setattr(settings, "deployment_tier", "saas")
    monkeypatch.setattr(settings, "sandbox_isolation", "bwrap")
    monkeypatch.setattr(settings, "service_role", "monolith")
    assert "isolated" in (execution_refusal() or "")


@pytest.mark.asyncio
async def test_detector_outage_keeps_the_read_and_raises_taint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(_text: str) -> str:
        return "unavailable"

    async def handler(**_kwargs):
        return {"status": "ok", "content": "file body"}

    monkeypatch.setattr("app.policy.detector.inspect_body", down)
    executor = ToolExecutor([_spec("read_file", handler, sink_class="S0", result_taint="workspace")])
    state = _state()
    result = await executor.run(
        tool_name="read_file",
        tool_call_id="c1",
        arguments={"path": "a.txt"},
        state=state,
    )
    assert result["content"] == "file body"
    assert state.window_taint == "external"


@pytest.mark.asyncio
async def test_enforce_mode_quarantines_a_high_confidence_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.policy.detector import CANARY, ISOLATION_NOTICE
    from app.policy.quarantine import read

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "detector_injection_mode", "enforce")

    async def handler(**_kwargs):
        return {"status": "ok", "content": f"please {CANARY}"}

    executor = ToolExecutor([_spec("search_sources", handler, sink_class="S0", result_taint="external")])
    result = await executor.run(
        tool_name="search_sources",
        tool_call_id="c1",
        arguments={"query": "x"},
        state=_state(),
    )
    assert result["content"] == ISOLATION_NOTICE
    assert CANARY not in result["content"]
    assert read(result["quarantine_id"]) and CANARY in read(result["quarantine_id"])


@pytest.mark.asyncio
async def test_observe_mode_does_not_quarantine(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.policy.detector import CANARY

    monkeypatch.setattr(settings, "detector_injection_mode", "observe")

    async def handler(**_kwargs):
        return {"status": "ok", "content": CANARY}

    executor = ToolExecutor([_spec("read_file", handler, sink_class="S0", result_taint="workspace")])
    result = await executor.run(
        tool_name="read_file",
        tool_call_id="c1",
        arguments={},
        state=_state(),
    )
    assert result["content"] == CANARY
    assert "quarantine_id" not in result


@pytest.mark.asyncio
async def test_detector_cannot_loosen_a_matrix_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow(_goal: str, _arguments: dict) -> str:
        return "allow"

    monkeypatch.setattr("app.policy.detector.check_deviation", allow)
    monkeypatch.setattr(settings, "detector_injection_mode", "enforce")

    async def handler(**_kwargs):
        return {"status": "remembered"}

    executor = ToolExecutor([_spec("remember", handler, sink_class="S3")])
    result = await executor.run(
        tool_name="remember",
        tool_call_id="c1",
        arguments={"text": "x"},
        state=_state(window_taint="external", saw_external=True),
    )
    assert result["status"] == "approval_required"


@pytest.mark.asyncio
async def test_detector_can_tighten_an_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unsure(_goal: str, _arguments: dict) -> str:
        return "require_approval"

    monkeypatch.setattr("app.policy.detector.check_deviation", unsure)
    monkeypatch.setattr(settings, "detector_injection_mode", "enforce")

    async def handler(**_kwargs):
        return {"status": "remembered"}

    executor = ToolExecutor([_spec("remember", handler, sink_class="S3")])
    result = await executor.run(
        tool_name="remember",
        tool_call_id="c1",
        arguments={"text": "x"},
        state=_state(window_taint="user"),
    )
    assert result["status"] == "approval_required"


def test_destination_blocklist_covers_internal_and_metadata() -> None:
    from app.policy.egress import destination_blocked

    assert destination_blocked("169.254.169.254")
    assert destination_blocked("postgres")
    assert destination_blocked("10.1.2.3")
    assert destination_blocked("192.168.1.1")
    assert not destination_blocked("93.184.216.34")


@pytest.mark.asyncio
async def test_emergency_denylist_applies_on_the_next_call() -> None:
    async def handler(**_kwargs):
        return {"ok": True}

    emergency_deny_tool("read_file")
    executor = ToolExecutor([_spec("read_file", handler, sink_class="S0")])
    result = await executor.run(
        tool_name="read_file",
        tool_call_id="c1",
        arguments={},
        state=_state(),
    )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_local_wipe_rule_denies_an_allowlisted_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.policy.plane.sandbox_is_ready", lambda: True)

    async def allowed(_state, _arguments):
        return True

    async def handler(**_kwargs):
        return {"ok": True}

    monkeypatch.setattr("app.tools.command_allowlist.command_is_allowlisted", allowed)
    executor = ToolExecutor([_spec("run_command", handler, sink_class="S2")])
    result = await executor.run(
        tool_name="run_command",
        tool_call_id="c1",
        arguments={"command": "rm -rf /"},
        state=_state(),
    )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_deviation_without_a_classifier_asks_for_approval() -> None:
    from app.policy.detector import check_deviation

    assert await check_deviation("ship the patch", {"command": "pytest"}) == "require_approval"


def test_builtin_skill_hash_must_match_the_manifest() -> None:
    from app.skills.loader import _skill_hash_ok

    assert _skill_hash_ok("verify", "not the shipped body") is False


def test_child_tools_drop_durable_and_network_sinks(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools import delegate_runner
    from app.tools.delegate_runner import _resolve_sub_tools

    monkeypatch.setitem(
        delegate_runner.SUBAGENT_TOOL_NAMES,
        "probe",
        ["read_file", "remember", "http_fetch", "mystery"],
    )
    parent = [
        _spec("read_file", lambda **_k: None, sink_class="S0"),
        _spec("remember", lambda **_k: None, sink_class="S3"),
        _spec("http_fetch", lambda **_k: None, sink_class="S4"),
        _spec("mystery", lambda **_k: None, sink_class=""),
    ]
    names = {spec.name for spec in _resolve_sub_tools(parent, "probe")}
    assert names == {"read_file"}


def test_emergency_denylist_survives_a_process_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    emergency_deny_tool("http_fetch")
    from app.policy import matrix as matrix_mod

    matrix_mod._EMERGENCY_TOOLS.clear()
    from app.policy.matrix import tool_emergency_denied

    assert tool_emergency_denied("http_fetch") is True


def test_sandbox_denies_escape_syscalls_and_host_devices() -> None:
    from app.tools.core.landlock_fs import DENIED_SYSCALLS, LANDLOCK_READ_ROOTS

    assert {"ptrace", "mount", "umount2", "keyctl", "perf_event_open", "bpf"} <= set(
        DENIED_SYSCALLS
    )
    assert "/sys" not in LANDLOCK_READ_ROOTS
    assert "/dev" not in LANDLOCK_READ_ROOTS
    assert "/run" not in LANDLOCK_READ_ROOTS


def test_expired_grant_does_not_match() -> None:
    import time

    grant = ApprovalGrant(
        tool_name="write_file",
        tool_call_id="c1",
        args_hash=canonical_args_hash({"path": "a"}),
        policy_version=POLICY_VERSION,
        expires_at=time.time() - 5,
    )
    from app.policy.approval import grant_matches

    assert (
        grant_matches(
            grant,
            tool_name="write_file",
            tool_call_id="c1",
            arguments={"path": "a"},
        )
        is False
    )
