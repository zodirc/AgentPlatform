"""Turn 与 Run 持久化：创建、幂等、查询及启动失败标记。

负责 ``turns`` / ``runs`` / ``turn_views`` 初始行写入；pull 模式下按
``TURN_DISPATCH_WAKE`` 发 PG NOTIFY 与/或 COMMIT 后 Redis ``turn.dispatch``，
以及 Ops 模型密钥 escrow 入口。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from app.db.pool import get_pool


async def _find_existing_turn(
    pool, session_id: UUID, client_request_id: UUID
) -> tuple[dict, dict] | None:
    existing = await pool.fetchrow(
        """
        SELECT t.id, t.session_id, t.scenario_id, t.status, t.user_input, t.created_at,
               r.id AS run_id
        FROM turns t
        JOIN runs r ON r.turn_id = t.id
        WHERE t.session_id = $1 AND t.client_request_id = $2
        """,
        session_id,
        client_request_id,
    )
    if not existing:
        return None
    turn = {
        "id": existing["id"],
        "session_id": existing["session_id"],
        "scenario_id": existing["scenario_id"],
        "status": existing["status"],
        "user_input": existing["user_input"],
        "created_at": existing["created_at"],
    }
    return turn, {"id": existing["run_id"]}


async def find_existing_turn(
    session_id: UUID, client_request_id: UUID
) -> tuple[dict, dict] | None:
    """按 client_request_id 查找已存在的 turn+run（幂等创建）。

    参数:
        session_id: 会话 UUID。
        client_request_id: 客户端幂等键。

    返回:
        ``(turn_dict, run_dict)`` 或 None。
    """
    pool = await get_pool()
    return await _find_existing_turn(pool, session_id, client_request_id)


def _normalize_plan_phase(plan_phase: str | None) -> str | None:
    if plan_phase is None:
        return None
    phase = str(plan_phase).strip().lower()
    if phase in {"planning", "executing"}:
        return phase
    return None


def _normalize_model_mode(model_mode: str | None) -> str | None:
    if model_mode is None:
        return None
    mode = str(model_mode).strip().lower()
    if mode in {"stub", "live", "recorded"}:
        return mode
    return None


def resolve_pull_eligible(
    *,
    dispatch_notify: bool = True,
    pull_eligible: bool | None = None,
) -> bool:
    """解析 run 是否进入 pull 队列且可被 runtime claim。

    参数:
        dispatch_notify: False 时强制不可 pull（legacy 逃生口）。
        pull_eligible: 显式覆盖；None 时等同 dispatch_notify。

    返回:
        是否 ``pull_eligible``。

    说明:
        Ops 与 Web 应统一经 StartSpec + 密钥 escrow，共享同一 pull 队列。
    """
    eligible = dispatch_notify if pull_eligible is None else bool(pull_eligible)
    if not dispatch_notify:
        return False
    return eligible


async def create_turn(
    session_id: UUID,
    scenario_id: str,
    message: str,
    client_request_id: UUID | None,
    *,
    dispatch_notify: bool = True,
    pull_eligible: bool | None = None,
    plan_phase: str | None = None,
    ops_eval: bool = False,
    model_mode: str | None = None,
    model_override: dict[str, Any] | None = None,
) -> tuple[dict, dict, bool]:
    """原子创建 turn、run 与空 turn_view；支持幂等与 Ops 模型密钥。

    参数:
        session_id: 父会话。
        scenario_id: 场景 id。
        message: 用户输入。
        client_request_id: 可选幂等键；冲突时返回已有行且 created=False。
        dispatch_notify: 是否 pg_notify 唤醒 pull runtime。
        pull_eligible: 覆盖是否可 claim。
        plan_phase: planning/executing 或 None。
        ops_eval: Ops 评测 run 标记。
        model_mode: stub/live/recorded。
        model_override: 含 api_key 时 Fernet 写入 turn_model_secrets。

    返回:
        ``(turn, run, created)``；created False 表示幂等重放。

    说明:
        ON CONFLICT DO NOTHING 关闭 SELECT-INSERT 竞态；丢失竞态时再读 winner。
    """
    eligible = resolve_pull_eligible(
        dispatch_notify=dispatch_notify,
        pull_eligible=pull_eligible,
    )
    phase = _normalize_plan_phase(plan_phase)
    mode = _normalize_model_mode(model_mode)
    want_ops = bool(ops_eval)
    override = model_override if isinstance(model_override, dict) else None
    if override and override.get("api_key"):
        want_ops = True
        if mode is None:
            mode = "live"
    elif want_ops and mode is None:
        mode = "live"

    pool = await get_pool()

    if client_request_id is not None:
        found = await _find_existing_turn(pool, session_id, client_request_id)
        if found:
            turn, run = found
            return turn, run, False

    turn_id = uuid4()
    run_id = uuid4()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # ON CONFLICT closes the SELECT-then-INSERT race: a concurrent
            # duplicate returns no row here and we read the winner below.
            turn_row = await conn.fetchrow(
                """
                INSERT INTO turns (
                    id, session_id, scenario_id, status, user_input,
                    client_request_id, plan_phase
                )
                VALUES ($1, $2, $3, 'pending', $4, $5, $6)
                ON CONFLICT (session_id, client_request_id) DO NOTHING
                RETURNING id, session_id, scenario_id, status, user_input,
                          created_at, plan_phase
                """,
                turn_id,
                session_id,
                scenario_id,
                message,
                client_request_id,
                phase,
            )
            run_row = None
            if turn_row is not None:
                run_row = await conn.fetchrow(
                    """
                    INSERT INTO runs (
                        id, turn_id, status, pull_eligible, ops_eval, model_mode
                    )
                    VALUES ($1, $2, 'accepted', $3, $4, $5)
                    RETURNING id, turn_id, status, pull_eligible, ops_eval, model_mode
                    """,
                    run_id,
                    turn_id,
                    eligible,
                    want_ops,
                    mode,
                )
                await conn.execute(
                    """
                    INSERT INTO turn_views (
                        turn_id, session_id, scenario_id, status, user_input,
                        latest_output, tool_timeline, artifacts, last_event_sequence
                    )
                    VALUES ($1, $2, $3, 'pending', $4, NULL, '[]'::jsonb, '[]'::jsonb, 0)
                    """,
                    turn_id,
                    session_id,
                    scenario_id,
                    message,
                )
                if override and override.get("api_key"):
                    from app.services.resource.turn_model_secrets import (
                        store_turn_model_secret,
                    )

                    await store_turn_model_secret(
                        conn,
                        run_id=run_id,
                        turn_id=turn_id,
                        model_override=override,
                    )
                # O1 pull: PG doorbell (optional). Redis publish happens after COMMIT.
                if eligible and dispatch_notify:
                    from app.services.realtime.redis_bus import should_pg_notify_dispatch

                    if should_pg_notify_dispatch():
                        await conn.execute(
                            "SELECT pg_notify('turn_dispatch_channel', $1)",
                            str(run_id),
                        )

    if turn_row is None:
        # Lost the ON CONFLICT race — the winner has committed by the time
        # DO NOTHING returns, so its turn + run are visible now.
        assert client_request_id is not None
        found = await _find_existing_turn(pool, session_id, client_request_id)
        if found is None:
            raise RuntimeError(
                f"duplicate create_turn race for session {session_id} but "
                "winning turn not found"
            )
        turn, run = found
        return turn, run, False

    # After COMMIT: Redis wake (doorbell only; CAS claim stays in Postgres).
    if eligible and dispatch_notify and run_row is not None:
        from app.services.realtime.redis_bus import (
            publish_turn_dispatch,
            should_redis_publish_dispatch,
        )

        if should_redis_publish_dispatch():
            publish_turn_dispatch(run_row["id"])

    return dict(turn_row), dict(run_row), True


async def mark_turn_start_failed(turn_id: UUID, run_id: UUID, *, message: str) -> None:
    """push 模式 runtime start_turn 失败时，将 turn/run/view 标为 failed。

    参数:
        turn_id: Turn UUID。
        run_id: Run UUID。
        message: 错误摘要（写入 turn_views.latest_output，截断 512）。

    返回:
        None。
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE turns SET status = 'failed', updated_at = now() WHERE id = $1",
                turn_id,
            )
            await conn.execute(
                """
                UPDATE runs
                SET status = 'failed', termination_reason = 'start_failed', updated_at = now()
                WHERE id = $1
                """,
                run_id,
            )
            await conn.execute(
                """
                UPDATE turn_views
                SET status = 'failed', latest_output = $2, updated_at = now()
                WHERE turn_id = $1
                """,
                turn_id,
                message[:512],
            )


