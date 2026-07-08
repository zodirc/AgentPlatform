from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.services.projection.projector import project_turn
from app.settings import settings

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = frozenset({"turn.completed", "turn.failed", "turn.cancelled"})


class TurnEventListener:
    def __init__(self, *, queue_maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[UUID] = asyncio.Queue(maxsize=queue_maxsize)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._conn = None
        self._consumer_task: asyncio.Task | None = None
        self._listen_task: asyncio.Task | None = None

    async def start(self) -> None:
        from app.db.pool import get_pool

        self._loop = asyncio.get_running_loop()
        await get_pool()
        self._consumer_task = asyncio.create_task(self._consumer_loop())
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

    async def notify(self, turn_id: UUID) -> None:
        try:
            self._queue.put_nowait(turn_id)
        except asyncio.QueueFull:
            logger.warning("projection queue full; turn %s will be reconciled periodically", turn_id)

    async def wait_for_turn(self, turn_id: UUID, timeout: float = 0.3) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            try:
                notified = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return False
            if notified == turn_id:
                return True
            try:
                await project_turn(notified)
            except Exception:
                logger.exception("projection failed for turn %s", notified)

    def _on_notify(self, _conn, _pid, _channel, payload: str) -> None:
        try:
            turn_id = UUID(payload)
        except ValueError:
            return
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, turn_id)

    async def _listen_loop(self) -> None:
        from app.db.pool import get_pool

        pool = await get_pool()
        while True:
            conn = None
            try:
                conn = await pool.acquire()
                await conn.add_listener("turn_events_channel", self._on_notify)
                self._conn = conn
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("LISTEN loop error; retrying in 1s")
                await asyncio.sleep(1)
            finally:
                if conn is not None:
                    try:
                        await conn.remove_listener("turn_events_channel", self._on_notify)
                    except Exception:
                        pass
                    await pool.release(conn)
                    self._conn = None

    async def _consumer_loop(self) -> None:
        while True:
            turn_id = await self._queue.get()
            try:
                await project_turn(turn_id)
                if settings.worker_mode == "inline":
                    await self._inline_session_summary(turn_id)
                await self._maybe_enqueue_async_jobs(turn_id)
            except Exception:
                logger.exception("projection failed for turn %s", turn_id)

    async def _inline_session_summary(self, turn_id: UUID) -> None:
        from app.db.pool import get_pool
        from app.services.jobs.handlers import handle_session_summary

        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT type FROM turn_events
            WHERE turn_id = $1
            ORDER BY sequence DESC
            LIMIT 1
            """,
            turn_id,
        )
        if row is None or row["type"] not in TERMINAL_EVENTS:
            return
        await handle_session_summary({"turn_id": str(turn_id)})

    async def _maybe_enqueue_async_jobs(self, turn_id: UUID) -> None:
        if settings.worker_mode != "outbox":
            return
        from app.db.pool import get_pool
        from app.services.outbox import enqueue_turn_jobs

        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT t.scenario_id, te.type AS last_type
            FROM turns t
            JOIN LATERAL (
                SELECT type FROM turn_events
                WHERE turn_id = t.id
                ORDER BY sequence DESC
                LIMIT 1
            ) te ON true
            WHERE t.id = $1
            """,
            turn_id,
        )
        if row is None or row["last_type"] not in TERMINAL_EVENTS:
            return
        await enqueue_turn_jobs(turn_id=turn_id, scenario_id=row["scenario_id"])
