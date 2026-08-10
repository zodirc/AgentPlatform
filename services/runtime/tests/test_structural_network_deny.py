from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.settings import settings
from app.tenant_context import (
    bind_tenant_context,
    reset_tenant_context,
    sandbox_network_allowed,
)
from app.tools.core.sandbox import wrap_argv_for_exec


def test_sandbox_network_allowed_only_denies_ops_eval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "ops_eval_deny_network", True)
    tokens = bind_tenant_context(work_root=str(tmp_path), ops_eval=False)
    try:
        assert sandbox_network_allowed() is True
    finally:
        reset_tenant_context(tokens)

    tokens = bind_tenant_context(work_root=str(tmp_path), ops_eval=True)
    try:
        assert sandbox_network_allowed() is False
    finally:
        reset_tenant_context(tokens)


def test_wrap_argv_forces_bwrap_unshare_when_deny(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "ops_eval_deny_network", True)
    monkeypatch.setattr(
        "app.tools.core.sandbox._which_bwrap",
        lambda: "/usr/bin/bwrap",
    )
    monkeypatch.setattr("app.tools.core.sandbox._bwrap_can_exec", lambda: True)
    tokens = bind_tenant_context(work_root=str(tmp_path), ops_eval=True)
    try:
        argv, backend = wrap_argv_for_exec(argv=["echo", "hi"], cwd=tmp_path)
        assert backend == "bwrap"
        assert "--unshare-net" in argv
    finally:
        reset_tenant_context(tokens)


def test_wrap_argv_fail_closed_without_bwrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "ops_eval_deny_network", True)
    monkeypatch.setattr("app.tools.core.sandbox._which_bwrap", lambda: None)
    tokens = bind_tenant_context(work_root=str(tmp_path), ops_eval=True)
    try:
        with pytest.raises(RuntimeError, match="ops_eval_deny_network"):
            wrap_argv_for_exec(argv=["echo", "hi"], cwd=tmp_path)
    finally:
        reset_tenant_context(tokens)
