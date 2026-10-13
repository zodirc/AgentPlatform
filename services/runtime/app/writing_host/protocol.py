"""写作宿主协议 1.0。桌面命令行与后续 Android 壳只调用这里。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PROTOCOL_VERSION = "1.0"

HostEventCallback = Callable[["HostEvent"], None]


@dataclass
class ModelConfig:
    base_url: str
    api_key: str
    model: str
    context_window_tokens: int = 128_000
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnBudget:
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    max_steps: int = 40


@dataclass
class HostEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnResult:
    turn_id: str
    summary: str
    termination_reason: str
    status: str


@dataclass
class ProbeCheck:
    name: str
    ok: bool
    reason: str = ""


@dataclass
class ProbeReport:
    ok: bool
    checks: list[ProbeCheck]


@dataclass
class ResumableTurn:
    turn_id: str
    step_index: int
    schema_version: int


@dataclass
class CoreInfo:
    core_version: str
    protocol_version: str
    schema_versions: dict[str, int]


def core_info() -> CoreInfo:
    from app.writing.version import core_version
    from app.writing_host.schema import SCHEMA_VERSIONS

    return CoreInfo(
        core_version=core_version(),
        protocol_version=PROTOCOL_VERSION,
        schema_versions=dict(SCHEMA_VERSIONS),
    )


def cancel_turn(turn_id: str) -> None:
    from app.writing_host.runner import cancel_turn as impl

    impl(turn_id)


def list_resumable(work_root: Path) -> list[ResumableTurn]:
    from app.writing_host.files import FileCheckpointStore

    rows = FileCheckpointStore(Path(work_root)).list_turns()
    return [
        ResumableTurn(
            turn_id=row["turn_id"],
            step_index=int(row["step_index"]),
            schema_version=int(row["schema_version"]),
        )
        for row in rows
    ]


def read_events(work_root: Path, turn_id: str, after_sequence: int = 0):
    from app.writing_host.events import read_events as impl

    return impl(Path(work_root), turn_id, after_sequence)


def work_view(work_root: Path):
    from app.writing_host.works import work_view as impl

    return impl(Path(work_root))


def read_document(work_root: Path, doc_id: str):
    from app.writing_host.works import read_document as impl

    return impl(Path(work_root), doc_id)


def write_document(work_root: Path, doc_id: str, text: str, *, base_revision: str):
    from app.writing_host.runner import turn_busy
    from app.writing_host.works import write_document as impl

    return impl(Path(work_root), doc_id, text, base_revision=base_revision, busy=turn_busy())


def list_turn_history(work_root: Path):
    from app.writing_host.works import list_turn_history as impl

    return impl(Path(work_root))


def revert_turn(work_root: Path, turn_id: str) -> None:
    from app.writing_host.runner import turn_busy
    from app.writing_host.errors import Busy
    from app.writing_host.works import revert_turn as impl

    if turn_busy():
        raise Busy()
    impl(Path(work_root), turn_id)


def export_work(work_root: Path, dest: Path) -> None:
    from app.writing_host.works import export_work as impl

    impl(Path(work_root), Path(dest))


def import_work(src: Path, work_root: Path):
    from app.writing_host.works import import_work as impl

    return impl(Path(src), Path(work_root))


async def start_turn(
    *,
    work_root: Path,
    message: str = "",
    model: ModelConfig,
    budget: TurnBudget,
    plan_phase: str | None = None,
    on_event: HostEventCallback | None = None,
    recording: str | None = None,
    host: bool = True,
    turn_id: str | None = None,
    intent: dict | None = None,
) -> TurnResult:
    from app.writing_host.runner import start_turn as impl

    return await impl(
        work_root=work_root,
        message=message,
        model=model,
        budget=budget,
        plan_phase=plan_phase,
        on_event=on_event,
        recording=recording,
        host=host,
        turn_id=turn_id,
        intent=intent,
    )


async def resume_turn(
    *,
    work_root: Path,
    turn_id: str,
    model: ModelConfig,
    budget: TurnBudget,
    on_event: HostEventCallback | None = None,
    recording: str | None = None,
) -> TurnResult:
    from app.writing_host.runner import resume_turn as impl

    return await impl(
        work_root=work_root,
        turn_id=turn_id,
        model=model,
        budget=budget,
        on_event=on_event,
        recording=recording,
    )


async def probe_model(model: ModelConfig) -> ProbeReport:
    from app.writing_host.runner import probe_model as impl

    return await impl(model)
