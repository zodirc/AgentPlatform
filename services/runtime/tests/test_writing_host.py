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
    assert any(event.type == "step.completed" for event in events)
    assert events[0].type == "turn.accepted"
    assert events[-1].type == "turn.completed"
    assert all(getattr(event, "turn_id", "") == result.turn_id for event in events)
    assert not list_resumable(work)
    assert (work / ".agent" / "checkpoints" / f"{result.turn_id}.json").is_file()

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


def test_event_append_does_not_sweep(tmp_path: Path):
    import asyncio

    from app.writing_host.files import FileEventLog
    from app.writing_host.schema import EVENT_KEEP_TURNS

    directory = tmp_path / ".agent" / "events"
    directory.mkdir(parents=True)
    for index in range(EVENT_KEEP_TURNS + 4):
        (directory / f"turn-{index:02d}.jsonl").write_text("{}\n", encoding="utf-8")
    asyncio.run(FileEventLog(tmp_path, "latest").append({"event_type": "usage"}))
    assert len(list(directory.glob("*.jsonl"))) == EVENT_KEEP_TURNS + 5


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


def test_runner_does_not_assign_process_settings():
    source = Path(__file__).resolve().parents[1].joinpath("app/writing_host/runner.py").read_text(encoding="utf-8")
    assert "settings." not in source


def test_preferred_plan_phase_keeps_confirm():
    from app.writing.intents import preferred_plan_phase

    assert preferred_plan_phase("executing", "planning") == "executing"
    assert preferred_plan_phase(None, "planning") == "planning"


