"""Persist Ops Eval runs to Postgres (docs/29 history)."""

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
    return {
        "total": len(cases),
        "pass": sum(1 for c in cases if c.get("status") == "pass"),
        "fail": sum(1 for c in cases if c.get("status") == "fail"),
        "skipped": sum(1 for c in cases if c.get("status") == "skipped"),
        "pending": sum(1 for c in cases if c.get("status") in {"pending", "running"}),
    }


def model_meta_safe(model: dict[str, Any] | None) -> dict[str, Any]:
    if not model:
        return {}
    return {
        "provider": model.get("provider"),
        "model_name": model.get("model_name"),
        "base_url": model.get("base_url"),
        # intentionally omit api_key
    }


async def upsert_run(payload: dict[str, Any]) -> None:
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
    """Delete ops_eval_runs rows. When suite is set, only that suite (model_meta)."""
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
    """Delete specific run ids (optionally constrained to suite)."""
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
    """Delete runs with created_at strictly before ``before_iso`` (timestamptz)."""
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
