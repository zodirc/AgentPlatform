"""写作内核对外端口。

默认实现是服务器上的 Postgres / controller。宿主在回合开始前绑定文件实现。
``app/writing``、``app/engine``、``app/context`` 只从这里出去，不直接导入
``app.db``、``app.controller`` 或 ``asyncpg``。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable
from uuid import UUID

_buffered: ContextVar[Callable[[UUID], Any] | None] = ContextVar("port_buffered", default=None)
_evaluation: ContextVar[Any] = ContextVar("port_evaluation", default=None)
_prefs: ContextVar[Any] = ContextVar("port_prefs", default=None)
_summary: ContextVar[Any] = ContextVar("port_summary", default=None)
_owner: ContextVar[Callable[..., Awaitable[Any]] | None] = ContextVar("port_owner", default=None)
_history: ContextVar[Callable[..., Awaitable[Any]] | None] = ContextVar("port_history", default=None)
class _Unset:
    pass


_EMBEDDER_UNSET = _Unset()
_embedder: ContextVar[Any] = ContextVar("port_embedder", default=_EMBEDDER_UNSET)
_model: ContextVar[Callable[..., Awaitable[Any]] | None] = ContextVar("port_model", default=None)


def bind_buffered_writer(fn: Callable[[UUID], Any] | None):
    return _buffered.set(fn)


def reset_buffered_writer(token) -> None:
    _buffered.reset(token)


def buffered_writer(turn_id: UUID):
    custom = _buffered.get()
    if custom is not None:
        return custom(turn_id)
    from app.controller.event_writer import get_event_writer

    return get_event_writer(turn_id)


def bind_evaluation_store(store):
    return _evaluation.set(store)


def reset_evaluation_store(token) -> None:
    _evaluation.reset(token)


def evaluation_store():
    current = _evaluation.get()
    if current is not None:
        return current
    from app.adapters.server_ports import PostgresEvaluationStore

    return PostgresEvaluationStore()


def bind_prefs_source(source):
    return _prefs.set(source)


def reset_prefs_source(token) -> None:
    _prefs.reset(token)


def prefs_source():
    current = _prefs.get()
    if current is not None:
        return current
    from app.adapters.server_ports import PostgresPrefsSource

    return PostgresPrefsSource()


_pool_factory: ContextVar[Callable[[], Awaitable[Any]] | None] = ContextVar(
    "port_pool", default=None
)


def bind_pool_factory(factory: Callable[[], Awaitable[Any]] | None):
    return _pool_factory.set(factory)


def reset_pool_factory(token) -> None:
    _pool_factory.reset(token)


async def acquire_pool():
    factory = _pool_factory.get()
    if factory is not None:
        return await factory()
    from app.db.pool import get_pool

    return await get_pool()


def bind_summary_store(store):
    return _summary.set(store)


def reset_summary_store(token) -> None:
    _summary.reset(token)


async def load_context_summary(session_id: UUID):
    current = _summary.get()
    if current is not None:
        return await current.load(session_id)
    from app.adapters.server_ports import load_context_summary as impl

    return await impl(session_id)


async def save_context_summary(session_id: UUID, record: dict[str, Any]) -> None:
    current = _summary.get()
    if current is not None:
        await current.save(session_id, record)
        return
    from app.adapters.server_ports import save_context_summary as impl

    await impl(session_id, record)


def bind_session_owner(fn: Callable[..., Awaitable[Any]] | None):
    return _owner.set(fn)


def reset_session_owner(token) -> None:
    _owner.reset(token)


async def load_session_owner_user_id(session_id):
    custom = _owner.get()
    if custom is not None:
        return await custom(session_id)
    from app.controller.session_context import load_session_owner_user_id as impl

    return await impl(session_id)


async def load_session_work(session_id):
    from app.controller.session_context import load_session_work as impl

    return await impl(session_id)


def bind_turn_history(fn: Callable[..., Awaitable[Any]] | None):
    return _history.set(fn)


def reset_turn_history(token) -> None:
    _history.reset(token)


async def load_session_turn_history(session_id, *, limit: int = 20):
    custom = _history.get()
    if custom is not None:
        return await custom(session_id, limit=limit)
    from app.controller.session_compact import load_session_turn_history as impl

    return await impl(session_id, limit=limit)


def bind_embedder(embedder):
    return _embedder.set(embedder)


def reset_embedder(token) -> None:
    _embedder.reset(token)


def get_embedder():
    """未绑定时走检索实现。宿主绑定 None 表示没有向量嵌入。"""
    value = _embedder.get()
    if value is _EMBEDDER_UNSET:
        from app.retrieval.embedder import get_embedder as impl

        return impl()
    return value


def bind_model_resolver(fn: Callable[..., Awaitable[Any]] | None):
    return _model.set(fn)


def reset_model_resolver(token) -> None:
    _model.reset(token)


async def resolve_model_config(**kwargs):
    custom = _model.get()
    if custom is not None:
        return await custom(**kwargs)
    from app.model.config import resolve_model_config as impl

    return await impl(**kwargs)


def current_event_writer():
    from app.controller.runtime_context import get_event_writer

    return get_event_writer()


_raw_snapshot: ContextVar[Callable[..., Awaitable[Any]] | None] = ContextVar(
    "port_raw_snapshot", default=None
)
_envelope: ContextVar[Callable[..., Awaitable[Any]] | None] = ContextVar(
    "port_envelope", default=None
)


def bind_raw_snapshot(fn: Callable[..., Awaitable[Any]] | None):
    return _raw_snapshot.set(fn)


def reset_raw_snapshot(token) -> None:
    _raw_snapshot.reset(token)


def bind_model_envelope(fn: Callable[..., Awaitable[Any]] | None):
    return _envelope.set(fn)


def reset_model_envelope(token) -> None:
    _envelope.reset(token)


async def schedule_raw_snapshot(**kwargs):
    custom = _raw_snapshot.get()
    if custom is not None:
        return await custom(**kwargs)
    from app.controller.session_raw import append_raw_snapshot

    return await append_raw_snapshot(**kwargs)


async def persist_model_envelope(**kwargs):
    custom = _envelope.get()
    if custom is not None:
        return await custom(**kwargs)
    from app.observability.model_envelope import maybe_persist_model_envelope

    return await maybe_persist_model_envelope(**kwargs)
