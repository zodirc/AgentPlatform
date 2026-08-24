"""Turn 事件 LISTEN/NOTIFY 监听器：唤醒 SSE 等待者与异步投影消费者。

独立 PostgreSQL 连接订阅 ``turn_events_channel``，与请求池隔离，避免长连接
占满 hot pool；队列满时依赖周期性 reconcile 兜底。
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from cachetools import TTLCache

from app.services.projection.projector import project_turn
from app.settings import settings

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = frozenset({"turn.completed", "turn.failed", "turn.cancelled"})

# B6: how often the LISTEN connection is probed for liveness.
_LISTEN_PROBE_SECONDS = 30.0


class TurnEventListener:
    """turn_events NOTIFY → 投影队列 + per-turn asyncio.Event _fan-out。"""

    def __init__(self, *, queue_maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[UUID] = asyncio.Queue(maxsize=queue_maxsize)
        # B9: per-turn waiter Events were never removed; a TTL cache bounds the
        # map (finished turns stop being waited on well within the TTL).
        self._turn_events: TTLCache = TTLCache(maxsize=4096, ttl=3600)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._conn = None
        self._consumer_task: asyncio.Task | None = None
        self._listen_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动 LISTEN 循环与投影 consumer 任务。

        参数:
            无。

        返回:
            None。
        """
        from app.db.pool import get_pool

        self._loop = asyncio.get_running_loop()
        await get_pool()
        self._consumer_task = asyncio.create_task(self._consumer_loop())
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        """取消后台任务并等待退出（应用 shutdown）。

        参数:
            无。

        返回:
            None。
        """
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
        """本地唤醒：create_turn 等路径在无 NOTIFY 时主动 fan-out。

        参数:
            turn_id: 有新事件或需投影的 turn。

        返回:
            None。
        """
        self._fan_out(turn_id)

    def _fan_out(self, turn_id: UUID) -> None:
        """唤醒该 turn 的 SSE 等待者并入队投影任务。

        参数:
            turn_id: Turn UUID。

        返回:
            None；队列满时打 warning 并计 metric，依赖周期 reconcile。
        """
        self._turn_events.setdefault(turn_id, asyncio.Event()).set()
        try:
            self._queue.put_nowait(turn_id)
        except asyncio.QueueFull:
            logger.warning("projection queue full; turn %s will be reconciled periodically", turn_id)
            try:
                from app.observability.metrics import metrics

                metrics.inc("projection_queue_full_total")
            except Exception:
                pass

    async def wait_for_turn(self, turn_id: UUID, timeout: float = 0.3) -> bool:
        """阻塞直到 turn 收到 NOTIFY 或超时（SSE 空闲轮询用）。

        参数:
            turn_id: 监听的 turn。
            timeout: 最长等待秒数。

        返回:
            True 表示在超时前被唤醒；False 表示超时。
        """
        event = self._turn_events.setdefault(turn_id, asyncio.Event())
        if event.is_set():
            event.clear()
            return True
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        event.clear()
        return True

    def _on_notify(self, _conn, _pid, _channel, payload: str) -> None:
        try:
            turn_id = UUID(payload)
        except ValueError:
            return
        if self._loop is not None:

            def _enqueue() -> None:
                self._fan_out(turn_id)

            self._loop.call_soon_threadsafe(_enqueue)

    async def _listen_loop(self) -> None:
        """订阅 ``turn_events_channel``；断线重连并定期 SELECT 1 探活（B6）。

        参数:
            无。

        返回:
            None；异常时 sleep 1s 后重连。
        """
        import asyncpg

        while True:
            conn = None
            try:
                # LISTEN stays checked out indefinitely. Keep it separate from
                # the request/query pool so realtime cannot starve API traffic.
                conn = await asyncpg.connect(settings.database_url)
                await conn.add_listener("turn_events_channel", self._on_notify)
                self._conn = conn
                # B6: a half-open connection (PG restart, network blip) never
                # raises by itself — probe it so the outer loop reconnects
                # instead of silently degrading realtime to polling.
                while True:
                    await asyncio.sleep(_LISTEN_PROBE_SECONDS)
                    await conn.execute("SELECT 1")
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
                    await conn.close()
                    self._conn = None

    async def _consumer_loop(self) -> None:
        """从队列取 turn_id 执行 ``project_turn``，终端事件后触发 session 摘要/outbox。

        参数:
            无。

        返回:
            None；单 turn 投影失败记日志不终止循环。
        """
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
        """inline worker 模式：turn 终端后同步写 session 摘要。

        参数:
            turn_id: 刚投影的 turn。

        返回:
            None；末事件非 terminal 时 no-op。
        """
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
        """outbox 模式：从 terminal 事件 payload 提取 post_turn_jobs 入队。

        参数:
            turn_id: 刚完成的 turn。

        返回:
            None；``worker_mode != outbox`` 时直接返回。
        """
        if settings.worker_mode != "outbox":
            return
        from app.db.pool import get_pool
        from app.services.outbox import enqueue_turn_jobs

        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT t.scenario_id, te.type AS last_type, te.payload AS last_payload
            FROM turns t
            JOIN LATERAL (
                SELECT type, payload FROM turn_events
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
        jobs: list[str] = []
        raw = row["last_payload"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = None
        if isinstance(raw, dict):
            for item in raw.get("post_turn_jobs") or []:
                name = str(item or "").strip()
                if name:
                    jobs.append(name)
        await enqueue_turn_jobs(
            turn_id=turn_id,
            scenario_id=row["scenario_id"],
            post_turn_jobs=jobs,
        )
