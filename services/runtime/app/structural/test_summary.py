"""Parse pytest / unittest stdout into a compact test_summary (Wave 4 W10).

Omit the field when format is uncertain — never invent failures.
Quality-uplift C-1: parse from untruncated streams; accept -q / short footers.
"""

from __future__ import annotations

import re
from typing import Any

_PYTEST_SUMMARY_RE = re.compile(
    r"=+\s*(?P<body>.+?)\s*=+\s*$",
    re.MULTILINE,
)
_PYTEST_QUIET_RE = re.compile(
    r"(?P<body>(?:\d+\s+(?:passed|failed|errors?|error|skipped|xfailed|xpassed|warnings?)"
    r"(?:,\s*)?)+)"
    r"(?:\s+in\s+[0-9.]+s)?",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(
    r"(?P<n>\d+)\s+(?P<label>passed|failed|errors?|error|skipped|xfailed|xpassed|warnings?)",
    re.IGNORECASE,
)
_FAILED_HEADER_RE = re.compile(
    r"^_{2,}\s+(?P<nodeid>\S.*?)\s+_{2,}\s*$",
    re.MULTILINE,
)
_SHORT_FAIL_RE = re.compile(
    r"^(?:FAILED|ERROR)\s+(?P<nodeid>\S+)(?:\s+-\s+(?P<rest>.+))?\s*$",
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
_DETAIL_MAX = 400
_STDOUT_FULL_KEY = "_stdout_full"
_STDERR_FULL_KEY = "_stderr_full"


def is_testish_command(command: str | None) -> bool:
    return bool(command) and _TESTISH_CMD_RE.search(command or "") is not None


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    if not text or "\x1b" not in text:
        return text
    return _ANSI_RE.sub("", text)


def parse_test_summary(
    stdout: str,
    *,
    stderr: str = "",
    max_failures: int = _FIRST_FAILURES_MAX,
) -> dict[str, Any] | None:
    """Return compact summary or None if stdout is not a recognized test report."""
    text = "\n".join(p for p in (stdout or "", stderr or "") if p)
    text = _strip_ansi(text)
    if not text.strip():
        return None

    pytest = _parse_pytest(text, max_failures=max_failures)
    if pytest is not None:
        return pytest
    return _parse_unittest(text, max_failures=max_failures)


def format_failure_feed(summary: dict[str, Any] | None) -> str | None:
    """Fixed subsection for the first failing test (C-1c) — ≤400 chars of detail."""
    if not isinstance(summary, dict):
        return None
    fails = summary.get("first_failures")
    if not isinstance(fails, list) or not fails:
        return None
    first = fails[0] if isinstance(fails[0], dict) else None
    if not first:
        return None
    name = str(first.get("name") or "").strip()
    detail = str(first.get("detail") or "").strip()[:_DETAIL_MAX]
    if not name:
        return None
    lines = [f"First failing test: {name}"]
    if detail:
        lines.append(f"  {detail}")
    return "\n".join(lines)


def _streams_for_parse(result: dict[str, Any]) -> tuple[str, str]:
    stdout = str(result.get(_STDOUT_FULL_KEY) or result.get("stdout") or "")
    stderr = str(result.get(_STDERR_FULL_KEY) or result.get("stderr") or "")
    return stdout, stderr


def _drop_full_streams(result: dict[str, Any]) -> dict[str, Any]:
    result.pop(_STDOUT_FULL_KEY, None)
    result.pop(_STDERR_FULL_KEY, None)
    return result


def _attach_parsed(result: dict[str, Any], summary: dict[str, Any] | None) -> dict[str, Any]:
    _drop_full_streams(result)
    if summary is None:
        return result
    result["test_summary"] = summary
    feed = format_failure_feed(summary)
    if feed:
        result["failure_feed"] = feed
        prev = str(result.get("summary") or "").strip()
        result["summary"] = f"{feed}\n{prev}" if prev else feed
    return result


def attach_test_summary_for_run_tests(result: dict[str, Any]) -> dict[str, Any]:
    """Always attempt parse for run_tests results (command is inherently testish)."""
    stdout, stderr = _streams_for_parse(result)
    return _attach_parsed(result, parse_test_summary(stdout, stderr=stderr))


def attach_test_summary_for_run_command(
    result: dict[str, Any],
    *,
    command: str,
) -> dict[str, Any]:
    if not is_testish_command(command):
        return _drop_full_streams(result)
    stdout, stderr = _streams_for_parse(result)
    return _attach_parsed(result, parse_test_summary(stdout, stderr=stderr))


def _counts_from_body(body: str) -> dict[str, int]:
    return {m.group("label").lower(): int(m.group("n")) for m in _COUNT_RE.finditer(body)}


def _counts_look_like_pytest(counts: dict[str, int]) -> bool:
    return bool(counts) and any(
        k in counts for k in ("passed", "failed", "error", "errors")
    )


def _summary_from_counts(
    text: str, counts: dict[str, int], *, max_failures: int
) -> dict[str, Any]:
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


def _parse_pytest(text: str, *, max_failures: int) -> dict[str, Any] | None:
    # Prefer a banner whose body actually has passed/failed/error counts.
    # Last ``=====`` line is often coverage / "short test summary info" / warnings.
    for banner in reversed(list(_PYTEST_SUMMARY_RE.finditer(text))):
        counts = _counts_from_body(banner.group("body"))
        if _counts_look_like_pytest(counts):
            return _summary_from_counts(text, counts, max_failures=max_failures)
    quiet = list(_PYTEST_QUIET_RE.finditer(text))
    if quiet:
        counts = _counts_from_body(quiet[-1].group("body"))
        if _counts_look_like_pytest(counts):
            return _summary_from_counts(text, counts, max_failures=max_failures)
    # Timeout / truncated: FAILED lines but no footer.
    # Unittest's ``FAILED (failures=N)`` must not be stolen as a pytest nodeid.
    if _UNITTEST_FAILED_LINE_RE.search(text) or _UNITTEST_FAIL_RE.search(text):
        return None
    first = _pytest_first_failures(text, max_failures=max_failures)
    if first:
        n_fail = len(first)
        return {
            "passed": 0,
            "failed": n_fail,
            "errors": 0,
            "first_failures": first,
            "provider": "pytest",
        }
    return None


def _pytest_first_failures(text: str, *, max_failures: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _FAILED_HEADER_RE.finditer(text):
        nodeid = m.group("nodeid").strip()
        if not nodeid or nodeid.lower() in {"failures", "errors", "short test summary info"}:
            continue
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
        key = nodeid[:200]
        if key in seen:
            continue
        seen.add(key)
        entry = {"name": key}
        if detail:
            entry["detail"] = detail[:_DETAIL_MAX]
        out.append(entry)
        if len(out) >= max_failures:
            return out
    for m in _SHORT_FAIL_RE.finditer(text):
        if len(out) >= max_failures:
            break
        nodeid = m.group("nodeid").strip()
        if not nodeid or nodeid in seen:
            continue
        if nodeid.startswith("("):
            continue
        seen.add(nodeid)
        entry = {"name": nodeid[:200]}
        rest = (m.group("rest") or "").strip()
        if rest:
            entry["detail"] = rest[:_DETAIL_MAX]
        out.append(entry)
    return out


def _parse_unittest(text: str, *, max_failures: int) -> dict[str, Any] | None:
    ran = _UNITTEST_RAN_RE.search(text)
    fl = _UNITTEST_FAILED_LINE_RE.search(text)
    names = [m.group("name").strip() for m in _UNITTEST_FAIL_RE.finditer(text)]
    ok = _UNITTEST_OK_RE.search(text) is not None
    if not ran and not fl and not names and not ok:
        return None

    failed = 0
    errors = 0
    if fl:
        failed = int(fl.group("f") or 0)
        errors = int(fl.group("e") or 0)
    elif ok:
        failed = 0
        errors = 0
    elif names:
        failed = len(names)
    elif ran:
        return None

    total = int(ran.group("ran")) if ran else max(failed + errors, len(names))
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
