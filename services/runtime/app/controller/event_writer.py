"""单轮次高频流式 delta 事件的缓冲写入器（review I2）。

English: Buffered per-turn writer for high-frequency stream delta events (review I2).

原先每个 ``turn.token`` 都要走完整事务（advisory lock + MAX(sequence) + INSERT，
约 4 次 DB 往返）。本模块将四类 delta 事件合并为窗口化多行 INSERT：

- 刷新后第一条 delta 立即写入，首 token 延迟不变。
- 窗口内（默认 40ms）后续 delta 批量刷盘；客户端可见的额外延迟有上界，
  低于 LISTEN/NOTIFY + SSE + rAF 端到端噪声底。
- 任意非 delta 事件会先刷缓冲（见 turn_controller），事件顺序与逐条写入字节一致。
- 刷盘事务仍在 per-turn advisory lock + MAX 下分配 sequence，
  跨进程写入（孤儿 finalizer、HA 重启）仍安全。

``EVENT_BATCH_WINDOW_SECONDS=0`` 可恢复逐条写入（回滚旋钮）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

from app.contracts.event_validation import maybe_validate_event_payload
from app.controller.events import next_sequence
from app.controller.thinking_sidecar import sidecar_line
from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)

# 仅合并高频流式 delta；其余事件仍走原有单条事务路径。
DELTA_EVENT_TYPES = frozenset(
    {
        "turn.token",
        "turn.thinking.delta",
        "tool.delta",
        "section.draft.delta",
    }
)

_INSERT_SQL = """
INSERT INTO turn_events (
    event_id, turn_id, stream_id, sequence, type, run_id,
    step_index, trace_id, causation_id, ts, payload
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
"""


class BufferedEventWriter:
    """按时间窗口缓冲 delta 事件，批量写入 ``turn_events``。

    English: Windowed coalescing writer for high-frequency delta events (review I2).
    """

    def __init__(
        self,
        *,
        turn_id: UUID,
        run_id: UUID,
        trace_id: UUID,
        window_seconds: float | None = None,
        skip_thinking_db: bool = False,
        sidecar_path: Path | None = None,
        heartbeat_seconds: float | None = None,
    ) -> None:
        """构造单轮缓冲写入器。

        参数:
            turn_id: 所属 turn，用于 advisory lock 与事件归属。
            run_id: 所属 run，刷盘成功后 touch 租约。
            trace_id: 追踪 ID，写入每条事件的 trace_id 列。
            window_seconds: 合并窗口秒数；``None`` 时用 ``settings.event_batch_window_seconds``。
            skip_thinking_db: 为真时 ``turn.thinking.delta`` 不写 DB，改走 sidecar + 心跳。
            sidecar_path: thinking 旁路文件路径；``skip_thinking_db`` 时追加 delta 文本。
            heartbeat_seconds: sidecar 模式下 ``turn.thinking`` 存活行间隔；``None`` 用 settings 默认。
        """
        self._turn_id = turn_id
        self._run_id = run_id
        self._trace_id = trace_id
        self._window = (
            settings.event_batch_window_seconds
            if window_seconds is None
            else window_seconds
        )
        self._buffer: list[tuple[str, dict, int]] = []
        self._flush_lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._last_flush = 0.0
        self._closed = False
        self._skip_thinking_db = bool(skip_thinking_db)
        self._sidecar_path = sidecar_path
        self._heartbeat_seconds = (
            float(settings.ops_eval_thinking_heartbeat_seconds)
            if heartbeat_seconds is None
            else float(heartbeat_seconds)
        )
        self._sidecar_buf: list[str] = []
        self._last_heartbeat = 0.0
        self._omitted_thinking = 0

    async def append_delta(
        self, *, event_type: str, payload: dict, step_index: int
    ) -> None:
        """缓冲一条 delta 事件；校验失败在调用处抛异常。

        English: Buffer one delta; first after flush writes immediately, then batch within window.

        参数:
            event_type: 须为 ``DELTA_EVENT_TYPES`` 之一。
            payload: 写入前经 schema 校验。
            step_index: Engine 步序号。
        """
        maybe_validate_event_payload(event_type, payload)
        if event_type == "turn.thinking.delta" and self._skip_thinking_db:
            await self._divert_thinking(payload=payload, step_index=step_index)
            return
        if self._closed or self._window <= 0:
            # 回滚旋钮 / 关闭后迟到的 delta：不走缓冲，逐条写库。
            await self._write_rows([(event_type, payload, step_index)])
            return
        self._buffer.append((event_type, payload, step_index))
        if time.monotonic() - self._last_flush >= self._window:
            await self.flush()
        elif self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _divert_thinking(self, *, payload: dict, step_index: int) -> None:
        """将 thinking delta 旁路到 sidecar 文件，并周期性写存活行。

        避免 thinking.delta 洪泛占满 ``turn_events``；客户端仍可通过
        ``turn.thinking`` 心跳与 sidecar 文件感知进度。

        参数:
            payload: delta 载荷，取 ``delta`` 字段写入 sidecar。
            step_index: 当前步序号，用于 sidecar 行格式与心跳 payload。

        返回:
            None
        """
        self._omitted_thinking += 1
        if self._sidecar_path is not None:
            self._sidecar_buf.append(
                sidecar_line(
                    step_index=step_index,
                    delta=str(payload.get("delta") or ""),
                )
            )
            if len(self._sidecar_buf) >= 32:
                await self._flush_sidecar()
        now = time.monotonic()
        if self._heartbeat_seconds > 0 and (
            self._last_heartbeat == 0.0
            or now - self._last_heartbeat >= self._heartbeat_seconds
        ):
            self._last_heartbeat = now
            await self._flush_sidecar()
            live_payload = {"step_index": step_index, "label": "sidecar-live"}
            maybe_validate_event_payload("turn.thinking", live_payload)
            async with self._flush_lock:
                await self._write_rows(
                    [
                        (
                            "turn.thinking",
                            live_payload,
                            step_index,
                        )
                    ]
                )

    async def _flush_sidecar(self) -> None:
        """将内存中的 sidecar 片段追加到磁盘文件。

        参数:
            无（使用实例 ``_sidecar_buf`` 与 ``_sidecar_path``）。

        返回:
            None
        """
        if not self._sidecar_buf or self._sidecar_path is None:
            return
        blob = "".join(self._sidecar_buf)
        self._sidecar_buf = []
        path = self._sidecar_path

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(blob)

        try:
            await asyncio.to_thread(_write)
        except Exception:
            logger.warning(
                "thinking sidecar write failed turn_id=%s path=%s",
                self._turn_id,
                path,
                exc_info=True,
            )

    async def flush(self) -> None:
        """在单次事务中刷空缓冲区的全部 delta。

        English: Flush all buffered deltas in one transaction under advisory lock.
        Non-delta events in turn_controller call flush first to preserve ordering.
        """
        async with self._flush_lock:
            if not self._buffer:
                return
            pending, self._buffer = self._buffer, []
            self._last_flush = time.monotonic()
            await self._write_rows(pending)

    async def close(self) -> None:
        """最终刷盘并停止窗口定时器；清理路径不向外抛异常。

        参数:
            无

        返回:
            None
        """
        self._closed = True
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await self.flush()
        except Exception:
            logger.exception(
                "final delta flush failed turn_id=%s (deltas dropped)", self._turn_id
            )
        try:
            await self._flush_sidecar()
        except Exception:
            logger.warning(
                "final thinking sidecar flush failed turn_id=%s",
                self._turn_id,
                exc_info=True,
            )

    async def _delayed_flush(self) -> None:
        """窗口到期后异步刷盘；失败仅记日志。

        参数:
            无（睡眠 ``self._window`` 后调用 ``flush``）。

        返回:
            None
        """
        await asyncio.sleep(self._window)
        try:
            await self.flush()
        except Exception:
            # 窗口刷盘无调用方兜底；记日志。后续非 delta 或 close 不会重试——
            # delta 丢失，影响面与单条写入失败相同。
            logger.exception("windowed delta flush failed turn_id=%s", self._turn_id)

    async def _write_rows(self, rows: list[tuple[str, dict, int]]) -> None:
        """在 advisory lock 下批量 INSERT，含 sequence 竞态与超时重试。

        参数:
            rows: ``(event_type, payload, step_index)`` 列表，一次事务内连续 sequence。

        返回:
            None

        抛出:
            RuntimeError: 重试耗尽仍失败。
        """
        pool = await get_pool()
        last_error: Exception | None = None
        pending = rows
        for attempt in range(5):
            try:
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        start = await next_sequence(conn, self._turn_id)
                        now = datetime.now(timezone.utc)
                        args = [
                            (
                                uuid4(),
                                self._turn_id,
                                self._turn_id,
                                start + offset,
                                event_type,
                                self._run_id,
                                step_index,
                                self._trace_id,
                                None,
                                now,
                                json.dumps(payload),
                            )
                            for offset, (event_type, payload, step_index) in enumerate(
                                pending
                            )
                        ]
                        await conn.executemany(_INSERT_SQL, args)
                # 流式期间证明 run 仍存活（thinking.delta 洪泛可能拖慢全局心跳任务，超过短租约 TTL）。
                try:
                    from app.controller import run_lock

                    await run_lock.touch_run_lease(run_id=self._run_id)
                except Exception:
                    pass
                return
            except asyncpg.UniqueViolationError as exc:
                last_error = exc
                logger.warning(
                    "turn_events batch sequence race turn_id=%s attempt=%s size=%s",
                    self._turn_id,
                    attempt + 1,
                    len(pending),
                )
                continue
            except (TimeoutError, asyncio.TimeoutError, asyncpg.InterfaceError) as exc:
                # 长思考流可能在 PG statement_timeout 下刷大批 delta；拆半重试而非整轮失败。
                last_error = exc
                logger.warning(
                    "turn_events batch timeout/interface turn_id=%s attempt=%s size=%s err=%s",
                    self._turn_id,
                    attempt + 1,
                    len(pending),
                    type(exc).__name__,
                )
                if len(pending) > 1:
                    mid = max(1, len(pending) // 2)
                    head, tail = pending[:mid], pending[mid:]
                    await self._write_rows(head)
                    pending = tail
                    continue
                await asyncio.sleep(0.05 * (attempt + 1))
                continue
        raise RuntimeError(
            f"failed to append {len(rows)} delta events for turn {self._turn_id} after retries"
        ) from last_error


# 本进程每个活跃 turn 一个 writer；由 _fail_turn / _finalize_turn 弹出并 flush，
# 保证终态事件不会排在缓冲 delta 之前。
_writers: dict[UUID, BufferedEventWriter] = {}


def register_event_writer(turn_id: UUID, writer: BufferedEventWriter) -> None:
    """注册 turn 对应的缓冲写入器。

    参数:
        turn_id: turn 标识。
        writer: 已构造的 ``BufferedEventWriter`` 实例。

    返回:
        None
    """
    _writers[turn_id] = writer


def get_event_writer(turn_id: UUID) -> BufferedEventWriter | None:
    """按 turn_id 查找本进程已注册的写入器。

    参数:
        turn_id: turn 标识。

    返回:
        已注册的 ``BufferedEventWriter``，未注册则 ``None``。
    """
    return _writers.get(turn_id)


async def close_event_writer(turn_id: UUID) -> None:
    """从注册表移除写入器并执行 ``close``（最终刷盘）。

    参数:
        turn_id: turn 标识。

    返回:
        None
    """
    writer = _writers.pop(turn_id, None)
    if writer is not None:
        await writer.close()
