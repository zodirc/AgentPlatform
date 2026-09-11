from __future__ import annotations

from pathlib import Path

from app.writing.regime import (
    resolve_regime,
    save_regime_override,
)


def test_short_is_always_strict_even_if_user_pins_author(tmp_path: Path) -> None:
    save_regime_override(value="author", source="user", workspace_root=tmp_path)
    value, source = resolve_regime("写一篇短篇小说", workspace_root=tmp_path)
    assert value == "strict"
    assert source == "default"


def test_single_is_always_strict(tmp_path: Path) -> None:
    value, source = resolve_regime("写一篇故事", workspace_root=tmp_path)
    assert value == "strict"
    assert source == "default"


def test_long_defaults_to_author(tmp_path: Path) -> None:
    value, source = resolve_regime("写一章长篇第一章", workspace_root=tmp_path)
    assert value == "author"
    assert source == "default"


def test_user_pin_strict_on_long(tmp_path: Path) -> None:
    save_regime_override(value="strict", source="user", workspace_root=tmp_path)
    value, source = resolve_regime("写一章长篇", workspace_root=tmp_path)
    assert value == "strict"
    assert source == "user"


def test_message_override_beats_user_pin(tmp_path: Path) -> None:
    save_regime_override(value="strict", source="user", workspace_root=tmp_path)
    value, source = resolve_regime("写一章长篇 作者模式", workspace_root=tmp_path)
    assert value == "author"
    assert source == "message"
    value, source = resolve_regime("写一章长篇 严格模式", workspace_root=tmp_path)
    assert value == "strict"
    assert source == "message"
