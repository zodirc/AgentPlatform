"""Tenant work_root sandbox (docs/27 MT2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tenant_context import bind_tenant_context, reset_tenant_context
from app.tools.core import tools as core_tools


def test_resolve_path_uses_bound_work_root(tmp_path: Path) -> None:
    work_a = tmp_path / "works" / "a"
    work_b = tmp_path / "works" / "b"
    work_a.mkdir(parents=True)
    work_b.mkdir(parents=True)
    (work_a / "only_a.md").write_text("secret-a", encoding="utf-8")
    (work_b / "only_b.md").write_text("secret-b", encoding="utf-8")

    tokens = bind_tenant_context(work_root=str(work_a))
    try:
        resolved = core_tools._resolve_path("only_a.md")
        assert resolved == (work_a / "only_a.md").resolve()
        with pytest.raises(PermissionError):
            # Absolute escape attempt via .. should fail relative_to
            core_tools._resolve_path("../b/only_b.md")
    finally:
        reset_tenant_context(tokens)

    tokens = bind_tenant_context(work_root=str(work_b))
    try:
        resolved = core_tools._resolve_path("only_b.md")
        assert resolved.read_text(encoding="utf-8") == "secret-b"
    finally:
        reset_tenant_context(tokens)
