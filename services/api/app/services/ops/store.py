"""Ops 评测 run 的 Postgres 持久化（docs/29 历史记录）。

English: Persist Ops Eval runs to Postgres (docs/29 history).

职责：将 Golden/Official 评测 run 的 status、cases、logs、model_meta 写入
``ops_eval_runs``，供 Ops Console 列表/详情/清理 API 读取。不写 runtime 状态。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.db.pool import get_pool


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def summary_from_cases(cases: list[dict[str, Any]]) -> dict[str, int]:
    """从 case 行列表汇总 pass/fail/skipped/pending 计数。

    参数:
        cases: 每条含 ``status`` 字段的 case dict（pass/fail/skipped/pending/running）。

    返回:
        含 ``total``、``pass``、``fail``、``skipped``、``pending`` 的计数 dict；
        ``running`` 计入 ``pending``。
    """
    return {
        "total": len(cases),
        "pass": sum(1 for c in cases if c.get("status") == "pass"),
        "fail": sum(1 for c in cases if c.get("status") == "fail"),
        "skipped": sum(1 for c in cases if c.get("status") == "skipped"),
        "pending": sum(1 for c in cases if c.get("status") in {"pending", "running"}),
    }


def model_meta_safe(model: dict[str, Any] | None) -> dict[str, Any]:
    """提取可持久化的模型元数据， deliberately 省略 ``api_key``。

    参数:
        model: 评测请求里的 model 配置 dict，或 ``None``。

    返回:
        仅含 ``provider``、``model_name``、``base_url`` 的子集；空输入返回 ``{}``。
    """
    if not model:
        return {}
    return {
        "provider": model.get("provider"),
        "model_name": model.get("model_name"),
        "base_url": model.get("base_url"),
        # intentionally omit api_key
    }


async def upsert_run(payload: dict[str, Any]) -> None:
    """插入或更新一条 ops_eval_runs 记录（SSE 进度与终态均走此路径）。

    参数:
        payload: 含 ``id``、``status``、``mode``、可选 ``cases``/``logs``/``summary``/
            ``model_meta``/``error``/时间戳等字段的 run 快照。

    返回:
        无；冲突时按 ``id`` 全量覆盖可变列。
    """
    pool = await get_pool()
    run_id = UUID(str(payload["id"]))
    cases = list(payload.get("cases") or [])
    summary = payload.get("summary") or summary_from_cases(cases)
    logs = list(payload.get("logs") or [])
    model_meta = payload.get("model_meta") or {}
    created_at = _parse_ts(payload.get("created_at")) or datetime.now(timezone.utc)
    finished_at = _parse_ts(payload.get("finished_at"))

    await pool.execute(
        """
        INSERT INTO ops_eval_runs (
            id, status, mode, restart_runtime, created_at, finished_at, error,
            model_meta, summary, cases, logs, updated_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, now()
        )
        ON CONFLICT (id) DO UPDATE SET
            status = EXCLUDED.status,
            mode = EXCLUDED.mode,
            restart_runtime = EXCLUDED.restart_runtime,
            finished_at = EXCLUDED.finished_at,
            error = EXCLUDED.error,
            model_meta = EXCLUDED.model_meta,
            summary = EXCLUDED.summary,
            cases = EXCLUDED.cases,
            logs = EXCLUDED.logs,
            updated_at = now()
        """,
        run_id,
        str(payload.get("status") or "queued"),
        str(payload.get("mode") or "stub"),
        bool(payload.get("restart_runtime")),
        created_at,
        finished_at,
        payload.get("error"),
        json.dumps(model_meta),
        json.dumps(summary),
        json.dumps(cases),
        json.dumps(logs),
    )


async def load_run(run_id: str) -> dict[str, Any] | None:
    """按 UUID 加载完整 run（含 cases 与 logs）。

    参数:
        run_id: run 的 UUID 字符串。

    返回:
        与 ``_row_to_dict(include_logs=True)`` 同形的 dict；非法 UUID 或不存在时 ``None``。
    """
    pool = await get_pool()
    try:
        uid = UUID(run_id)
    except ValueError:
        return None
    row = await pool.fetchrow(
        """
        SELECT id, status, mode, restart_runtime, created_at, finished_at, error,
               model_meta, summary, cases, logs
        FROM ops_eval_runs
        WHERE id = $1
        """,
        uid,
    )
    if row is None:
        return None
    return _row_to_dict(row, include_logs=True)


async def list_runs(
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    mode: str | None = None,
    suite: str | None = None,
    q: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """分页列出评测 run（列表项不含 logs，仅 summary 级字段）。

    参数:
        limit: 每页条数，钳制在 1–100。
        offset: 偏移。
        status: 可选，按 run status 过滤。
        mode: 可选，按 stub/live 等 mode 过滤。
        suite: 可选，按 ``model_meta.suite`` 过滤；缺 suite 的 legacy 行视为 ``golden``。
        q: 可选，对 run id 或 error 文本做 ILIKE 模糊搜索。

    返回:
        ``(rows, total)``：rows 为摘要 dict 列表，total 为匹配总数（分页前）。
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    clauses: list[str] = []
    args: list[Any] = []

    def _add(clause: str, value: Any) -> None:
        args.append(value)
        clauses.append(clause.replace("?", f"${len(args)}"))

    if status:
        _add("status = ?", status.strip().lower())
    if mode:
        _add("mode = ?", mode.strip().lower())
    if suite:
        suite_norm = suite.strip().lower()
        # suite lives in model_meta JSON; legacy rows without suite are golden
        args.append(suite_norm)
        n = len(args)
        clauses.append(
            f"(COALESCE(NULLIF(TRIM(model_meta->>'suite'), ''), 'golden') = ${n})"
        )
    if q:
        needle = q.strip()
        if needle:
            args.append(f"%{needle}%")
            n = len(args)
            clauses.append(
                f"(id::text ILIKE ${n} OR COALESCE(error, '') ILIKE ${n})"
            )

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    pool = await get_pool()
    total = int(await pool.fetchval(f"SELECT COUNT(*) FROM ops_eval_runs {where}", *args) or 0)
    args.extend([limit, offset])
    lim_i, off_i = len(args) - 1, len(args)
    rows = await pool.fetch(
        f"""
        SELECT id, status, mode, restart_runtime, created_at, finished_at, error,
               model_meta, summary, cases, logs
        FROM ops_eval_runs
        {where}
        ORDER BY created_at DESC
        LIMIT ${lim_i} OFFSET ${off_i}
        """,
        *args,
    )
    return [_row_to_summary(row) for row in rows], total


