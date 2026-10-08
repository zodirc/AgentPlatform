"""宿主协议、断点迁移、预算、回放对照与签名包。"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.engine.agent_engine import AgentEngine
from app.engine.state import TurnState, Usage
from app.model.gateway import ModelGateway, ModelResponse
from app.writing_host.errors import ResumeIncompatible
from app.writing_host.files import FileCheckpointStore
from app.writing_host.protocol import (
    PROTOCOL_VERSION,
    ModelConfig,
    TurnBudget,
    core_info,
    list_resumable,
    resume_turn,
    start_turn,
)
from app.writing_host.schema import migrate_checkpoint
from app.writing_host.trust import verify_package


def test_file_memory_roundtrip(tmp_path: Path):
    import asyncio

    from app.tenant_context import bind_tenant_context, reset_tenant_context
    from app.tools.core.memory_file import forget, recall, remember

    token = bind_tenant_context(work_root=str(tmp_path), work_id=uuid4(), owner_user_id=uuid4())
    try:
        saved = asyncio.run(remember(text="主角怕水", namespace="prefs"))
        found = asyncio.run(recall(query="怕水", namespace="prefs"))
        removed = asyncio.run(forget(memory_id=saved["id"]))
        empty = asyncio.run(recall(query="怕水", namespace="prefs"))
    finally:
        reset_tenant_context(token)
    assert saved["status"] == "ok"
    assert found["hits"]
    assert removed["deleted"] == 1
    assert empty["hits"] == []


def test_protocol_version_and_core_info():
    info = core_info()
    assert PROTOCOL_VERSION == "1.0"
    assert info.protocol_version == "1.0"
    assert info.core_version
    assert info.schema_versions["checkpoint"] == 1


def test_old_checkpoint_migrates_and_newer_is_rejected():
    bare = {"turn_id": "old", "step_count": 2, "messages": []}
    migrated = migrate_checkpoint(bare)
    assert migrated["schema_version"] == 1
    assert migrated["state"]["turn_id"] == "old"
    with pytest.raises(ResumeIncompatible):
        migrate_checkpoint({"schema_version": 99, "state": {}})


class _Once:
    async def stream(self, *, messages, tools, abort=None):
        del messages, tools, abort
        yield ModelResponse(
            text="到此为止",
            input_tokens=2,
            output_tokens=5,
            cache_read_input_tokens=1,
            cache_creation_input_tokens=1,
        )


@pytest.mark.asyncio
async def test_output_budget_ends_turn(tmp_path: Path):
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        max_steps=4,
        max_output_tokens=1,
    )

    async def write_event(**kwargs):
        del kwargs

    async def check_cancel():
        return False, False

    engine = AgentEngine(
        gateway=ModelGateway(_Once()),
        tools=[],
        system_prompt="BASE",
        write_event=write_event,
        check_cancel=check_cancel,
        context_window_tokens=8000,
    )
    summary = await engine.run(state)
    assert state.budget_exceeded is True
    assert state.termination_reason == "budget_exceeded"
    assert state.usage.cache_read_input_tokens == 1
    assert summary
    state.usage.output_tokens = 0
    state.usage.input_tokens = 3
    state.max_output_tokens = 0
    state.max_input_tokens = 1
    assert engine._budget_exceeded(state) is True


def _recording(tmp_path: Path, name: str, text: str) -> ModelConfig:
    path = tmp_path / "recordings"
    path.mkdir(exist_ok=True)
    (path / f"{name}.json").write_text(
        json.dumps({"steps": [{"text": text}]}),
        encoding="utf-8",
    )
    return ModelConfig(
        base_url="http://127.0.0.1",
        api_key="recording",
        model="recorded",
        context_window_tokens=8000,
        capabilities={"recordings_dir": str(path)},
    )


@pytest.mark.asyncio
async def test_recorded_turn_and_resume(tmp_path: Path):
    work = tmp_path / "book"
    model = _recording(tmp_path, "host_finish", "第一章写完了")
    events = []
    result = await start_turn(
        work_root=work,
        message="请看一下大纲",
        model=model,
        budget=TurnBudget(max_steps=1),
        on_event=events.append,
        recording="host_finish",
    )
    assert result.status == "ok"
    assert "第一章写完了" in result.summary
    assert any(event.type == "step_committed" for event in events)
    assert events[-1].type == "turn_finished"
    assert list_resumable(work)

    again = _recording(tmp_path, "host_more", "又写了一点")
    resumed = await resume_turn(
        work_root=work,
        turn_id=result.turn_id,
        model=again,
        budget=TurnBudget(max_steps=3),
        recording="host_more",
    )
    assert resumed.turn_id == result.turn_id
    assert "又写了一点" in resumed.summary


@pytest.mark.asyncio
async def test_host_and_server_registry_parity(tmp_path: Path):
    from app.tools.writing_registry import build_writing_registry

    host_names = set(build_writing_registry(host=True)._tools)
    server_names = set(build_writing_registry(host=False)._tools)
    assert host_names.isdisjoint({"search_sources", "check_citation", "delegate"})
    assert server_names - host_names == {"search_sources", "check_citation", "delegate"}

    left = tmp_path / "host"
    right = tmp_path / "server"
    model = _recording(tmp_path, "same_line", "同一句收束")
    host_result = await start_turn(
        work_root=left,
        message="请看一下大纲",
        model=model,
        budget=TurnBudget(max_steps=1),
        recording="same_line",
        host=True,
    )
    server_result = await start_turn(
        work_root=right,
        message="请看一下大纲",
        model=model,
        budget=TurnBudget(max_steps=1),
        recording="same_line",
        host=False,
    )
    assert host_result.summary == server_result.summary
    assert host_result.status == server_result.status


def test_cli_runs_recording_without_database(tmp_path: Path):
    import os
    import subprocess
    import sys

    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "cli_finish.json").write_text(
        json.dumps({"steps": [{"text": "命令行写完"}]}),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.writing_host.cli",
            "--work",
            str(tmp_path / "book"),
            "--message",
            "请看一下大纲",
            "--recording",
            "cli_finish",
            "--recordings-dir",
            str(recordings),
            "--max-steps",
            "1",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "命令行写完" in completed.stdout
    turn_line = next(line for line in completed.stdout.splitlines() if line.startswith("turn "))
    turn_id = turn_line.split()[1]
    (recordings / "cli_more.json").write_text(
        json.dumps({"steps": [{"text": "进程恢复后续写"}]}),
        encoding="utf-8",
    )
    resumed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.writing_host.cli",
            "--work",
            str(tmp_path / "book"),
            "--resume",
            turn_id,
            "--recording",
            "cli_more",
            "--recordings-dir",
            str(recordings),
            "--max-steps",
            "3",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert "进程恢复后续写" in resumed.stdout


def test_checkpoint_roundtrip_keeps_budget_fields(tmp_path: Path):
    store = FileCheckpointStore(tmp_path)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        usage=Usage(input_tokens=3, output_tokens=4, cache_read_input_tokens=8, cache_creation_input_tokens=2),
        max_input_tokens=11,
        max_output_tokens=12,
        related_tests_union=[{"path": "a.py", "command": "pytest"}, "b.py"],
    )

    async def save():
        await store.save(state=state, step_index=1)

    import asyncio

    asyncio.run(save())
    restored, _interrupt, step = store.load(str(state.turn_id))
    assert step == 1
    assert restored.max_input_tokens == 11
    assert restored.usage.cache_creation_input_tokens == 2
    assert restored.related_tests_union[0]["path"] == "a.py"
    assert restored.related_tests_union[1]["path"] == "b.py"


def _builder():
    import importlib.util

    path = Path(__file__).resolve().parents[3] / "scripts" / "build_writing_core.py"
    spec = importlib.util.spec_from_file_location("build_writing_core", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.build_package


def test_signed_package_verifies_and_rejects_tamper(tmp_path: Path):
    build_package = _builder()

    key = Ed25519PrivateKey.generate()
    archive = build_package(tmp_path / "dist", private_key=key)
    manifest = verify_package(archive, public=key.public_key())
    assert manifest["protocol_version"] == "1.0"
    assert manifest["core_version"]

    broken = tmp_path / "dist" / "broken.zip"
    broken.write_bytes(archive.read_bytes().replace(b"app/writing", b"app/writinh", 1))
    with pytest.raises(Exception):
        verify_package(broken, public=key.public_key(), signature=tmp_path / "dist" / "manifest.json.sig")


def test_version_must_change_when_package_hashes_change(tmp_path: Path):
    build_package = _builder()

    key = Ed25519PrivateKey.generate()
    build_package(tmp_path / "dist", private_key=key)
    previous = tmp_path / "previous.json"
    manifest_bytes = _manifest_bytes(tmp_path / "dist")
    previous.write_text(manifest_bytes, encoding="utf-8")
    data = json.loads(manifest_bytes)
    data["files"]["app/writing/VERSION"] = "0" * 64
    previous.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit):
        build_package(tmp_path / "again", private_key=key, previous_manifest=previous)


def test_event_log_keeps_recent_turns(tmp_path: Path):
    import asyncio

    from app.writing_host.files import FileEventLog
    from app.writing_host.schema import EVENT_KEEP_TURNS

    directory = tmp_path / ".agent" / "events"
    directory.mkdir(parents=True)
    for index in range(EVENT_KEEP_TURNS + 4):
        (directory / f"turn-{index:02d}.jsonl").write_text("{}\n", encoding="utf-8")
    asyncio.run(FileEventLog(tmp_path, "latest").append({"event_type": "usage"}))
    assert len(list(directory.glob("*.jsonl"))) == EVENT_KEEP_TURNS


def test_memory_file_has_schema_version(tmp_path: Path):
    import asyncio

    from app.tenant_context import bind_tenant_context, reset_tenant_context
    from app.tools.core.memory_file import remember

    token = bind_tenant_context(work_root=str(tmp_path), work_id=uuid4(), owner_user_id=uuid4())
    try:
        asyncio.run(remember(text="记得下雨", namespace="prefs"))
    finally:
        reset_tenant_context(token)
    payload = json.loads((tmp_path / "memory" / "memories.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["items"][0]["text"] == "记得下雨"


@pytest.mark.asyncio
async def test_draft_parity_and_section_nine(tmp_path: Path):
    from app.engine.agent_engine import AgentEngine
    from app.ports import get_embedder
    from app.writing_host.files import FileEvaluationStore, PlatformPrefsSource

    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "draft_once.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "tool_calls": [
                            {
                                "name": "draft_section",
                                "input": {"section_id": "ch-1", "content": "海边起风了。"},
                            }
                        ]
                    },
                    {"text": "这一章写好了"},
                ]
            }
        ),
        encoding="utf-8",
    )
    model = ModelConfig(
        base_url="http://127.0.0.1",
        api_key="recording",
        model="recorded",
        context_window_tokens=23456,
        capabilities={"recordings_dir": str(recordings)},
    )
    seen: dict[str, int] = {}
    original = AgentEngine.__init__

    def _capture(self, *args, **kwargs):
        seen["window"] = kwargs.get("context_window_tokens")
        return original(self, *args, **kwargs)

    AgentEngine.__init__ = _capture
    try:
        host_result = await start_turn(
            work_root=tmp_path / "host",
            message="续写第三章",
            model=model,
            budget=TurnBudget(max_steps=2),
            recording="draft_once",
            host=True,
        )
        server_result = await start_turn(
            work_root=tmp_path / "server",
            message="续写第三章",
            model=model,
            budget=TurnBudget(max_steps=2),
            recording="draft_once",
            host=False,
        )
    finally:
        AgentEngine.__init__ = original
    assert seen["window"] == 23456
    assert host_result.summary == server_result.summary
    assert host_result.termination_reason == server_result.termination_reason
    host_drafts = sorted((tmp_path / "host").rglob("*.md"))
    server_drafts = sorted((tmp_path / "server").rglob("*.md"))
    assert [path.read_text(encoding="utf-8") for path in host_drafts] == [
        path.read_text(encoding="utf-8") for path in server_drafts
    ]
    assert any("海边起风了" in path.read_text(encoding="utf-8") for path in host_drafts)
    assert (tmp_path / "host" / ".agent" / "work" / "format.json").is_file()
    assert await FileEvaluationStore(tmp_path / "host").load_turn(uuid4()) == []
    assert await PlatformPrefsSource().load_account(uuid4()) is None
    from app.ports import bind_embedder, reset_embedder

    token = bind_embedder(None)
    try:
        assert get_embedder() is None
    finally:
        reset_embedder(token)


def test_package_loads_and_rejected_package_keeps_current_kernel(tmp_path: Path):
    import os
    import subprocess
    import sys

    from app.writing_host.loader import load_kernel_package

    build_package = _builder()
    key = Ed25519PrivateKey.generate()
    archive = build_package(tmp_path / "dist", private_key=key)
    current = tmp_path / "current-kernel"
    current.mkdir()
    (current / "marker.txt").write_text("current", encoding="utf-8")
    loaded = load_kernel_package(
        archive,
        destination=tmp_path / "kernel",
        public=key.public_key(),
        signature=tmp_path / "dist" / "manifest.json.sig",
        current_root=current,
    )
    assert loaded.accepted
    assert loaded.root == tmp_path / "kernel"
    assert (current / "marker.txt").is_file()

    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "pkg_finish.json").write_text(
        json.dumps({"steps": [{"text": "包里写完"}]}),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(loaded.root)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.writing_host.cli",
            "--work",
            str(tmp_path / "book"),
            "--message",
            "续写第三章",
            "--recording",
            "pkg_finish",
            "--recordings-dir",
            str(recordings),
            "--max-steps",
            "1",
        ],
        cwd=str(loaded.root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "包里写完" in completed.stdout

    rejected = load_kernel_package(
        tmp_path / "dist" / "missing.zip",
        destination=tmp_path / "next",
        public=key.public_key(),
        current_root=loaded.root,
    )
    assert rejected.accepted is False
    assert rejected.root == loaded.root
    assert not (tmp_path / "next").exists()


def _manifest_bytes(dist: Path) -> str:
    import zipfile

    archive = next(dist.glob("writing-core-*.zip"))
    with zipfile.ZipFile(archive) as handle:
        return handle.read("manifest.json").decode("utf-8")
