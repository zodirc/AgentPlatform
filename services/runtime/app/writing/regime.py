"""写作档位：strict = 现行闸门；author = 作者态方案。Engine 不读本模块。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from app.writing.book_scope import (
    BookScope,
    explicit_book_scope,
    resolve_book_scope,
)

Regime = Literal["author", "strict"]
RegimeSource = Literal["default", "user", "message"]

_AUTHOR_PHRASE = re.compile(r"作者模式|作者档")
_STRICT_PHRASE = re.compile(r"严格模式|严格档")


def normalize_regime(value: str | None) -> Regime:
    token = (value or "").strip().lower()
    if token in {"author", "strict"}:
        return token  # type: ignore[return-value]
    return "strict"


def explicit_regime(message: str = "") -> Regime | None:
    """句里写明的档位。短篇/单篇调用方会再压成 strict。"""
    blob = message or ""
    author_hits = [m.start() for m in _AUTHOR_PHRASE.finditer(blob)]
    strict_hits = [m.start() for m in _STRICT_PHRASE.finditer(blob)]
    if not author_hits and not strict_hits:
        return None
    last_author = author_hits[-1] if author_hits else -1
    last_strict = strict_hits[-1] if strict_hits else -1
    return "author" if last_author > last_strict else "strict"


def load_regime_override(
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    from app.writing.work_mode import load_writing_prefs

    data = load_writing_prefs(workspace_root=workspace_root)
    raw = data.get("regime")
    if not isinstance(raw, dict):
        return None
    source = str(raw.get("source") or "default").strip().lower()
    if source not in {"default", "user"}:
        source = "default"
    return {
        "value": normalize_regime(str(raw.get("value") or "")),
        "source": source,
    }


def save_regime_override(
    *,
    value: str,
    source: RegimeSource = "user",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    from app.writing.work_mode import load_writing_prefs, save_writing_prefs

    data = load_writing_prefs(workspace_root=workspace_root)
    src: RegimeSource = "user" if source == "user" else "default"
    data["regime"] = {"value": normalize_regime(value), "source": src}
    return save_writing_prefs(data, workspace_root=workspace_root)


def default_regime_for_scope(scope: str) -> Regime:
    from app.writing.book_scope import normalize_book_scope

    return "author" if normalize_book_scope(scope) == "long" else "strict"


def resolve_regime(
    message: str = "",
    *,
    workspace_root: Path | None = None,
    book_scope: str | None = None,
) -> tuple[Regime, RegimeSource]:
    """句内覆盖 > 用户钉死 > 尺度默认。短篇/单篇永远 strict。"""
    scope: BookScope
    if book_scope:
        from app.writing.book_scope import normalize_book_scope

        scope = normalize_book_scope(book_scope)
    else:
        named_scope = explicit_book_scope(message)
        if named_scope is not None:
            scope = named_scope
        else:
            scope, _src = resolve_book_scope(
                message, workspace_root=workspace_root
            )
    if scope in {"short", "single"}:
        return "strict", "default"
    named = explicit_regime(message)
    if named is not None:
        return named, "message"
    stored = load_regime_override(workspace_root=workspace_root)
    if stored and stored.get("source") == "user":
        return normalize_regime(str(stored.get("value"))), "user"
    return default_regime_for_scope(scope), "default"


def is_author_regime(
    message: str = "",
    *,
    workspace_root: Path | None = None,
    book_scope: str | None = None,
) -> bool:
    value, _src = resolve_regime(
        message, workspace_root=workspace_root, book_scope=book_scope
    )
    return value == "author"