async def get_turn(turn_id: UUID) -> dict | None:
    """按 id 读取 turn 基础字段。

    参数:
        turn_id: Turn UUID。

    返回:
        行 dict 或 None。
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, session_id, scenario_id, status, user_input, created_at
        FROM turns WHERE id = $1
        """,
        turn_id,
    )
    return dict(row) if row else None


def _latest_plan_from_artifacts(artifacts: Any) -> dict | None:
    """Return the last plan artifact (projection keeps latest; tolerate legacy append)."""
    if not isinstance(artifacts, list):
        return None
    found: dict | None = None
    for art in artifacts:
        if isinstance(art, dict) and art.get("type") == "plan":
            found = art
    return found


def _latest_opening_ponds_from_artifacts(artifacts: Any) -> dict | None:
    if not isinstance(artifacts, list):
        return None
    found: dict | None = None
    for art in artifacts:
        if isinstance(art, dict) and art.get("type") == "opening_ponds":
            found = art
    return found


async def list_turns_for_session(session_id: UUID) -> list[dict]:
    """列出会话内 turn，LEFT JOIN turn_views 附带 latest_output 与 plan。

    参数:
        session_id: 会话 UUID。

    返回:
        dict 列表；``plan`` 取自 artifacts 中最后一个 type=plan 项。
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id, t.session_id, t.scenario_id, t.status, t.user_input, t.created_at,
               tv.latest_output, tv.artifacts
        FROM turns t
        LEFT JOIN turn_views tv ON tv.turn_id = t.id
        WHERE t.session_id = $1
        ORDER BY t.created_at ASC
        """,
        session_id,
    )
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        artifacts = item.pop("artifacts", None)
        # asyncpg may return JSON as str depending on codec — normalize lightly.
        if isinstance(artifacts, str):
            try:
                artifacts = json.loads(artifacts)
            except json.JSONDecodeError:
                artifacts = None
        item["plan"] = _latest_plan_from_artifacts(artifacts)
        item["opening_ponds"] = _latest_opening_ponds_from_artifacts(artifacts)
        out.append(item)
    return out


async def get_run_for_turn(turn_id: UUID) -> dict | None:
    """读取 turn 关联 run（控制命令、cancel 用）。

    参数:
        turn_id: Turn UUID。

    返回:
        run 行 dict 或 None。
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, turn_id, status, runner_id, cancel_requested_at, cancel_force
        FROM runs WHERE turn_id = $1
        """,
        turn_id,
    )
    return dict(row) if row else None


async def get_run(run_id: UUID) -> dict | None:
    """按 run_id 读取完整 run 行（含 termination、时间戳）。

    参数:
        run_id: Run UUID。

    返回:
        run 行 dict 或 None。
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, turn_id, status, termination_reason, runner_id,
               cancel_requested_at, cancel_force, created_at, updated_at
        FROM runs WHERE id = $1
        """,
        run_id,
    )
    return dict(row) if row else None
