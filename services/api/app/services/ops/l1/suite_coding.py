"""SWE-bench Official L1 coding suite."""
from __future__ import annotations
import asyncio, json, logging, os, time
from pathlib import Path
from typing import Any
from app.services.end_user.users import SYSTEM_USER_ID
from app.services.resource import sessions as session_svc
from .coding_harness import (
    coding_harness_fail_error,
    coding_harness_failed,
    maybe_run_coding_harness,
)
from .coding_metrics import finish_coding_metrics, resolve_workspace_index_wait
from .coding_thinking import (
    assemble_thinking_jsonl,
    coding_case_done_message,
    promote_thinking_sidecar,
)
from .common import (CancelCheck, L1Cancelled, L1TurnTracker, L1_CODING_TURN_TIMEOUT_S,
    L1_ROOT, PROTOCOL_L1, ProgressCb, _clamp_parallel, _coding_prompt, _emit,
    _emit_fail, _ensure_scripts_path, _exc_text, _l1_fingerprint, _reports)
from .turn_driver import (_create_l1_work, _enqueue_ephemeral_workspace_index,
    _pull_with_live_logs, _start_turn, _wait_turn_verbose)
logger = logging.getLogger(__name__)


async def run_coding_l1(
    *,
    tier: str = "n25",
    n_instances: int | None = None,
    instance_ids: list[str] | None = None,
    model: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
    scenario_id: str = "agent",
    max_parallel: int | None = None,
    checkout_repo: bool = True,
    run_harness: bool = False,
    workspace_index_wait_ready: bool | None = None,
    should_cancel: CancelCheck | None = None,
    turn_tracker: L1TurnTracker | None = None,
) -> dict[str, Any]:
    """SWE Lite via product Turns.

    A-3: default materializes repo at base_commit; patch prefers git diff;
    optional Docker harness after all Turns (``run_harness``).
    """
    if not checkout_repo:
        raise RuntimeError(
            "run_coding_l1 requires checkout_repo=true "
            "(structural navigation + git_diff need a base-commit worktree)"
        )
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        csi_probes_from_events,
        file_hit,
        patch_apply_check,
        patch_from_baseline_diff,
        patch_from_edit_events,
        patch_from_events,
        patch_from_git_diff,
        patch_from_work_root,
        patch_hunks_incomplete,
        ran_tests_from_events,
        read_file_stats_from_events,
        step_count_from_events,
        terminal_state_from_events,
        turn_failure_message_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.l2_probes import classify_bucket
    from official_bench.pull import pull_swebench
    from official_bench.repo_materialize import (
        cleanup_worktree,
        materialize_instance_repo,
        prewarm_repo_mirrors,
    )
    from official_bench.run_session import RunSession
    from official_bench.swe_run import (
        _ensure_slice_files,
        _load_instances,
        resolve_coding_selection,
        write_predictions,
    )

    cfg = load_suites()
    coding_cfg = (cfg.get("suites") or {}).get("coding") or {}
    # E1 dual-track: suites.coding.workspace_index on|off (§7 eval-ephemeral).
    workspace_index_on = bool(coding_cfg.get("workspace_index"))
    workspace_index_wait_ready, workspace_index_wait_timeout_s = (
        resolve_workspace_index_wait(coding_cfg, workspace_index_wait_ready)
    )
    root = await _pull_with_live_logs(
        "SWE-bench Lite",
        lambda: pull_swebench(cfg, force=False),
        on_progress=on_progress,
    )
    instances_path = root / "instances.jsonl"
    _ensure_slice_files(instances_path)
    selected_tier, selected_n, ids, fingerprint = resolve_coding_selection(
        tier=tier, n_instances=n_instances, instance_ids=instance_ids
    )
    rows = _load_instances(instances_path, allowed_ids=set(ids))
    by_id = {str(r.get("instance_id")): r for r in rows}
    ordered = [by_id[i] for i in ids if i in by_id]
    if instance_ids and not ordered:
        raise ValueError(
            "retry instance_ids matched no SWE Lite rows: "
            + ", ".join(str(x) for x in ids[:8])
        )
    retry_subset = bool(instance_ids)

    session = RunSession(
        suite="coding",
        title=f"SWE-bench Lite · L1 agent-path · {selected_tier}",
    )
    session.extra = {
        "protocol_version": PROTOCOL_L1,
        "eval_path": "agent",
        "coding_tier": selected_tier,
        "n_instances": selected_n,
        "instance_fingerprint": fingerprint,
        "infer_mode": "platform_turn",
        "harness": bool(run_harness),
        "checkout_repo": bool(checkout_repo),
        "workspace_index": bool(workspace_index_on),
        "workspace_index_wait_ready": bool(
            workspace_index_on and workspace_index_wait_ready
        ),
        "workspace_index_wait_timeout_s": float(workspace_index_wait_timeout_s),
        "sample_tier": (
            "anchor"
            if (not retry_subset)
            and selected_tier in {"n25", "full300"}
            and run_harness
            else "smoke"
        ),
        "retry_instance_ids": list(ids) if retry_subset else None,
        # Structural lane is fused into agent; archive prewarm / deny-net only.
        "structural_fused": True,
        "structural_prewarm_env": os.environ.get("STRUCTURAL_PREWARM", ""),
        "ops_eval_deny_network_env": os.environ.get(
            "OPS_EVAL_DENY_NETWORK",
            "1" if os.environ.get("OFFICIAL_SWE_NETWORK", "").strip().lower() == "deny" else "",
        ),
        "official_swe_network": os.environ.get("OFFICIAL_SWE_NETWORK", ""),
        **_l1_fingerprint(model),
    }
    patches: dict[str, str] = {}
    patch_sources: dict[str, str] = {}
    run_root = L1_ROOT / session.run_id / "coding"
    nonempty = 0
    conc = _clamp_parallel(max_parallel)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] coding plan n={len(ordered)} tier={selected_tier} "
            f"parallel={conc} checkout={checkout_repo} harness={run_harness} "
            + (
                f"retry_ids={','.join(ids[:8])} "
                if retry_subset
                else ""
            )
            + f"workspace_index={int(workspace_index_on)} "
            + f"wait_ready={int(workspace_index_on and workspace_index_wait_ready)}"
        ),
    )
    # Suite-level mirror sync (bypass): fetch once per unique repo before Turns so
    # per-instance materialize is local clone+checkout, not cold network.
    repos = [str(inst.get("repo") or "") for inst in ordered]
    await _emit(
        on_progress,
        "log",
        message=f"[L1] mirror prewarm starting n_repos={len({r for r in repos if r})}",
    )
    prewarm_meta = await asyncio.to_thread(prewarm_repo_mirrors, repos)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] mirror prewarm done ok={len(prewarm_meta.get('ok') or [])} "
            f"failed={len(prewarm_meta.get('failed') or {})}"
        ),
    )
    if prewarm_meta.get("failed"):
        for repo, err in list((prewarm_meta.get("failed") or {}).items())[:5]:
            await _emit(
                on_progress,
                "log",
                message=f"[L1] mirror prewarm fail {repo}: {err}",
            )
    session.extra["mirror_prewarm"] = {
        "n_repos": prewarm_meta.get("n_repos"),
        "n_ok": len(prewarm_meta.get("ok") or []),
        "n_failed": len(prewarm_meta.get("failed") or {}),
        "failed_repos": list((prewarm_meta.get("failed") or {}).keys())[:12],
    }
    try:
        sem = asyncio.Semaphore(conc)
        case_lock = asyncio.Lock()
        done_count = 0

        async def _one_inst(inst: dict[str, Any]) -> None:
            nonlocal nonempty, done_count
            iid = str(inst.get("instance_id"))
            async with sem:
                if should_cancel is not None and should_cancel():
                    raise L1Cancelled("L1 cancelled")
                # INFRA: entire case body isolated — StartTurn / transport
                # failures must not abort asyncio.gather / suite.
                work = None
                turn: dict[str, Any] | None = None
                run_row: dict[str, Any] | None = None
                has_repo = False
                mirror_hit = False
                patch = ""
                patch_source = "none"
                err: str | None = None
                l2: dict[str, Any] = {
                    "case_id": iid,
                    "arm": "free",
                    "patch_source": "none",
                    "terminal_state": "failed",
                    "has_repo": False,
                    "mirror_hit": False,
                    "bucket": "infra_error",
                }
                t0 = time.monotonic()
                await _emit(
                    on_progress,
                    "log",
                    message=f"[L1] coding case start {iid}",
                )
                try:
                    work = await _create_l1_work(
                        str(run_root / iid.replace("/", "_")),
                        name=f"l1-swe-{iid}"[:120],
                    )
                    # checkout_repo is required (enforced above); materialize must succeed
                    # before StartTurn — no silent problem.md-only fallback.
                    try:
                        meta = await asyncio.to_thread(
                            materialize_instance_repo, inst, work.work_root
                        )
                        has_repo = True
                        mirror_hit = bool(meta.get("mirror_hit"))
                        await _emit(
                            on_progress,
                            "log",
                            message=(
                                f"[L1] checkout {iid} mirror_hit={mirror_hit} "
                                f"repo={meta.get('repo')} commit={meta.get('base_commit')}"
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001
                        err = f"checkout_failed: {exc}"
                        await _emit(
                            on_progress,
                            "log",
                            message=f"[L1] checkout failed {iid}: {exc}",
                        )
                        l2 = {
                            "case_id": iid,
                            "arm": "free",
                            "patch_source": "none",
                            "checkout_failed": True,
                            "has_repo": False,
                            "mirror_hit": False,
                            "terminal_state": "failed",
                            "bucket": "checkout_failed",
                        }
                        async with case_lock:
                            patches[iid] = ""
                            patch_sources[iid] = "none"
                            session.add_case(
                                iid,
                                status="fail",
                                error=err,
                                metrics={
                                    "nonempty": 0.0,
                                    "steps": 0.0,
                                    "elapsed_s": float(
                                        round(time.monotonic() - t0, 1)
                                    ),
                                },
                                extra={
                                    "bucket": "checkout_failed",
                                    "l2": l2,
                                    "has_repo": False,
                                    "mirror_hit": False,
                                },
                            )
                            done_count += 1
                            await _emit(
                                on_progress,
                                "log",
                                message=coding_case_done_message(
                                    done=done_count,
                                    total=len(ordered),
                                    iid=iid,
                                    status="fail",
                                    bucket="checkout_failed",
                                    steps=0,
                                    elapsed_s=time.monotonic() - t0,
                                ),
                            )
                        await _emit_fail(on_progress, iid, error=err)
                        return

                    sess = await session_svc.create_session(
                        scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
                    )
                    hint = _coding_prompt(inst, has_repo=True)
                    tenant = {
                        "work_id": str(work.id),
                        "work_root": str(work.work_root),
                        "owner_user_id": SYSTEM_USER_ID,
                    }
                    # Default (wait_ready=false): StartTurn first (R1) — index
                    # builds during the Turn. Optional wait_ready: enqueue +
                    # await ready|stale before StartTurn (product-parity Locate).
                    if workspace_index_on and workspace_index_wait_ready:
                        try:
                            await _enqueue_ephemeral_workspace_index(
                                iid=iid,
                                tenant=tenant,
                                on_progress=on_progress,
                                should_cancel=should_cancel,
                                wait_ready=True,
                                wait_timeout_s=workspace_index_wait_timeout_s,
                            )
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "workspace_index wait_ready failed for %s",
                                iid,
                                exc_info=True,
                            )
                    turn, run_row = await _start_turn(
                        session_id=sess["id"],
                        scenario_id=scenario_id,
                        message=hint,
                        work=work,
                        model_override=model,
                    )
                    if workspace_index_on and not workspace_index_wait_ready:
                        try:
                            await _enqueue_ephemeral_workspace_index(
                                iid=iid,
                                tenant=tenant,
                                on_progress=on_progress,
                                should_cancel=should_cancel,
                                wait_ready=False,
                            )
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "workspace_index enqueue failed for %s",
                                iid,
                                exc_info=True,
                            )

                    patch_source = "none"
                    events: list[dict[str, Any]] = []
                    try:
                        events = await _wait_turn_verbose(
                            turn["id"],
                            on_progress=on_progress,
                            label=f"swe.{iid}",
                            timeout=L1_CODING_TURN_TIMEOUT_S,
                            should_cancel=should_cancel,
                            run_id=run_row["id"],
                            turn_tracker=turn_tracker,
                        )
                        patch = ""
                        if has_repo:
                            patch = patch_from_git_diff(work.work_root)
                            if patch.strip():
                                patch_source = "git_diff"
                        # Repair path: empty OR truncated hunks (strip bug / corrupt).
                        # First rebuild a git-exact per-file diff vs the checkout
                        # baseline (real hunk offsets — applies onto base commit);
                        # only then fall back to edit_file span synthesis.
                        if (not str(patch or "").strip()) or patch_hunks_incomplete(
                            patch
                        ):
                            repaired = (
                                patch_from_baseline_diff(work.work_root, events)
                                if has_repo
                                else ""
                            )
                            if repaired.strip() and not patch_hunks_incomplete(
                                repaired
                            ):
                                patch = repaired
                                patch_source = "baseline_diff"
                            else:
                                repaired = patch_from_edit_events(events)
                                if repaired.strip() and not patch_hunks_incomplete(
                                    repaired
                                ):
                                    patch = repaired
                                    patch_source = "edit_events"
                        if not str(patch or "").strip():
                            patch = patch_from_events(events)
                            if patch.strip():
                                patch_source = (
                                    "propose" if "@@" in patch else "fenced"
                                )
                        if not str(patch or "").strip():
                            patch = patch_from_work_root(work.work_root)
                            if patch.strip():
                                patch_source = "write"
                        incomplete = (
                            patch_hunks_incomplete(patch) if patch.strip() else False
                        )
                        applies = (
                            patch_apply_check(work.work_root, patch)
                            if has_repo and patch.strip()
                            else None
                        )
                        reject_reason = None
                        if patch.strip() and incomplete:
                            reject_reason = "hunks_incomplete"
                        elif patch.strip() and applies is False:
                            reject_reason = "apply_check_failed"
                        accepted_patch = "" if reject_reason else patch
                        read_stats = read_file_stats_from_events(events)
                        csi = csi_probes_from_events(events)
                        # §7.7.1 D1 file_hit: gold patch only post-hoc (§8.4 — never in prompt).
                        gold_patch = str(inst.get("patch") or "")
                        hit = file_hit(model_patch=accepted_patch or patch, gold_patch=gold_patch)
                        l2 = {
                            "case_id": iid,
                            "turn_id": str(turn["id"]),
                            "arm": "free",
                            "patch_source": patch_source,
                            "patch_applies": applies,
                            "patch_incomplete": incomplete,
                            "patch_rejected": reject_reason,
                            "patch_chars": len(patch) if patch else 0,
                            "ran_tests": ran_tests_from_events(events),
                            "file_hit": hit,
                            **read_stats,
                            **csi,
                            "steps": step_count_from_events(events),
                            "terminal_state": terminal_state_from_events(events),
                            "mirror_hit": mirror_hit,
                            "has_repo": has_repo,
                        }
                        fail_msg = turn_failure_message_from_events(events)
                        if fail_msg:
                            l2["failure_message"] = fail_msg[:500]
                        l2["bucket"] = classify_bucket("coding", l2)
                        # Infra turn death (e.g. start_timeout) must not look like
                        # "agent produced no patch" — surface the real reason.
                        term = str(l2.get("terminal_state") or "")
                        if term in {"failed", "step_timeout", "stall"} and not patch.strip():
                            err = fail_msg or term
                        else:
                            err = None
                        patch = accepted_patch
                    except L1Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        raw = patch_from_work_root(work.work_root) if has_repo else ""
                        if not raw:
                            raw = (
                                patch_from_git_diff(work.work_root) if has_repo else ""
                            )
                        patch_source = "git_diff" if raw.strip() else "none"
                        if (not raw.strip() or patch_hunks_incomplete(raw)) and has_repo:
                            repaired = patch_from_baseline_diff(work.work_root, events)
                            if repaired.strip() and not patch_hunks_incomplete(repaired):
                                raw = repaired
                                patch_source = "baseline_diff"
                        applies = (
                            patch_apply_check(work.work_root, raw)
                            if has_repo and raw.strip()
                            else None
                        )
                        reject_reason = None
                        if raw.strip() and patch_hunks_incomplete(raw):
                            reject_reason = "hunks_incomplete"
                        elif raw.strip() and applies is False:
                            reject_reason = "apply_check_failed"
                        patch = "" if reject_reason else raw
                        err = _exc_text(exc)
                        csi = csi_probes_from_events(events)
                        gold_patch = str(inst.get("patch") or "")
                        hit = file_hit(model_patch=patch, gold_patch=gold_patch)
                        l2 = {
                            "case_id": iid,
                            "turn_id": str(turn["id"]),
                            "patch_source": patch_source,
                            "patch_applies": applies,
                            "patch_rejected": reject_reason,
                            "terminal_state": "failed",
                            "has_repo": has_repo,
                            "mirror_hit": mirror_hit,
                            "file_hit": hit,
                            **csi,
                        }
                        l2["bucket"] = classify_bucket("coding", l2)
                except L1Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 — case isolation, no re-raise
                    err = _exc_text(exc)
                    logger.warning(
                        "L1 coding case failed iid=%s err=%s", iid, err, exc_info=True
                    )
                    l2 = {
                        "case_id": iid,
                        "turn_id": str(turn["id"]) if turn else "",
                        "arm": "free",
                        "patch_source": patch_source,
                        "terminal_state": "failed",
                        "has_repo": has_repo,
                        "mirror_hit": mirror_hit,
                        "failure_message": err[:500],
                        "bucket": "infra_error",
                    }
                    patch = ""
                    patch_source = "none"

                # Keep eval thinking before wiping the worktree (not in turn_events).
                if work is not None and turn is not None:
                    try:
                        dest = promote_thinking_sidecar(
                            session_dir=Path(session.dir),
                            iid=iid,
                            turn_id=turn["id"],
                            work_root=work.work_root,
                        )
                        if dest is not None:
                            await _emit(
                                on_progress,
                                "log",
                                message=(
                                    f"[L1] thinking sidecar {iid} "
                                    f"bytes={dest.stat().st_size} (not in DB)"
                                ),
                            )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "thinking sidecar promote failed for %s", iid, exc_info=True
                        )

                # Disk hygiene: drop heavy tree after extract (keep mirror).
                if work is not None and has_repo:
                    try:
                        await asyncio.to_thread(
                            cleanup_worktree, work.work_root, keep_problem=True
                        )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "cleanup_worktree failed for %s", iid, exc_info=True
                        )
                    if workspace_index_on:
                        # Never block the suite on purge (runtime may be busy indexing).
                        async def _purge_ast(wid: str = str(work.id), wr: str = str(work.work_root)) -> None:
                            try:
                                from app.services.admin import workspace as workspace_svc

                                await workspace_svc.ast_index_purge(
                                    tenant={
                                        "work_id": wid,
                                        "work_root": wr,
                                        "owner_user_id": SYSTEM_USER_ID,
                                    }
                                )
                            except Exception:  # noqa: BLE001
                                logger.warning(
                                    "workspace_index purge failed for %s",
                                    iid,
                                    exc_info=True,
                                )

                        asyncio.create_task(_purge_ast())

                async with case_lock:
                    patches[iid] = patch
                    patch_sources[iid] = patch_source
                    if patch.strip():
                        nonempty += 1
                    case_status = "pass" if patch.strip() else "fail"
                    elapsed_s = round(time.monotonic() - t0, 1)
                    steps_n = int(l2.get("steps") or 0)
                    l2["elapsed_s"] = elapsed_s
                    session.add_case(
                        iid,
                        status=case_status,
                        error=err,
                        metrics={
                            "nonempty": 1.0 if patch.strip() else 0.0,
                            "steps": float(steps_n),
                            "elapsed_s": float(elapsed_s),
                        },
                        extra={
                            "turn_id": str(turn["id"]) if turn else "",
                            "patch_source": patch_source,
                            "bucket": l2.get("bucket"),
                            "l2": l2,
                            "has_repo": has_repo,
                            "mirror_hit": mirror_hit,
                        },
                    )
                    done_count += 1
                    await _emit(
                        on_progress,
                        "log",
                        message=coding_case_done_message(
                            done=done_count,
                            total=len(ordered),
                            iid=iid,
                            status=case_status,
                            bucket=str(l2.get("bucket") or "") or None,
                            patch_source=patch_source,
                            steps=steps_n,
                            elapsed_s=elapsed_s,
                            error=str(err) if err else None,
                        ),
                    )
                if case_status == "fail" or err:
                    await _emit_fail(
                        on_progress,
                        iid,
                        error=str(
                            err
                            or l2.get("failure_message")
                            or l2.get("bucket")
                            or "no_patch"
                        ),
                    )

        results = await asyncio.gather(
            *[_one_inst(inst) for inst in ordered],
            return_exceptions=True,
        )
        if any(isinstance(r, L1Cancelled) for r in results) or (
            should_cancel is not None and should_cancel()
        ):
            if turn_tracker is not None:
                await turn_tracker.cancel_all(reason="ops_eval_stopped")
            raise L1Cancelled("L1 cancelled")

        pred_path = Path(session.dir) / "predictions.jsonl"
        write_predictions(
            ordered,
            model_name="agentplatform-agent",
            patches=patches,
            out_path=pred_path,
        )
        metrics = finish_coding_metrics(
            session=session,
            selected_n=selected_n,
            nonempty=nonempty,
            prewarm_meta=prewarm_meta,
        )
        try:
            assembled = assemble_thinking_jsonl(Path(session.dir))
            if assembled is not None:
                await _emit(
                    on_progress,
                    "log",
                    message=(
                        f"[L1] thinking.jsonl bytes={assembled.stat().st_size} "
                        "(download from artifacts)"
                    ),
                )
        except OSError:
            logger.warning("failed to assemble thinking.jsonl", exc_info=True)
        harness_result = await maybe_run_coding_harness(
            run_harness=run_harness,
            pred_path=pred_path,
            ordered=ordered,
            session=session,
            metrics=metrics,
            on_progress=on_progress,
        )

        session.metrics = metrics
        harness_failed = coding_harness_failed(run_harness, metrics)
        result = {
            "suite": "swebench.lite",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "coding_tier": selected_tier,
            "n_instances": selected_n,
            "instance_fingerprint": fingerprint,
            "infer_mode": "platform_turn",
            "harness": bool(run_harness),
            "harness_failed": harness_failed,
            "checkout_repo": bool(checkout_repo),
            "sample_tier": session.extra.get("sample_tier"),
            "metrics": metrics,
            "predictions": str(pred_path),
            "patch_sources": patch_sources,
            "resolved_ids": list(harness_result.get("resolved_ids") or []),
            "unresolved_ids": list(harness_result.get("unresolved_ids") or []),
            "error_ids": list(harness_result.get("error_ids") or []),
        }
        if harness_failed:
            err = coding_harness_fail_error(metrics)
            await _emit_fail(on_progress, "suite=coding", error=err)
            manifest = session.finish(
                status="failed", error=err, metrics=metrics, result=result
            )
        else:
            manifest = session.finish(status="completed", metrics=metrics, result=result)
        (_reports() / "latest_coding.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await _emit(on_progress, "log", message=f"[L1] coding infer done run_id={session.run_id}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        logger.exception("L1 coding failed")
        await _emit_fail(on_progress, "suite=coding", error=_exc_text(exc))
        session.finish(status="failed", error=_exc_text(exc))
        raise
