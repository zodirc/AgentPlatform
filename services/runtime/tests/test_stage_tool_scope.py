from __future__ import annotations

from app.tools.bootstrap import stage_tool_runtime_blocked, stage_tool_scope
from app.tools.registry import ToolSpec


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        handler=lambda **_kwargs: {"ok": True},
    )


def test_stage_tool_scope_keeps_early_tools() -> None:
    specs = [_spec("search_sources"), _spec("read_file"), _spec("export_document")]
    out = stage_tool_scope(specs, step_count=1, max_steps=40, delivery=None)
    assert [s.name for s in out] == [s.name for s in specs]


def test_stage_tool_scope_static_by_default_even_after_delivery(monkeypatch) -> None:
    """C2 default: schema stays full; runtime gate handles late drops."""
    from app.settings import settings

    monkeypatch.setattr(settings, "stage_tool_scope_mutate_schema", False)
    specs = [_spec("search_sources"), _spec("delegate"), _spec("read_file")]
    out = stage_tool_scope(
        specs,
        step_count=3,
        max_steps=40,
        delivery={"delivery_status": "ok"},
    )
    assert [s.name for s in out] == [s.name for s in specs]
    assert stage_tool_runtime_blocked(
        "search_sources",
        step_count=3,
        max_steps=40,
        delivery={"delivery_status": "ok"},
    )


def test_stage_tool_scope_legacy_mutate_when_enabled(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "stage_tool_scope_mutate_schema", True)
    specs = [_spec("search_sources"), _spec("delegate"), _spec("read_file")]
    out = stage_tool_scope(
        specs,
        step_count=3,
        max_steps=40,
        delivery={"delivery_status": "ok"},
    )
    assert [s.name for s in out] == ["read_file"]
