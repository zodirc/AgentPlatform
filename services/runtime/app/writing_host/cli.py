"""桌面命令行宿主。``python -m app.writing_host.cli --work <dir>``。"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from app.writing_host.protocol import (
    ModelConfig,
    TurnBudget,
    core_info,
    list_resumable,
    probe_model,
    resume_turn,
    start_turn,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="写作内核桌面宿主")
    parser.add_argument("--work", required=True, help="稿树目录")
    parser.add_argument("--message", default="", help="本回合用户消息")
    parser.add_argument("--resume", default="", help="要恢复的 turn id")
    parser.add_argument("--base-url", default=os.environ.get("WRITING_MODEL_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("WRITING_MODEL_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("WRITING_MODEL", "gpt-4o-mini"))
    parser.add_argument("--context-window", type=int, default=128000)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-input-tokens", type=int, default=0)
    parser.add_argument("--max-output-tokens", type=int, default=0)
    parser.add_argument("--plan-phase", default="")
    parser.add_argument("--recording", default="", help="回放用例名，不调用网络")
    parser.add_argument("--recordings-dir", default="")
    parser.add_argument("--probe", action="store_true")
    return parser


def _model(args: argparse.Namespace) -> ModelConfig:
    capabilities = {}
    if args.recordings_dir:
        capabilities["recordings_dir"] = args.recordings_dir
    return ModelConfig(
        base_url=args.base_url or "https://api.openai.com",
        api_key=args.api_key or "recording",
        model=args.model,
        context_window_tokens=args.context_window,
        capabilities=capabilities,
    )


def _budget(args: argparse.Namespace) -> TurnBudget:
    return TurnBudget(
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        max_steps=args.max_steps,
    )


def _print_event(event) -> None:
    print(f"{event.type}\t{event.payload}", flush=True)


async def _main(args: argparse.Namespace) -> int:
    info = core_info()
    print(
        f"core {info.core_version} protocol {info.protocol_version} schemas {info.schema_versions}",
        flush=True,
    )
    work = Path(args.work)
    if args.probe:
        report = await probe_model(_model(args))
        for check in report.checks:
            print(f"probe {check.name} ok={check.ok} {check.reason}", flush=True)
        return 0 if report.ok else 2
    if args.resume:
        result = await resume_turn(
            work_root=work,
            turn_id=args.resume,
            model=_model(args),
            budget=_budget(args),
            on_event=_print_event,
            recording=args.recording or None,
        )
    elif args.message or args.recording:
        result = await start_turn(
            work_root=work,
            message=args.message or "继续",
            model=_model(args),
            budget=_budget(args),
            plan_phase=args.plan_phase or None,
            on_event=_print_event,
            recording=args.recording or None,
        )
    else:
        for row in list_resumable(work):
            print(f"resumable {row.turn_id} step={row.step_index}", flush=True)
        return 0
    print(f"turn {result.turn_id} status={result.status} reason={result.termination_reason}", flush=True)
    if result.summary:
        print(result.summary, flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
