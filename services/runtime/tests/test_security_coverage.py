"""Cover the security paths the matrix suite does not reach."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest

from app.policy import credentials, detector_service, matrix, plane, quarantine, scenario_policy
from app.settings import settings


def test_detector_service_ignores_keywords_and_catches_the_canary() -> None:
    assert detector_service.classify_text("ignore previous injection instructions") == "allow"
    assert detector_service.classify_text(detector_service.CANARY) == "deny"
    assert detector_service.classify_deviation("ship it", {"command": "pytest"}) == "allow"
    assert detector_service.classify_deviation("ship it", {"text": detector_service.CANARY}) == "deny"
    assert detector_service.handle("/inspect", {"text": "plain"})["verdict"] == "allow"
    assert detector_service.handle("/deviation", {"goal": "x", "arguments": "nope"})["verdict"] == "allow"


def test_broker_loads_config_and_strips_model_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials.clear_broker()
    monkeypatch.setattr(settings, "egress_broker", "example.com=sekret, bad, =missing, example.com=other")
    assert credentials.authorization_for("Example.com") == "Bearer sekret"
    credentials.set_broker_token("other.test", "Bearer already")
    assert credentials.authorization_for("other.test") == "Bearer already"
    assert credentials.authorization_for("") is None
    cleaned = credentials.strip_model_secrets(
        {"url": "https://example.com", "Authorization": "nope", "token": "x"}
    )
    assert cleaned == {"url": "https://example.com"}
    assert credentials.strip_model_secrets(None) == {}
    credentials.clear_broker()


def test_plane_refuses_saas_shared_kernel_and_a_failed_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core import sandbox

    monkeypatch.setattr(settings, "deployment_tier", "saas")
    monkeypatch.setattr(settings, "sandbox_isolation", "bwrap")
    monkeypatch.setattr(settings, "service_role", "monolith")
    assert "isolated kernel" in (plane.execution_refusal() or "")

    monkeypatch.setattr(settings, "sandbox_isolation", "gvisor")
    monkeypatch.setattr(sandbox, "escape_probe_report", lambda: {"ran": True, "ok": False})
    reason = plane.execution_refusal() or ""
    assert reason in {"saas tier requires a cgroup", "sandbox escape probe failed"}

    monkeypatch.setattr(settings, "deployment_tier", "dev")
    monkeypatch.setattr(settings, "service_role", "orchestrator")
    monkeypatch.setattr(settings, "sandbox_plane_url", "")
    monkeypatch.setattr(sandbox, "escape_probe_report", lambda: {"ran": False, "ok": None})
    assert plane.execution_refusal() == "orchestrator refuses exec without SANDBOX_PLANE_URL"
    assert plane.sandbox_is_ready() is False

    monkeypatch.setattr(plane, "execution_refusal", lambda: None)
    monkeypatch.setattr("app.tools.core.remote_sandbox.should_use_remote_sandbox", lambda: True)
    assert plane.sandbox_is_ready() is True


def test_scenario_overlay_can_only_shrink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")
    (tmp_path / "other.txt").write_text("y")

    def security(_scenario_id: str) -> dict:
        return {
            "version": "cov-1",
            "mode": "off",
            "paths": ["src"],
            "memory": {"external": "deny", "workspace": "approval"},
            "commands": "pytest",
            "network": {"hosts": "example.com"},
            "detectors": {"injection": "loud"},
            "matrix": {"S3": "deny"},
        }

    monkeypatch.setattr(scenario_policy, "_security", security)
    monkeypatch.setattr("app.tenant_context.current_work_root_path", lambda: tmp_path)
    assert scenario_policy.scenario_version("agent") == "cov-1"
    assert scenario_policy.scenario_mode("agent") == "observe"
    assert scenario_policy.structural_controls_hold("agent") is True
    assert scenario_policy.scenario_command_allowed("agent", "pytest -q") is False
    assert scenario_policy.scenario_network_hosts("agent") is None
    assert scenario_policy.scenario_detector_mode("agent") == ""
    assert scenario_policy.scenario_path_allowed("agent", {"path": str(tmp_path / "src" / "a.py")})
    assert scenario_policy.scenario_path_allowed("agent", {"path": str(tmp_path / "other.txt")}) is False
    assert scenario_policy.scenario_path_allowed("agent", {}) is True
    assert (
        scenario_policy.apply_overlay(
            "allow", sink="S3", scenario_id="agent", tool_name="remember", window_taint="external"
        )
        == "deny"
    )
    assert (
        scenario_policy.apply_overlay(
            "allow", sink="S3", scenario_id="agent", tool_name="remember", window_taint="workspace"
        )
        == "require_approval"
    )
    assert (
        scenario_policy.apply_overlay(
            "allow", sink="S3", scenario_id="agent", tool_name="load_skill", window_taint="user"
        )
        == "deny"
    )


def test_quarantine_release_returns_the_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "internal_service_token", "cov-token")
    item_id = quarantine.put(body="hidden", turn_id="t1", tool_name="read_file")
    assert quarantine.meta("missing") is None
    assert quarantine.read("missing", actor="u") is None
    stored = quarantine.meta(item_id)
    assert stored is not None and stored["access_count"] == 0
    released = quarantine.release(item_id, actor="owner")
    assert released is not None
    assert released["body"] == "hidden"
    assert quarantine.read(item_id, actor="owner") is None
    (tmp_path / "quarantine" / "bad.json").write_text("{", encoding="utf-8")
    assert quarantine.meta("bad") is None


def test_corrupt_emergency_file_is_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    path = tmp_path / "security" / "emergency.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    try:
        assert matrix.policy_unreadable() is True
        matrix.emergency_deny_command("")
        matrix.emergency_deny_host("evil.test")
        matrix.emergency_deny_command("curl")
    finally:
        matrix.emergency_clear()


def test_cgroup_limits_follow_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core import sandbox

    saved = dict(sandbox._CGROUP_STATE)
    orig_is_file = Path.is_file
    orig_mkdir = Path.mkdir
    orig_write = Path.write_text
    try:
        def is_file(self: Path) -> bool:
            if self == Path("/sys/fs/cgroup/cgroup.controllers"):
                return False
            return orig_is_file(self)

        monkeypatch.setattr(Path, "is_file", is_file)
        assert sandbox.apply_cgroup_limits()["configured"] is False

        def is_file_ready(self: Path) -> bool:
            if self == Path("/sys/fs/cgroup/cgroup.controllers"):
                return True
            return orig_is_file(self)

        def mkdir(self: Path, *args: object, **kwargs: object) -> None:
            if self == Path("/sys/fs/cgroup/agent-sandbox"):
                return None
            return orig_mkdir(self, *args, **kwargs)

        def write_text(self: Path, text: str, *args: object, **kwargs: object) -> int:
            if str(self).startswith("/sys/fs/cgroup/agent-sandbox"):
                return len(text)
            return orig_write(self, text, *args, **kwargs)

        monkeypatch.setattr(Path, "is_file", is_file_ready)
        monkeypatch.setattr(Path, "mkdir", mkdir)
        monkeypatch.setattr(Path, "write_text", write_text)
        sandbox._CGROUP_STATE["pid_attached"] = False
        report = sandbox.apply_cgroup_limits()
        assert report["configured"] is True
        assert sandbox.attach_sandbox_cgroup(42) is True
    finally:
        sandbox._CGROUP_STATE.clear()
        sandbox._CGROUP_STATE.update(saved)


def test_escape_probe_records_a_real_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core import sandbox

    saved = dict(sandbox._PROBE_CACHE)

    class Completed:
        returncode = 0

    try:
        monkeypatch.setattr(sandbox, "_which_bwrap", lambda: "/usr/bin/bwrap")
        monkeypatch.setattr(sandbox, "_bwrap_can_exec", lambda: True)
        monkeypatch.setattr(sandbox.subprocess, "run", lambda *_a, **_k: Completed())
        assert sandbox._probe_command_fails("/usr/bin/bwrap", ["true"]) is False
        report = sandbox.refresh_escape_probes()
        assert report["ok"] is False
    finally:
        sandbox._PROBE_CACHE = saved


def test_disk_quota_and_cgroup_attach(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core import sandbox

    (tmp_path / "big.txt").write_bytes(b"12345")
    monkeypatch.setattr(settings, "sandbox_disk_quota_bytes", 1)
    assert sandbox.work_disk_exceeded(tmp_path) is True
    monkeypatch.setattr(settings, "sandbox_disk_quota_bytes", 0)
    assert sandbox.work_disk_exceeded(tmp_path) is False
    assert sandbox.work_disk_exceeded(tmp_path / "missing") is False
    monkeypatch.setattr(settings, "sandbox_disk_quota_bytes", "nope")
    assert sandbox.disk_quota_bytes() == 0
    assert sandbox.attach_sandbox_cgroup(0) is False
    report = sandbox.apply_cgroup_limits()
    assert "disk_quota" in report


def test_escape_probe_does_not_pass_when_it_cannot_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core import sandbox

    saved = dict(sandbox._PROBE_CACHE)
    try:
        monkeypatch.setattr(sandbox, "_which_bwrap", lambda: "")
        report = sandbox.refresh_escape_probes()
        assert report["ok"] is None

        monkeypatch.setattr(sandbox, "_which_bwrap", lambda: "/usr/bin/bwrap")
        monkeypatch.setattr(sandbox, "_bwrap_can_exec", lambda: True)

        def boom(*_args, **_kwargs):
            raise OSError("no sandbox")

        monkeypatch.setattr(sandbox.subprocess, "run", boom)
        held = sandbox._probe_command_fails("/usr/bin/bwrap", ["true"])
        assert held is None
        report = sandbox.refresh_escape_probes()
        assert report["ok"] is None
    finally:
        sandbox._PROBE_CACHE = saved


@pytest.mark.asyncio
async def test_probe_loop_can_be_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core import sandbox

    def explode() -> dict[str, object]:
        raise RuntimeError("probe down")

    monkeypatch.setattr(sandbox, "refresh_escape_probes", explode)
    monkeypatch.setattr(settings, "sandbox_probe_interval_seconds", 30)
    sandbox._probe_task = None
    sandbox.start_escape_probe_loop()
    sandbox.start_escape_probe_loop()
    await asyncio.sleep(0.05)
    await sandbox.stop_escape_probe_loop()
    await sandbox.stop_escape_probe_loop()


@pytest.mark.asyncio
async def test_curl_goes_through_the_egress_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core.shell import _execute_via_egress

    assert await _execute_via_egress(["echo", "hi"], display="echo hi") is None
    missing = await _execute_via_egress(["curl", "-I"], display="curl -I")
    assert missing is not None and missing["sandbox"] == "egress"

    class Response:
        status_code = 200
        text = "ok"

    async def proxy(method, url, *, body, headers):
        assert method == "GET"
        assert url.startswith("https://")
        return Response()

    monkeypatch.setattr("app.policy.egress.classify_http", lambda *args, **kwargs: "allow")
    monkeypatch.setattr("app.policy.egress.proxy_request", proxy)
    fetched = await _execute_via_egress(["curl", "https://example.com/a"], display="curl")
    assert fetched is not None and fetched["_taint"] == "external"
    monkeypatch.setattr("app.policy.egress.classify_http", lambda *args, **kwargs: "deny")
    blocked = await _execute_via_egress(["wget", "https://example.com/a"], display="wget")
    assert blocked is not None and blocked["summary"] == "destination blocked"


@pytest.mark.asyncio
async def test_http_fetch_repeats_the_destination_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core.http_fetch import http_fetch

    monkeypatch.setattr(settings, "egress_host_allowlist", "")
    denied = await http_fetch(url="https://example.com/secret", state=SimpleNamespace(window_taint="user", messages=[], turn_user_text=""))
    assert denied["status"] == "failed"

    class Response:
        status_code = 204
        text = "body"

    async def proxy(*_args, **_kwargs):
        return Response()

    monkeypatch.setattr("app.tools.core.http_fetch.classify_http", lambda *args, **kwargs: "allow")
    monkeypatch.setattr("app.policy.egress.proxy_request", proxy)
    credentials.set_broker_token("example.com", "sekret")
    try:
        ok = await http_fetch(url="https://example.com/a", method="GET", body="ignored")
    finally:
        credentials.clear_broker()
    assert ok["status"] == "ok"
    assert ok["_taint"] == "external"

    async def broken(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr("app.policy.egress.proxy_request", broken)
    failed = await http_fetch(url="https://example.com/a")
    assert failed["status"] == "failed"


@pytest.mark.asyncio
async def test_turn_event_insert_falls_back_when_the_role_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.controller.events import _insert_turn_event

    calls: list[str] = []

    class Conn:
        async def execute(self, statement, *values):
            calls.append(statement)
            if "SAVEPOINT" in statement:
                raise RuntimeError("no transaction")

    monkeypatch.setattr(settings, "turn_events_insert_role", "")
    await _insert_turn_event(Conn(), "INSERT direct")
    assert calls == ["INSERT direct"]

    calls.clear()
    monkeypatch.setattr(settings, "turn_events_insert_role", "agent_runtime_append")
    await _insert_turn_event(Conn(), "INSERT fallback")
    assert calls[-1] == "INSERT fallback"

    class RoleConn:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def execute(self, statement, *values):
            self.calls.append(statement)
            if statement.startswith("SET LOCAL ROLE"):
                raise asyncpg.UndefinedObjectError("missing role")

    role_conn = RoleConn()
    await _insert_turn_event(role_conn, "INSERT after role")
    assert "INSERT after role" in role_conn.calls

    class UniqueConn:
        async def execute(self, statement, *values):
            if statement.startswith("INSERT"):
                raise asyncpg.UniqueViolationError("dup")

    with pytest.raises(asyncpg.UniqueViolationError):
        await _insert_turn_event(UniqueConn(), "INSERT clash")


@pytest.mark.asyncio
async def test_remote_sandbox_posts_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.tools.core.remote_sandbox import remote_sandbox_exec, should_use_remote_sandbox

    monkeypatch.setattr(settings, "sandbox_plane_url", "")
    monkeypatch.setattr(settings, "service_role", "orchestrator")
    assert should_use_remote_sandbox() is False
    with pytest.raises(RuntimeError):
        await remote_sandbox_exec(command="true", cwd="/tmp", timeout_seconds=1.0)

    monkeypatch.setattr(settings, "sandbox_plane_url", "http://plane")
    assert should_use_remote_sandbox() is True
    monkeypatch.setattr(settings, "service_role", "sandbox")
    assert should_use_remote_sandbox() is False
    monkeypatch.setattr(settings, "service_role", "orchestrator")

    payloads: list[dict] = [
        {"accepted": False, "detail": "no"},
        {"accepted": True, "status": "executed", "stdout": "ok"},
        ["nope"],
    ]

    class Response:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, *, json: dict, headers: dict) -> Response:
            assert json["network"] is False
            assert url.endswith("/internal/sandbox/exec")
            assert "X-Internal-Token" in headers
            return Response(payloads.pop(0))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: Client())
    rejected = await remote_sandbox_exec(command="true", cwd="/tmp", timeout_seconds=1.0, argv=["true"])
    assert rejected["sandbox"] == "remote"
    accepted = await remote_sandbox_exec(command="true", cwd="/tmp", timeout_seconds=1.0)
    assert accepted["stdout"] == "ok"
    invalid = await remote_sandbox_exec(command="true", cwd="/tmp", timeout_seconds=1.0)
    assert invalid["summary"] == "invalid sandbox plane response"


@pytest.mark.asyncio
async def test_shell_terminate_stops_the_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.core.shell import _terminate_process

    class Finished:
        returncode = 0
        pid = 1

        async def wait(self) -> int:
            return 0

    await _terminate_process(Finished(), force=True)

    class Running:
        def __init__(self) -> None:
            self.returncode = None
            self.pid = 99

        async def wait(self) -> int:
            self.returncode = -9
            return self.returncode

    calls = {"n": 0}

    def killpg(pid: int, sig: int) -> None:
        calls["n"] += 1
        if calls["n"] > 1:
            raise ProcessLookupError

    monkeypatch.setattr("app.tools.core.shell.os.killpg", killpg)
    await _terminate_process(Running(), force=False)
    await _terminate_process(Running(), force=True)


def test_shell_refuses_a_plane_and_keeps_argv0_on_the_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.tools.core.shell import _path_without_work_root, _plane_refusal, _resolve_argv0

    monkeypatch.setattr("app.tools.core.remote_sandbox.should_use_remote_sandbox", lambda: True)
    assert _plane_refusal("pytest") is None
    monkeypatch.setattr("app.tools.core.remote_sandbox.should_use_remote_sandbox", lambda: False)
    monkeypatch.setattr("app.policy.plane.execution_refusal", lambda: "sandbox down")
    refused = _plane_refusal("pytest")
    assert refused is not None and refused["sandbox"] == "error"

    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:")
    monkeypatch.setattr("app.tenant_context.current_work_root", lambda: str(tmp_path))
    path = _path_without_work_root()
    assert str(tmp_path) not in path.split(":")
    resolved = _resolve_argv0(["/bin/echo", "hi"])
    assert resolved[0] == "/bin/echo"
    assert _resolve_argv0([]) == []


@pytest.mark.asyncio
async def test_missing_parked_child_fails_closed() -> None:
    from app.tools.delegate_runner import resume_parked_child

    result = await resume_parked_child("missing", None)
    assert result["status"] == "failed"
