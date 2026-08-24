
"""Turn 级 model mode/override ContextVar（docs/29 Ops eval）。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator, Literal

from app.model.config import ModelConfig

ModelMode = Literal["stub", "live", "recorded"]

_turn_model_mode: ContextVar[ModelMode | None] = ContextVar("turn_model_mode", default=None)
_turn_model_override: ContextVar[ModelConfig | None] = ContextVar("turn_model_override", default=None)


@dataclass(frozen=True)
class TurnModelBinding:
    """作用：Turn 级 mode + override 快照。"""
    mode: ModelMode | None
    override: ModelConfig | None


def current_turn_model_mode() -> ModelMode | None:
    """作用：读取 stub/live/recorded 模式。"""
    return _turn_model_mode.get()


def current_turn_model_override() -> ModelConfig | None:
    """作用：读取 ModelConfig 覆盖。"""
    return _turn_model_override.get()


def bind_turn_model(
    *,
    mode: ModelMode | None = None,
    override: ModelConfig | None = None,
) -> tuple[Token, Token]:
    """作用：设置 Turn 模型 ContextVar。"""
    return (
        _turn_model_mode.set(mode),
        _turn_model_override.set(override),
    )


def reset_turn_model(tokens: tuple[Token, Token]) -> None:
    """作用：reset Turn 模型 ContextVar。"""
    _turn_model_mode.reset(tokens[0])
    _turn_model_override.reset(tokens[1])


@contextmanager
def turn_model_scope(
    *,
    mode: ModelMode | None = None,
    override: ModelConfig | None = None,
) -> Iterator[None]:
    """作用：contextmanager 绑定/恢复 Turn 模型。"""
    tokens = bind_turn_model(mode=mode, override=override)
    try:
        yield
    finally:
        reset_turn_model(tokens)
