"""Parse pytest / unittest stdout into a compact test_summary (Wave 4 W10).

Omit the field when format is uncertain — never invent failures.
"""

from __future__ import annotations

import re
from typing import Any

_PYTEST_SUMMARY_RE = re.compile(
    r"=+\s*(?P<body>.+?)\s*=+\s*$",
    re.MULTILINE,
)
_COUNT_RE = re.compile(
    r"(?P<n>\d+)\s+(?P<label>passed|failed|errors?|error|skipped|xfailed|xpassed|warnings?)",
    re.IGNORECASE,
)
_FAILED_HEADER_RE = re.compile(
    r"^_{2,}\s+(?P<nodeid>\S.*?)\s+_{2,}\s*$",
    re.MULTILINE,
)
_ASSERT_LINE_RE = re.compile(
    r"^(?:E\s+)?(?:AssertionError|assert\s+.+|.+Error:.+)$",
    re.MULTILINE,
)
_UNITTEST_FAIL_RE = re.compile(
    r"^(?:FAIL|ERROR):\s+(?P<name>\S.+)$",
    re.MULTILINE,
)
_UNITTEST_RAN_RE = re.compile(
    r"^Ran\s+(?P<ran>\d+)\s+tests?\b.*?$",
    re.MULTILINE | re.IGNORECASE,
)
_UNITTEST_OK_RE = re.compile(r"^OK\b", re.MULTILINE)
_UNITTEST_FAILED_LINE_RE = re.compile(
    r"^FAILED\s*\(.*?failures?=(?P<f>\d+).*?(?:errors?=(?P<e>\d+))?.*?\)",
    re.MULTILINE | re.IGNORECASE,
)

_TESTISH_CMD_RE = re.compile(
    r"\b(pytest|py\.test|unittest|nosetests|tox)\b|"
    r"\bpython\s+-m\s+pytest\b|"
    r"\bpython\s+-m\s+unittest\b|"
    r"\brun_tests\b",
    re.IGNORECASE,
)

_FIRST_FAILURES_MAX = 5


def is_testish_command(command: str | None) -> bool:
    return bool(command) and _TESTISH_CMD_RE.search(command or "") is not None


def parse_test_summary(
    stdout: str,
    *,
    stderr: str = "",
    max_failures: int = _FIRST_FAILURES_MAX,
) -> dict[str, Any] | None:
    """Return compact summary or None if stdout is not a recognized test report."""
    text = "\n".join(p for p in (stdout or "", stderr or "") if p)
    if not text.strip():
        return None

    pytest = _parse_pytest(text, max_failures=max_failures)
    if pytest is not None:
        return pytest
    return _parse_unittest(text, max_failures=max_failures)


def attach_test_summary_for_run_tests(result: dict[str, Any]) -> dict[str, Any]:
    """Always attempt parse for run_tests results (command is inherently testish)."""
    summary = parse_test_summary(
        str(result.get("stdout") or ""),
        stderr=str(result.get("stderr") or ""),
    )
    if summary is None:
        return result
    result["test_summary"] = summary
    return result


def attach_test_summary_for_run_command(
    result: dict[str, Any],
    *,
    command: str,
) -> dict[str, Any]:
    if not is_testish_command(command):
        return result
    summary = parse_test_summary(
        str(result.get("stdout") or ""),
        stderr=str(result.get("stderr") or ""),
    )
    if summary is None:
        return result
    result["test_summary"] = summary
    return result


def _parse_pytest(text: str, *, max_failures: int) -> dict[str, Any] | None:
    # Prefer the last ===== summary ===== line (pytest footer).
    bodies = list(_PYTEST_SUMMARY_RE.finditer(text))
    if not bodies:
        return None
    body = bodies[-1].group("body")
    # Require at least one known count label so we don't grab random ==== banners.
    counts = {m.group("label").lower(): int(m.group("n")) for m in _COUNT_RE.finditer(body)}
    if not counts:
        return None
    if not any(k in counts for k in ("passed", "failed", "error", "errors")):
        return None

    passed = int(counts.get("passed") or 0)
    failed = int(counts.get("failed") or 0)
    errors = int(counts.get("error") or counts.get("errors") or 0)
    first = _pytest_first_failures(text, max_failures=max_failures)
    out: dict[str, Any] = {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "first_failures": first,
        "provider": "pytest",
    }
    skipped = counts.get("skipped")
    if skipped is not None:
        out["skipped"] = int(skipped)
    return out


def _pytest_first_failures(text: str, *, max_failures: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in _FAILED_HEADER_RE.finditer(text):
        nodeid = m.group("nodeid").strip()
        if not nodeid or nodeid.lower() in {"failures", "errors", "short test summary info"}:
            continue
        # Slice until next failure header or short summary.
        start = m.end()
        nxt = _FAILED_HEADER_RE.search(text, start)
        end = nxt.start() if nxt else len(text)
        chunk = text[start:end]
        detail = ""
        am = _ASSERT_LINE_RE.search(chunk)
        if am:
            detail = am.group(0).strip()
            if detail.startswith("E "):
                detail = detail[2:].strip()
        entry = {"name": nodeid[:200]}
        if detail:
            entry["detail"] = detail[:200]
        out.append(entry)
        if len(out) >= max_failures:
            break
    return out


def _parse_unittest(text: str, *, max_failures: int) -> dict[str, Any] | None:
    ran = _UNITTEST_RAN_RE.search(text)
    if not ran:
        return None
    total = int(ran.group("ran"))
    failed = 0
    errors = 0
    fl = _UNITTEST_FAILED_LINE_RE.search(text)
    if fl:
        failed = int(fl.group("f") or 0)
        errors = int(fl.group("e") or 0)
    elif _UNITTEST_OK_RE.search(text):
        failed = 0
        errors = 0
    else:
        # FAIL/ERROR headers present without FAILED(...) line.
        names = [m.group("name").strip() for m in _UNITTEST_FAIL_RE.finditer(text)]
        if not names and total > 0:
            # Ambiguous — omit rather than invent.
            return None
        failed = len(names)

    first: list[dict[str, str]] = []
    for m in _UNITTEST_FAIL_RE.finditer(text):
        first.append({"name": m.group("name").strip()[:200]})
        if len(first) >= max_failures:
            break

    passed = max(0, total - failed - errors)
    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "first_failures": first,
        "provider": "unittest",
    }
