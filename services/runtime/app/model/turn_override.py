"""Per-Turn model mode / override (docs/29 ops eval)."""

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
    mode: ModelMode | None
    override: ModelConfig | None


def current_turn_model_mode() -> ModelMode | None:
    return _turn_model_mode.get()


def current_turn_model_override() -> ModelConfig | None:
    return _turn_model_override.get()


def bind_turn_model(
    *,
    mode: ModelMode | None = None,
    override: ModelConfig | None = None,
) -> tuple[Token, Token]:
    return (
        _turn_model_mode.set(mode),
        _turn_model_override.set(override),
    )


def reset_turn_model(tokens: tuple[Token, Token]) -> None:
    _turn_model_mode.reset(tokens[0])
    _turn_model_override.reset(tokens[1])


@contextmanager
def turn_model_scope(
    *,
    mode: ModelMode | None = None,
    override: ModelConfig | None = None,
) -> Iterator[None]:
    tokens = bind_turn_model(mode=mode, override=override)
    try:
        yield
    finally:
        reset_turn_model(tokens)
