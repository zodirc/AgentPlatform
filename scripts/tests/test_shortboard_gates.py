#!/usr/bin/env python3
"""Unit tests for LOC / scenario-leak ratchet scripts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_loc_ratchet_passes_on_repo() -> None:
    mod = _load("check_file_size")
    assert mod.main([]) == 0


def test_loc_ratchet_detects_growth(tmp_path: Path) -> None:
    mod = _load("check_file_size")
    allow = tmp_path / "allow.txt"
    # Point allowlist at a real oversized file with a tiny cap → must fail.
    allow.write_text(
        "services/runtime/app/tools/core/tools.py\t100\n",
        encoding="utf-8",
    )
    assert mod.main(["--allowlist", str(allow)]) == 1


def test_scenario_leak_passes_on_repo() -> None:
    mod = _load("check_scenario_leak")
    assert mod.main([]) == 0


def test_scenario_leak_detects_new_hit(tmp_path: Path) -> None:
    mod = _load("check_scenario_leak")
    # Empty allowlist → every stock leak is NEW.
    allow = tmp_path / "allow.txt"
    allow.write_text("# empty\n", encoding="utf-8")
    assert mod.main(["--allowlist", str(allow)]) == 1


def test_scenario_leak_stale_allowlist(tmp_path: Path) -> None:
    mod = _load("check_scenario_leak")
    allow = tmp_path / "allow.txt"
    # Copy real allowlist + a bogus entry.
    real = (ROOT / "scripts" / "scenario_leak_allowlist.txt").read_text(encoding="utf-8")
    allow.write_text(
        real + "\nservices/runtime/app/engine/agent_engine.py:1\n",
        encoding="utf-8",
    )
    assert mod.main(["--allowlist", str(allow)]) == 1
