"""Buffered per-turn writer for high-frequency stream delta events (review I2).

Every ``turn.token`` used to pay a full transaction (advisory lock +
MAX(sequence) + INSERT ≈ 4 DB round-trips). This writer coalesces the four
delta event types into windowed multi-row inserts:

- The first delta after a flush is written immediately, so first-token
  latency is unchanged.
- Subsequent deltas within the window (default 40ms) are flushed together;
  the added client-visible delay is bounded by the window, below the
  LISTEN/NOTIFY + SSE + rAF end-to-end noise floor.
- Any non-delta event flushes the buffer first (see turn_controller), so
  event ordering is byte-identical to per-event writes.
- The flush transaction still allocates sequences under the per-turn
  advisory lock + MAX, so cross-process writers (orphan finalizers, HA
  restarts) remain safe.

``EVENT_BATCH_WINDOW_SECONDS=0`` restores per-event writes (rollback knob).
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

# Only high-frequency stream deltas are coalesced. Everything else keeps the
# existing single-event transactional path.
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
        """Buffer one delta event; validation errors raise at the call site."""
        maybe_validate_event_payload(event_type, payload)
        if event_type == "turn.thinking.delta" and self._skip_thinking_db:
            await self._divert_thinking(payload=payload, step_index=step_index)
            return
        if self._closed or self._window <= 0:
            # Rollback knob / post-close stragglers: per-event write path.
            await self._write_rows([(event_type, payload, step_index)])
            return
        self._buffer.append((event_type, payload, step_index))
        if time.monotonic() - self._last_flush >= self._window:
            await self.flush()
        elif self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _divert_thinking(self, *, payload: dict, step_index: int) -> None:
        """Sidecar + occasional liveness row; no per-chunk turn_events INSERT."""
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
        """Drain the buffer in one multi-row insert transaction."""
        async with self._flush_lock:
            if not self._buffer:
                return
            pending, self._buffer = self._buffer, []
            self._last_flush = time.monotonic()
            await self._write_rows(pending)

    async def close(self) -> None:
        """Final flush + stop the window timer. Cleanup path: never raises."""
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
        await asyncio.sleep(self._window)
        try:
            await self.flush()
        except Exception:
            # Window flush runs outside any caller; surface via logs. The next
            # non-delta event or close() retries nothing — deltas are lost,
            # same blast radius as a failed per-event write.
            logger.exception("windowed delta flush failed turn_id=%s", self._turn_id)

    async def _write_rows(self, rows: list[tuple[str, dict, int]]) -> None:
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
                # Proving liveness while streaming (thinking.delta floods can delay
                # the global heartbeat task past a short lease TTL).
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
                # Long think streams can flush large delta batches under PG
                # statement_timeout; retry with halves instead of failing the turn.
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


# One writer per active turn in this process; popped (and flushed) by
# _fail_turn / _finalize_turn so no terminal event can precede buffered deltas.
_writers: dict[UUID, BufferedEventWriter] = {}


def register_event_writer(turn_id: UUID, writer: BufferedEventWriter) -> None:
    _writers[turn_id] = writer


def get_event_writer(turn_id: UUID) -> BufferedEventWriter | None:
    return _writers.get(turn_id)


async def close_event_writer(turn_id: UUID) -> None:
    writer = _writers.pop(turn_id, None)
    if writer is not None:
        await writer.close()
