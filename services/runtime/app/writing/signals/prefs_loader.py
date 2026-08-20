"""Load writing_prefs without importing agent_contracts package __init__."""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from types import ModuleType

_REL = Path("packages") / "contracts" / "python" / "agent_contracts" / "writing_prefs.py"


def _prefs_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [Path("/contracts/python/agent_contracts/writing_prefs.py")]
    for i, parent in enumerate(here.parents):
        candidates.append(parent / _REL)
        if i >= 6:
            break
    for path in candidates:
        if path.is_file():
            return path
    raise ImportError(f"writing_prefs not found; tried {candidates}")


@lru_cache(maxsize=1)
def _module() -> ModuleType:
    path = _prefs_path()
    spec = importlib.util.spec_from_file_location("agent_contracts.writing_prefs", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"writing_prefs not found at {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def __getattr__(name: str):
    return getattr(_module(), name)
