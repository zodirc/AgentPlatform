"""Optional SWE-bench Docker harness after L1 infer."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .common import ProgressCb, _emit, _emit_fail, _exc_text

logger = logging.getLogger(__name__)


async def maybe_run_coding_harness(
    *,
    run_harness: bool,
    pred_path: Path,
    ordered: list[Any],
    session: Any,
    metrics: dict[str, Any],
    on_progress: ProgressCb | None,
) -> dict[str, Any]:
    """Run Docker harness if requested. Mutates ``metrics`` and ``session.cases``."""
    if not run_harness:
        metrics["note"] = (
            "patch_rate is auxiliary; official resolve requires harness "
            "(Ops coding always enables harness)"
        )
        return {}

    from official_bench.l2_probes import classify_bucket
    from official_bench.swe_run import run_swe_eval

    pred_n = 0
    try:
        with pred_path.open(encoding="utf-8") as pf:
            pred_n = sum(1 for line in pf if line.strip())
    except OSError:
        pred_n = len(ordered)
    await _emit(
        on_progress,
        "log",
        message=f"[L1] coding harness start n={pred_n}",
    )
    await _emit(on_progress, "log", message="[L1] coding harness resolve…")
    harness_result: dict[str, Any] = {}
    try:
        from official_bench.swe_run import (
            format_l1_harness_event,
            parse_harness_stdout_line,
        )

        loop = asyncio.get_running_loop()
        last_emit_key: tuple[Any, ...] | None = None

        def _harness_sink(raw: str) -> None:
            nonlocal last_emit_key
            ev = parse_harness_stdout_line(raw)
            if ev is None:
                return
            if ev.get("kind") == "log":
                return
            if ev.get("kind") == "progress":
                key = (
                    "progress",
                    ev.get("done"),
                    ev.get("total"),
                    ev.get("resolved"),
                    ev.get("unresolved"),
                    ev.get("error"),
                )
            else:
                key = ("stage", ev.get("stage"), ev.get("n"), ev.get("detail"))
            if key == last_emit_key:
                return
            last_emit_key = key
            msg = format_l1_harness_event(ev)
            if not msg:
                return

            def _schedule() -> None:
                asyncio.create_task(_emit(on_progress, "log", message=msg))

            try:
                loop.call_soon_threadsafe(_schedule)
            except RuntimeError:
                pass

        harness = await asyncio.to_thread(
            run_swe_eval,
            predictions=pred_path,
            on_line=_harness_sink,
        )
        h_metrics = harness.get("metrics") or {}
        metrics.update(h_metrics)
        if "resolve_rate" not in metrics and isinstance(
            h_metrics.get("resolve_rate"), (int, float)
        ):
            metrics["resolve_rate"] = float(h_metrics["resolve_rate"])
        harness_result = (
            harness.get("result") if isinstance(harness.get("result"), dict) else {}
        )
        resolved_ids = {
            str(x)
            for x in (harness_result.get("resolved_ids") or [])
            if x is not None
        }
        unresolved_ids = [
            str(x)
            for x in (harness_result.get("unresolved_ids") or [])
            if x is not None
        ]
        error_ids = [
            str(x)
            for x in (harness_result.get("error_ids") or [])
            if x is not None
        ]
        has_resolve_list = isinstance(harness_result.get("resolved_ids"), list)
        for case in session.cases:
            iid = str(case.get("case_id") or "")
            if not iid or iid.startswith("swebench.lite"):
                continue
            l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
            if has_resolve_list:
                l2["resolved"] = iid in resolved_ids
            l2["bucket"] = classify_bucket("coding", l2)
            case["l2"] = l2
            case["bucket"] = l2.get("bucket")
            m = dict(case.get("metrics") or {})
            if has_resolve_list:
                m["resolved"] = 1.0 if l2.get("resolved") else 0.0
            case["metrics"] = m
        if has_resolve_list:
            metrics["n_resolved"] = float(len(resolved_ids))
        rate = metrics.get("resolve_rate")
        rate_s = (
            f"{float(rate):.4f}"
            if isinstance(rate, (int, float))
            else "?"
        )
        denom = pred_n or max(
            len(resolved_ids) + len(unresolved_ids) + len(error_ids), 1
        )
        await _emit(
            on_progress,
            "log",
            message=(
                f"[L1] coding harness done resolved={len(resolved_ids)}/{denom} "
                f"unresolved={len(unresolved_ids)} error={len(error_ids)} "
                f"rate={rate_s}"
            ),
        )
        for hid in sorted(resolved_ids):
            await _emit(
                on_progress,
                "log",
                message=f"[L1] coding harness case {hid} outcome=resolved",
            )
        for hid in unresolved_ids:
            await _emit(
                on_progress,
                "log",
                message=f"[L1] coding harness case {hid} outcome=unresolved",
            )
        for hid in error_ids:
            await _emit(
                on_progress,
                "log",
                message=f"[L1] coding harness case {hid} outcome=error",
            )
    except Exception as exc:  # noqa: BLE001
        metrics["harness_error"] = str(exc)
        metrics["note"] = f"harness failed: {exc}"
        await _emit(
            on_progress,
            "log",
            message=f"[L1] coding harness done status=failed error={_exc_text(exc)[:200]}",
        )
        await _emit_fail(on_progress, "suite=coding.harness", error=str(exc))
    return harness_result