def test_resolve_intent_messages(tmp_path: Path):
    from app.writing.intents import resolve_intent
    from app.writing.opening_ponds import save_opening_ponds
    from app.writing_host.errors import InvalidIntent

    saved = save_opening_ponds(
        [{"id": "a", "title": "余烬"}, {"id": "b", "title": "潮汐"}],
        workspace_root=tmp_path,
    )
    ponds_id = saved["ponds_id"]
    text, phase = resolve_intent(
        {"kind": "select_pond", "ponds_id": ponds_id, "item_id": "a"},
        workspace_root=tmp_path,
    )
    assert text == "就用这个开篇：余烬"
    assert "采用此开篇" not in text
    assert phase is None
    noted, _phase = resolve_intent(
        {"kind": "select_pond", "ponds_id": ponds_id, "item_id": "a"},
        message="更短一点",
        workspace_root=tmp_path,
    )
    assert noted.endswith("更短一点")
    assert "采用此开篇" not in noted
    more, _phase = resolve_intent(
        {"kind": "more_ponds", "ponds_id": ponds_id},
        workspace_root=tmp_path,
    )
    assert more == "再给一组开篇"
    from app.writing.candidates import remember_pending_patch, save_turn_plan

    save_turn_plan({"plan_id": "plan-1", "items": [], "awaiting_consent": True}, workspace_root=tmp_path)
    confirmed, executing = resolve_intent(
        {"kind": "confirm_plan", "plan_id": "plan-1"},
        message="附言",
        workspace_root=tmp_path,
    )
    assert confirmed == "附言"
    assert executing == "executing"
    remember_pending_patch(
        {"patch_id": "patch-1", "path": "outline.md", "old_text": "旧", "status": "pending"},
        workspace_root=tmp_path,
    )
    accepted, _phase = resolve_intent(
        {"kind": "accept_patch", "patch_id": "patch-1"},
        workspace_root=tmp_path,
    )
    assert accepted == "采用这个修订 patch-1"
    assert "采用补丁「" not in accepted
    rejected, _phase = resolve_intent(
        {"kind": "reject_patch", "patch_id": "patch-1"},
        workspace_root=tmp_path,
    )
    assert rejected == "不用这个修订 patch-1"
    with pytest.raises(InvalidIntent):
        resolve_intent({"kind": "select_pond", "ponds_id": "", "item_id": "a"})
    with pytest.raises(InvalidIntent):
        resolve_intent(
            {"kind": "select_pond", "ponds_id": "missing", "item_id": "a"},
            workspace_root=tmp_path,
        )
    with pytest.raises(InvalidIntent):
        resolve_intent(None, message="  ")
    with pytest.raises(InvalidIntent):
        resolve_intent(
            {"kind": "more_ponds", "ponds_id": "missing"},
            workspace_root=tmp_path,
        )
    with pytest.raises(InvalidIntent):
        resolve_intent(
            {"kind": "confirm_plan", "plan_id": "plan-old"},
            workspace_root=tmp_path,
        )
    with pytest.raises(InvalidIntent):
        resolve_intent(
            {"kind": "reject_patch", "patch_id": "patch-1"},
            workspace_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_intent_reaches_turn_accepted(tmp_path: Path):
    from app.writing.opening_ponds import save_opening_ponds

    work = tmp_path / "book"
    saved = save_opening_ponds(
        [{"id": "item-a", "title": "余烬"}, {"id": "item-b", "title": "潮汐"}],
        workspace_root=work,
    )
    model = _recording(tmp_path, "intent_finish", "收到开篇")
    events = []
    result = await start_turn(
        work_root=work,
        message="选择开篇",
        intent={"kind": "select_pond", "ponds_id": saved["ponds_id"], "item_id": "item-a"},
        model=model,
        budget=TurnBudget(max_steps=1),
        on_event=events.append,
        recording="intent_finish",
    )
    assert result.status == "ok"
    preview = events[0].payload["user_input_preview"]
    assert preview.startswith("就用这个开篇：余烬")
    assert "采用此开篇" not in preview


@pytest.mark.asyncio
async def test_reject_snapshot_restores_pending_patch(tmp_path: Path):
    from app.writing.candidates import latest_pending_patch, remember_pending_patch
    from app.writing_host.protocol import revert_turn

    work = tmp_path / "book"
    work.mkdir()
    (work / "outline.md").write_text("# 旧题\n", encoding="utf-8")
    remember_pending_patch(
        {
            "patch_id": "patch-1",
            "path": "outline.md",
            "old_text": "旧",
            "new_text": "新",
            "status": "pending",
        },
        workspace_root=work,
    )
    model = _recording(tmp_path, "reject_patch", "已放下")
    result = await start_turn(
        work_root=work,
        message="不用这个修订",
        intent={"kind": "reject_patch", "patch_id": "patch-1"},
        model=model,
        budget=TurnBudget(max_steps=1),
        recording="reject_patch",
    )
    assert latest_pending_patch(workspace_root=work) is None
    revert_turn(work, result.turn_id)
    restored = latest_pending_patch(workspace_root=work)
    assert restored is not None
    assert restored["patch_id"] == "patch-1"


@pytest.mark.asyncio
async def test_cancel_before_first_step(tmp_path: Path):
    from app.writing_host.protocol import cancel_turn

    work = tmp_path / "book"
    model = _recording(tmp_path, "never", "不会写到")
    turn_id = str(uuid4())
    cancel_turn(turn_id)
    events = []
    result = await start_turn(
        work_root=work,
        message="请看一下大纲",
        turn_id=turn_id,
        model=model,
        budget=TurnBudget(max_steps=1),
        on_event=events.append,
        recording="never",
    )
    assert result.status == "cancelled"
    assert [event.type for event in events] == ["turn.accepted", "turn.cancelled"]
    assert events[-1].payload["reason"] == "user_requested"
    assert not any(event.type == "step.started" for event in events)


@pytest.mark.asyncio
async def test_duplicate_turn_id_returns_original(tmp_path: Path):
    work = tmp_path / "book"
    model = _recording(tmp_path, "once", "只跑一次")
    turn_id = str(uuid4())
    first_events = []
    first = await start_turn(
        work_root=work,
        message="请看一下大纲",
        turn_id=turn_id,
        model=model,
        budget=TurnBudget(max_steps=1),
        on_event=first_events.append,
        recording="once",
    )
    second_events = []
    second = await start_turn(
        work_root=work,
        message="另一句",
        turn_id=turn_id,
        model=model,
        budget=TurnBudget(max_steps=1),
        on_event=second_events.append,
        recording="once",
    )
    assert second.turn_id == first.turn_id
    assert second.summary == first.summary
    assert second_events == []


@pytest.mark.asyncio
async def test_second_start_while_busy(tmp_path: Path):
    import asyncio
    import threading

    from app.writing_host.errors import Busy

    work = tmp_path / "book"
    model = _recording(tmp_path, "hold", "占住回合")
    held = threading.Event()
    release = threading.Event()

    def on_event(event):
        if event.type == "turn.accepted":
            held.set()
            assert release.wait(timeout=10)

    def run_first():
        asyncio.run(
            start_turn(
                work_root=work,
                message="请看一下大纲",
                model=model,
                budget=TurnBudget(max_steps=1),
                on_event=on_event,
                recording="hold",
            )
        )

    thread = threading.Thread(target=run_first)
    thread.start()
    assert held.wait(timeout=10)
    with pytest.raises(Busy):
        await start_turn(
            work_root=tmp_path / "other",
            message="第二个",
            model=model,
            budget=TurnBudget(max_steps=1),
            recording="hold",
        )
    release.set()
    thread.join(timeout=15)
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_read_events_replays_without_duplicates(tmp_path: Path):
    from app.writing_host.protocol import read_events

    work = tmp_path / "book"
    model = _recording(tmp_path, "replay", "补齐事件")
    live = []
    result = await start_turn(
        work_root=work,
        message="请看一下大纲",
        model=model,
        budget=TurnBudget(max_steps=1),
        on_event=live.append,
        recording="replay",
    )
    cut = 2
    replay = read_events(work, result.turn_id, after_sequence=cut)
    stitched = live[:cut] + replay
    assert [event.sequence for event in stitched] == [event.sequence for event in live]
    assert [event.type for event in stitched] == [event.type for event in live]
    assert [event.sequence for event in read_events(work, result.turn_id, after_sequence=0)] == [
        event.sequence for event in live
    ]


@pytest.mark.asyncio
async def test_step_completed_follows_checkpoint(tmp_path: Path):
    work = tmp_path / "book"
    model = _recording(tmp_path, "commit", "已提交")
    seen = []

    def on_event(event):
        if event.type == "step.completed":
            checkpoint = work / ".agent" / "checkpoints" / f"{event.turn_id}.json"
            assert checkpoint.is_file()
            assert "usage" in event.payload
        seen.append(event.type)

    await start_turn(
        work_root=work,
        message="请看一下大纲",
        model=model,
        budget=TurnBudget(max_steps=1),
        on_event=on_event,
        recording="commit",
    )
    assert seen[0] == "turn.accepted"
    assert "step.completed" in seen
    assert seen[-1] == "turn.completed"


@pytest.mark.asyncio
async def test_model_error_emits_turn_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.model.recorded_provider import RecordedModelProvider
    from app.writing_host.errors import NetworkError
    from app.writing_host.protocol import read_events

    async def boom(self, *, messages, tools, abort=None):
        del self, messages, tools, abort
        raise TimeoutError("timed out")
        yield ""  # pragma: no cover

    monkeypatch.setattr(RecordedModelProvider, "stream", boom)
    work = tmp_path / "book"
    model = _recording(tmp_path, "down", "不会用到")
    events = []
    with pytest.raises(NetworkError):
        await start_turn(
            work_root=work,
            message="请看一下大纲",
            model=model,
            budget=TurnBudget(max_steps=1),
            on_event=events.append,
            recording="down",
        )
    assert events[-1].type == "turn.failed"
    assert events[-1].payload["termination_reason"] == "model_timeout"
    assert events[-1].payload["error_kind"] == "network"
    logged = read_events(work, events[-1].turn_id)
    assert logged[-1].type == "turn.failed"


@pytest.mark.asyncio
async def test_budget_completed_and_work_roundtrip(tmp_path: Path):
    from app.writing_host.errors import Conflict
    from app.writing_host.protocol import (
        export_work,
        import_work,
        list_turn_history,
        read_document,
        revert_turn,
        work_view,
        write_document,
    )

    work = tmp_path / "book"
    work.mkdir(parents=True)
    (work / "outline.md").write_text("# 旧题\n原来的大纲\n", encoding="utf-8")
    before = work_view(work)
    model = _recording(tmp_path, "budget", "这句话会超出预算")
    events = []
    result = await start_turn(
        work_root=work,
        message="请看一下大纲",
        model=model,
        budget=TurnBudget(max_steps=2, max_output_tokens=1),
        on_event=events.append,
        recording="budget",
    )
    assert result.status == "budget_exceeded"
    assert events[-1].type == "turn.completed"
    assert events[-1].payload["termination_reason"] == "budget_exceeded"
    assert list_turn_history(work)
    (work / "outline.md").write_text("# 新题\n改过了\n", encoding="utf-8")
    doc = read_document(work, "outline")
    updated = write_document(work, "outline", "# 手改\n", base_revision=doc.revision)
    assert updated.revision != doc.revision
    with pytest.raises(Conflict):
        write_document(work, "outline", "# 再改\n", base_revision=doc.revision)
    revert_turn(work, result.turn_id)
    restored = work_view(work)
    assert restored.title == before.title
    assert read_document(work, "outline").text.startswith("# 旧题")
    assert list_turn_history(work) == []

    (work / "outline.md").write_text("# 旧题\n原来的大纲\n", encoding="utf-8")
    archive = tmp_path / "book.zip"
    export_work(work, archive)
    imported = import_work(archive, tmp_path / "restored")
    assert any(item.doc_id == "outline" for item in imported.documents)
    assert read_document(tmp_path / "restored", "outline").text.startswith("# 旧题")


def _turn_fixture(name: str) -> dict:
    path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "contracts"
        / "tests"
        / "fixtures"
        / "turns"
        / f"{name}.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_fixtures_follow_host_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """夹具的事件类型序列来自宿主回放，不另写一套。"""
    from app.model.recorded_provider import RecordedModelProvider

    def recorded(name: str, steps: list) -> ModelConfig:
        path = tmp_path / "recordings"
        path.mkdir(exist_ok=True)
        (path / f"{name}.json").write_text(json.dumps({"steps": steps}, ensure_ascii=False), encoding="utf-8")
        return ModelConfig(
            base_url="http://127.0.0.1",
            api_key="recording",
            model="recorded",
            context_window_tokens=8000,
            capabilities={"recordings_dir": str(path)},
        )

    async def replay(name: str, steps: list, **kwargs):
        events = []
        await start_turn(
            work_root=tmp_path / name,
            model=recorded(name, steps),
            on_event=events.append,
            recording=name,
            **kwargs,
        )
        return [event.type for event in events]

    text = await replay("text-turn", message="请看一下大纲", budget=TurnBudget(max_steps=1), steps=[{"text": "第一章写完了"}])
    assert text == [item["type"] for item in _turn_fixture("text-turn")["events"]]

    budget = await replay(
        "budget",
        message="请看一下大纲",
        budget=TurnBudget(max_steps=2, max_output_tokens=1),
        steps=[{"text": "这句话会超出预算"}],
    )
    assert budget == [item["type"] for item in _turn_fixture("budget")["events"]]
    assert _turn_fixture("budget")["events"][-1]["payload"]["termination_reason"] == "budget_exceeded"

    plan = await replay(
        "plan",
        message="先列一个计划",
        budget=TurnBudget(max_steps=3),
        plan_phase="planning",
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "update_plan",
                        "input": {
                            "items": [{"id": "1", "title": "写开篇", "status": "pending"}],
                            "summary": "先列计划",
                        },
                    }
                ]
            },
            {"text": "等你确认"},
        ],
    )
    assert plan == [item["type"] for item in _turn_fixture("plan")["events"]]
    assert _turn_fixture("plan")["view"]["plan"]["items"][0]["title"] == "写开篇"

    pitch_a = (
        "灾变之后，人类进入了一个新的时代。资源匮乏、军阀割据、势力林立，"
        "秦禹只想要活下去。但现实一步步把他推向了更大的舞台。"
        "他明天还得去领粮，也还得决定跟哪一路人站在一起。柜台上的账今晚必须对上，否则铺子开不了门。"
    )
    pitch_b = (
        "潮水每夜把码头的桩撞松一寸。她把船票攥在手里，货还堆在棚里，天亮前必须点清。"
        "岸上的人各算各的账，船老大只认定金。她还没决定人留在哪一岸，明天的班次却不会等。"
        "铺子里的灯火还亮着，她听得见账房在算今夜的损耗。"
    )
    opening = await replay(
        "opening",
        message="给我两个开篇",
        budget=TurnBudget(max_steps=4),
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "propose_book_candidates",
                        "input": {
                            "items": [
                                {"id": "pond-1", "title": "余烬", "pitch": pitch_a},
                                {"id": "pond-2", "title": "潮汐", "pitch": pitch_b},
                            ]
                        },
                    }
                ]
            },
            {"text": "等你点选"},
        ],
    )
    assert opening == [item["type"] for item in _turn_fixture("opening")["events"]]
    assert [item["title"] for item in _turn_fixture("opening")["view"]["opening_ponds"]["items"]] == [
        "余烬",
        "潮汐",
    ]

    (tmp_path / "patch" / "outline.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "patch" / "outline.md").write_text("# 旧题\n\n第一句还在。\n", encoding="utf-8")
    patch = await replay(
        "patch",
        message="改一下大纲标题",
        budget=TurnBudget(max_steps=4),
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "propose_patch",
                        "input": {
                            "path": "outline.md",
                            "old_text": "# 旧题",
                            "new_text": "# 新题",
                            "summary": "改标题",
                        },
                    }
                ]
            },
            {"text": "标题已提出"},
        ],
    )
    assert patch == [item["type"] for item in _turn_fixture("patch")["events"]]
    assert _turn_fixture("patch")["view"]["patch_candidates"][0]["path"] == "outline.md"
    assert _turn_fixture("patch")["view"]["patch_candidates"][0]["summary"] == "改标题"

    duplicate = _turn_fixture("resume-duplicate")
    assert duplicate["events"][0]["sequence"] == duplicate["events"][1]["sequence"]
    assert duplicate["view"]["last_event_sequence"] == _turn_fixture("text-turn")["view"]["last_event_sequence"]

    async def boom(self, *, messages, tools, abort=None):
        del self, messages, tools, abort
        raise TimeoutError("timed out")
        yield ""  # pragma: no cover

    monkeypatch.setattr(RecordedModelProvider, "stream", boom)
    events = []
    from app.writing_host.errors import NetworkError

    with pytest.raises(NetworkError):
        await start_turn(
            work_root=tmp_path / "failed",
            message="请看一下大纲",
            model=_recording(tmp_path, "failed", [{"text": "x"}]),
            budget=TurnBudget(max_steps=1),
            on_event=events.append,
            recording="failed",
        )
    assert [event.type for event in events] == [item["type"] for item in _turn_fixture("failed")["events"]]
    assert events[-1].payload["error_kind"] == "network"
    assert events[-1].payload["termination_reason"] == "model_timeout"


def test_kernel_package_includes_turn_fixtures(tmp_path: Path):
    import zipfile

    build_package = _builder()
    fixtures = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "tests" / "fixtures" / "turns"
    assert any(fixtures.glob("*.json"))
    archive = build_package(tmp_path / "dist", private_key=Ed25519PrivateKey.generate())
    with zipfile.ZipFile(archive) as handle:
        names = set(handle.namelist())
    assert any(name.startswith("fixtures/turns/") and name.endswith(".json") for name in names)