async def delete_runs(*, suite: str | None = None) -> int:
    """删除 ops_eval_runs 行；指定 suite 时仅删该套件的历史。

    参数:
        suite: 可选套件名（``model_meta.suite``）；``None`` 时清空全表。

    返回:
        实际删除行数（解析 asyncpg ``DELETE n`` 结果）。
    """
    pool = await get_pool()
    if suite:
        result = await pool.execute(
            """
            DELETE FROM ops_eval_runs
            WHERE COALESCE(model_meta->>'suite', 'golden') = $1
            """,
            suite.strip().lower(),
        )
    else:
        result = await pool.execute("DELETE FROM ops_eval_runs")
    # asyncpg returns like 'DELETE 3'
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def delete_runs_by_ids(
    ids: list[str],
    *,
    suite: str | None = None,
) -> int:
    """按 run id 列表批量删除；可选 suite 约束防误删其它套件。

    参数:
        ids: UUID 字符串列表；空白项忽略。
        suite: 可选，仅删除 ``model_meta.suite`` 匹配的行。

    返回:
        删除行数；空 id 列表返回 0。
    """
    cleaned = [str(i).strip() for i in ids if str(i).strip()]
    if not cleaned:
        return 0
    pool = await get_pool()
    if suite:
        result = await pool.execute(
            """
            DELETE FROM ops_eval_runs
            WHERE id = ANY($1::uuid[])
              AND COALESCE(model_meta->>'suite', 'golden') = $2
            """,
            cleaned,
            suite.strip().lower(),
        )
    else:
        result = await pool.execute(
            "DELETE FROM ops_eval_runs WHERE id = ANY($1::uuid[])",
            cleaned,
        )
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def delete_runs_before(
    before_iso: str,
    *,
    suite: str | None = None,
) -> int:
    """删除 ``created_at`` 严格早于给定时间戳的 run。

    参数:
        before_iso: ISO8601 时间字符串（作 timestamptz 比较）。
        suite: 可选套件过滤，语义同 ``delete_runs``。

    返回:
        删除行数。
    """
    pool = await get_pool()
    if suite:
        result = await pool.execute(
            """
            DELETE FROM ops_eval_runs
            WHERE created_at < $1::timestamptz
              AND COALESCE(model_meta->>'suite', 'golden') = $2
            """,
            before_iso,
            suite.strip().lower(),
        )
    else:
        result = await pool.execute(
            "DELETE FROM ops_eval_runs WHERE created_at < $1::timestamptz",
            before_iso,
        )
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


def _as_obj(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _row_to_dict(row, *, include_logs: bool) -> dict[str, Any]:
    cases = _as_obj(row["cases"]) or []
    summary = _as_obj(row["summary"]) or summary_from_cases(cases)
    model_meta = _as_obj(row["model_meta"]) or {}
    payload: dict[str, Any] = {
        "id": str(row["id"]),
        "status": row["status"],
        "suite": model_meta.get("suite") or "golden",
        "mode": row["mode"],
        "restart_runtime": bool(row["restart_runtime"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "error": row["error"],
        "model_meta": model_meta,
        "summary": summary,
        "cases": cases,
    }
    if include_logs:
        payload["logs"] = _as_obj(row["logs"]) or []
    return payload


def _row_to_summary(row) -> dict[str, Any]:
    cases = _as_obj(row["cases"]) or []
    summary = _as_obj(row["summary"]) or summary_from_cases(cases)
    model_meta = _as_obj(row["model_meta"]) or {}
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "suite": model_meta.get("suite") or "golden",
        "mode": row["mode"],
        "restart_runtime": bool(row["restart_runtime"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "error": row["error"],
        "model_meta": model_meta,
        "summary": summary,
    }
