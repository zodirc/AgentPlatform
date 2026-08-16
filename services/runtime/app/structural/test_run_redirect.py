"""ops_eval + SWE marker: run_command → sweb.eval (tests + env probes).

Peels display-only pipelines (``| tail`` / ``| grep`` / …) so agents that
truncate for readability still get full test output + test_summary via the
solve-side image path. Same weld style as pager→read_file (C-2).

Also redirects env archaeology (``python --version``, ``python -c "import …"``)
into the instance image, and rejects ``pip``/``uv install`` in the Work.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from app.tools.core.test_command_gate import gate_run_tests_command

# First pipeline stage must be a test launcher; later stages may be view filters.
_VIEW_HEAD = frozenset(
    {
        "tail",
        "head",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "sed",
        "awk",
        "uniq",
        "sort",
        "wc",
        "cat",
        "colrm",
        "cut",
        "tr",
    }
)
_REDIR_TAIL = re.compile(r"(?:2>&1|1>&2|&>/dev/null|2>/dev/null|1>/dev/null)\s*$")
_CD_AND = re.compile(r"^cd\s+(?P<dir>\S+)\s+&&\s+", re.IGNORECASE)
# pip / uv install — env archaeology in bare worktree when sweb.eval is available.
_PIP_INSTALL = re.compile(
    r"(?:^|[;&|]\s*)(?:python\d*(?:\.\d+)?\s+-m\s+)?(?:pip\d*|uv)\s+install\b",
    re.IGNORECASE,
)
_PY_BIN = frozenset({"python", "python3", "python3.10", "python3.11", "python3.12"})


def split_unquoted_pipes(command: str) -> list[str]:
    """Split on ``|`` outside single/double quotes (no nested complexity)."""
    raw = command or ""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(raw):
        ch = raw[i]
        if quote:
            buf.append(ch)
            if ch == quote and (quote == "'" or raw[i - 1 : i] != "\\"):
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "|":
            parts.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail or parts:
        parts.append(tail)
    return [p for p in parts if p]


def _strip_cd_prefix(stage: str) -> str:
    m = _CD_AND.match(stage.strip())
    if not m:
        return stage.strip()
    dest = m.group("dir").strip().strip("'\"")
    if dest in {".", "./", "/workspace", "/testbed"}:
        return stage[m.end() :].strip()
    return stage.strip()


def _strip_trailing_redirs(stage: str) -> str:
    s = stage.strip()
    while True:
        n = _REDIR_TAIL.sub("", s).strip()
        if n == s:
            return s
        s = n


def _is_view_stage(stage: str) -> bool:
    s = _strip_trailing_redirs(stage.strip())
    if not s:
        return False
    try:
        parts = shlex.split(s, posix=True)
    except ValueError:
        return False
    if not parts:
        return False
    return parts[0].rsplit("/", 1)[-1].lower() in _VIEW_HEAD


def _peel_head(command: str) -> str | None:
    raw = (command or "").strip()
    if not raw:
        return None
    stages = split_unquoted_pipes(raw)
    if not stages:
        return None
    head = _strip_trailing_redirs(_strip_cd_prefix(stages[0]))
    if not head:
        return None
    if len(stages) > 1 and not all(_is_view_stage(s) for s in stages[1:]):
        # Still allow when head alone is actionable (ignore noisy filters).
        return head
    return head


def extract_test_command_for_redirect(command: str) -> str | None:
    """Return a gate-able test command, or None if this is not a test run.

    Examples that redirect::

        python -m pytest astropy/io/ascii/tests/test_rst.py -x -q 2>&1 | tail -15
        pytest -q
        python -m pytest tests/ -q | grep FAILED

    Examples that do not (handled by env-probe redirect instead)::

        python -c "import pytest"
        pip install pytest
        ls | grep pytest
    """
    head = _peel_head(command)
    if not head:
        return None
    gated = gate_run_tests_command(head)
    if not gated.allowed or not gated.argv:
        return None
    return " ".join(gated.argv)


def extract_sweb_env_argv(command: str) -> list[str] | None:
    """Return argv to run inside sweb.eval for env probes / ``python -c``.

    Covers version / which / import checks that otherwise spuriously fail in the
    bare Work tree and trigger pip archaeology.
    """
    head = _peel_head(command)
    if not head:
        return None
    # Never treat install as an env probe.
    if is_swe_env_install_command(head):
        return None
    # Tests go through extract_test_command_for_redirect → run_tests.
    if gate_run_tests_command(head).allowed:
        return None
    try:
        parts = shlex.split(head, posix=True)
    except ValueError:
        return None
    if not parts:
        return None
    bin0 = parts[0].rsplit("/", 1)[-1].lower()

    # which python|pytest
    if bin0 == "which" and len(parts) >= 2:
        target = parts[1].rsplit("/", 1)[-1].lower()
        if target in _PY_BIN or target in {"pytest", "pip", "pip3"}:
            return parts

    # python --version / -V
    if bin0 in _PY_BIN:
        if len(parts) == 1:
            return parts
        if len(parts) == 2 and parts[1] in {"--version", "-V", "-V:"}:
            return parts
        # python -m pytest --version (gate allows full pytest; already excluded)
        if len(parts) >= 3 and parts[1] == "-m" and parts[2] == "pytest":
            # version-only or help — still ok in sweb
            return parts
        # python -c "…"
        if len(parts) >= 3 and parts[1] == "-c":
            return parts
        return None

    # bare pytest --version (gate allows pytest * → already excluded if allowed)
    if bin0 == "pytest" and any(a in {"--version", "-V"} for a in parts[1:]):
        return parts

    return None


def is_swe_env_install_command(command: str) -> bool:
    """True for pip/uv install attempts (bare-worktree env archaeology)."""
    return bool(_PIP_INSTALL.search(command or ""))


def swe_install_reject_payload(
    command: str, *, probe: dict[str, Any] | None = None
) -> dict[str, Any]:
    summary = "rejected: use run_tests / sweb.eval (deps are in the instance image)"
    stderr = (
        "SWE solve env is the pre-pulled sweb.eval image — do not pip install "
        "in the Work. Call run_tests (or pytest / python -c via run_command; "
        "they redirect into the image)."
    )
    out: dict[str, Any] = {
        "command": command,
        "status": "rejected",
        "stdout": "",
        "stderr": stderr,
        "exit_code": None,
        "summary": summary,
        "error": "swe_eval_use_run_tests",
        "redirected_from": "run_command",
    }
    if probe:
        out["solve_env_probe"] = {
            "ok": probe.get("ok"),
            "summary": probe.get("summary"),
            "image_ref": probe.get("image_ref"),
            "cached": probe.get("cached"),
        }
        if probe.get("ok"):
            out["summary"] = (
                f"{summary}; solve env probe ok — python/pytest ready in sweb.eval"
            )
    return out
