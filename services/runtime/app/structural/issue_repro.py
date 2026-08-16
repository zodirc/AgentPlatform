"""Extract issue-behavior repro hints from problem.md (no gold F2P leakage).

General rules (not SWE-instance special cases):
- Prefer examples written in the issue (fences / quoted commands / REPL / I/O calls).
- After a code edit, a successful command must cover those examples (asset coverage).
- If the issue shows a failure signature, a clearing repro must not still emit it.
- Table/ascii write with format kwargs → require write→read round-trip (same format/kwargs).
- Explicit case-insensitivity claims → also exercise a casefolded variant of issue samples.
- Do not invent inputs the issue never showed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_PROBLEM_NAMES = ("problem.md", "PROBLEM.md", "issue.md")
_FENCE_RE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL)
_QUOTED_CMD_RE = re.compile(
    r'["\']((?:read|write|SELECT|INSERT)\s+[^"\']{2,80})["\']',
    re.IGNORECASE,
)
_TABLE_READ_RE = re.compile(
    r"(?:Q?Table|Table)\.read\s*\(\s*['\"]([^'\"]+)['\"].*?format\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE | re.DOTALL,
)
_TABLE_WRITE_RE = re.compile(
    r"\.write\s*\([^;]*?format\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE | re.DOTALL,
)
_HEADER_ROWS_RE = re.compile(r"header_rows\s*=", re.IGNORECASE)
_REPL_RE = re.compile(r"^>>>\s*(.+)$", re.MULTILINE)
_ERROR_LINE_RE = re.compile(
    r"^((?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*(?:Error|Exception|Warning)):\s*(.+)$",
    re.MULTILINE,
)
_RAISES_RE = re.compile(
    r"\braises?\s+((?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*(?:Error|Exception))",
    re.IGNORECASE,
)
_EXPECT_HDR_RE = re.compile(
    r"(?im)^(?:#{1,3}\s*)?(?:expected(?:\s+behavior)?|expected\s+result)\s*$"
)
_HEADING_RE = re.compile(r"(?m)^#{1,3}\s+\S")
# File/format-level case claims (not "HTTP headers are case-insensitive" alone).
_CASEFOLD_CLAIM_RE = re.compile(
    r"(?:"
    r"not\s+case\s+sensitive"
    r"|case\s*[- ]?insensitive"
    r"|case\s+sensitive"
    r"|assumes?\s+(?:that\s+)?(?:\w+\s+){0,6}upper\s*case"
    r"|upper\s*case[^\n.]{0,40}assum"
    r"|all[- ]caps"
    r"|commands?\s+(?:are|must\s+be)\s+upper"
    r")",
    re.IGNORECASE,
)
_ASCII_FORMAT_RE = re.compile(r"ascii\.\w+", re.IGNORECASE)
_MAX_COMMANDS = 4
_MAX_MARKERS = 8
_MAX_REQUIRED = 6
_MAX_ASSETS = 2
_MAX_SIGNALS = 6
_MAX_FENCE_CHARS = 400
_MIN_ASSET_CHARS = 8


def load_problem_text(work_root: Path | str | None) -> str:
    if work_root is None:
        return ""
    root = Path(work_root)
    for name in _PROBLEM_NAMES:
        path = root / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
    return ""


def extract_issue_repro_hints(problem_text: str) -> dict[str, Any]:
    """Return hints derived only from issue/problem text."""
    text = (problem_text or "").strip()
    empty = {
        "commands": [],
        "markers": [],
        "required_tokens": [],
        "assets": [],
        "casefold_assets": [],
        "fail_signals": [],
        "expect_signals": [],
        "need_roundtrip": False,
        "need_casefold": False,
        "roundtrip_formats": [],
        "roundtrip_kwargs": [],
        "summary": "",
    }
    if not text:
        return empty

    markers: list[str] = []
    commands: list[str] = []
    required: list[str] = []
    assets: list[str] = []

    fences = [m.group(1).strip() for m in _FENCE_RE.finditer(text)]
    data_fences = [_normalize_fence(f) for f in fences if _looks_like_data_file(f)]
    data_fences = [f for f in data_fences if f]

    read_formats = [
        (m.group(2) or "").strip()
        for m in _TABLE_READ_RE.finditer(text)
        if (m.group(2) or "").strip()
    ]
    write_formats = [
        (m.group(1) or "").strip()
        for m in _TABLE_WRITE_RE.finditer(text)
        if (m.group(1) or "").strip()
    ]
    formats = list(dict.fromkeys([*read_formats, *write_formats]))
    read_names = [
        (m.group(1) or "").strip()
        for m in _TABLE_READ_RE.finditer(text)
        if (m.group(1) or "").strip()
    ]

    for fence in data_fences[:_MAX_ASSETS]:
        _add_unique(assets, fence)
        for line in fence.splitlines():
            s = line.strip()
            if s and not s.startswith((">", ">>>", "...", "#", "$")):
                if _looks_like_marker_line(s):
                    tok = s[:80].lower()
                    _add_unique(markers, tok)
                    _add_unique(required, tok)

    for m in _QUOTED_CMD_RE.finditer(text):
        tok = m.group(1).strip().lower()[:80]
        _add_unique(markers, tok)
        _add_unique(required, tok)

    for fmt in formats:
        _add_unique(markers, fmt.lower())

    roundtrip_kwargs: list[str] = []
    if _HEADER_ROWS_RE.search(text):
        _add_unique(roundtrip_kwargs, "header_rows")
        _add_unique(markers, "header_rows")
        _add_unique(required, "header_rows")

    need_roundtrip = _should_require_roundtrip(text, write_formats, read_formats, roundtrip_kwargs)
    need_casefold = bool(_CASEFOLD_CLAIM_RE.search(text))

    casefold_assets: list[str] = []
    if need_casefold:
        for asset in assets:
            folded = _casefold_issue_sample(asset)
            if folded and folded != asset:
                _add_unique(casefold_assets, folded)

    repl_lines = _extract_repl_lines(text)
    commands.extend(
        _suggest_commands(
            data_fences,
            formats,
            read_names,
            repl_lines,
            need_roundtrip=need_roundtrip,
            roundtrip_kwargs=roundtrip_kwargs,
            need_casefold=need_casefold,
            casefold_assets=casefold_assets,
        )
    )

    fail_signals = _extract_fail_signals(text)
    expect_signals = _extract_expect_signals(text)

    if assets and len(required) > 3:
        required = required[:3]

    if not required and markers:
        _add_unique(required, markers[0])

    markers = markers[:_MAX_MARKERS]
    required = required[:_MAX_REQUIRED]
    commands = commands[:_MAX_COMMANDS]
    assets = assets[:_MAX_ASSETS]
    casefold_assets = casefold_assets[:_MAX_ASSETS]
    fail_signals = fail_signals[:_MAX_SIGNALS]
    expect_signals = expect_signals[:_MAX_SIGNALS]
    roundtrip_formats = [f for f in formats if f][:4]

    summary_parts: list[str] = []
    if need_roundtrip:
        summary_parts.append("round-trip write→read")
    if need_casefold:
        summary_parts.append("casefold sample")
    if assets:
        summary_parts.append(f"asset ({len(assets[0])} chars)")
    elif required:
        summary_parts.append(f"tokens: {', '.join(required[:3])}")
    if fail_signals:
        summary_parts.append(f"clear: {fail_signals[0][:40]}")

    return {
        "commands": commands,
        "markers": markers,
        "required_tokens": required,
        "assets": assets,
        "casefold_assets": casefold_assets,
        "fail_signals": fail_signals,
        "expect_signals": expect_signals,
        "need_roundtrip": need_roundtrip,
        "need_casefold": need_casefold,
        "roundtrip_formats": roundtrip_formats,
        "roundtrip_kwargs": roundtrip_kwargs[:4],
        "summary": "; ".join(summary_parts),
    }


def command_matches_issue_repro(
    command: str,
    markers: list[str],
    required_tokens: list[str] | None = None,
    *,
    assets: list[str] | None = None,
) -> bool:
    """True when the tool command covers issue sample assets/tokens."""
    cmd = (command or "").strip()
    if not cmd:
        return False
    cmd_l = cmd.lower()
    asset_list = [a for a in (assets or []) if a and str(a).strip()]
    if asset_list:
        if _looks_like_repo_pytest(cmd_l):
            return False
        return any(_asset_covered_by_command(a, cmd) for a in asset_list)

    req = [t.lower() for t in (required_tokens or []) if t and str(t).strip()]
    if req:
        if _looks_like_repo_pytest(cmd_l):
            return False
        return all(_token_in_command(t, cmd_l) for t in req)
    if not markers:
        return False
    if _looks_like_repo_pytest(cmd_l) and not any(
        _token_in_command(m, cmd_l) for m in markers if m
    ):
        return False
    return any(m and _token_in_command(m, cmd_l) for m in markers)


def command_matches_roundtrip(
    command: str,
    *,
    formats: list[str] | None = None,
    kwargs: list[str] | None = None,
) -> bool:
    """True when command exercises both write and read for the issue format/kwargs."""
    cmd = (command or "").strip()
    if not cmd or _looks_like_repo_pytest(cmd.lower()):
        return False
    c = cmd.lower()
    has_write = bool(re.search(r"\.write\s*\(|\bwrite\s*\(", c))
    has_read = bool(re.search(r"\.read\s*\(|\bread\s*\(", c))
    if not (has_write and has_read):
        return False
    fmts = [f.lower() for f in (formats or []) if f]
    kws = [k.lower() for k in (kwargs or []) if k]
    if kws and not all(k in c for k in kws):
        return False
    if fmts and not any(f in c for f in fmts):
        # Allow if an ascii.* format string appears at all.
        if not _ASCII_FORMAT_RE.search(c):
            return False
    return True


def command_matches_casefold(
    command: str,
    *,
    casefold_assets: list[str] | None = None,
    base_assets: list[str] | None = None,
) -> bool:
    """True when command covers a casefolded issue sample or applies a fold transform."""
    cmd = (command or "").strip()
    if not cmd or _looks_like_repo_pytest(cmd.lower()):
        return False
    folded = [a for a in (casefold_assets or []) if a and str(a).strip()]
    if folded:
        return any(_asset_covered_by_command(a, cmd) for a in folded)
    c = cmd.lower()
    transform = bool(
        re.search(r"\.lower\s*\(|\.casefold\s*\(|\blowercase\b|\bcasefold\b", c)
    )
    if not transform:
        return False
    bases = [a for a in (base_assets or []) if a and str(a).strip()]
    if bases:
        return any(_asset_covered_by_command(a, cmd) for a in bases)
    # Claim-only with no data fence: transform marker is the signal.
    return True


def obligations_met_for_command(
    command: str,
    hints: dict[str, Any],
) -> bool:
    """Whether one command covers base sample plus optional round-trip / casefold."""
    markers = list(hints.get("markers") or [])
    required = list(hints.get("required_tokens") or [])
    assets = list(hints.get("assets") or [])
    need_rt = bool(hints.get("need_roundtrip"))
    need_cf = bool(hints.get("need_casefold"))

    base_ok = False
    if assets or required or markers:
        base_ok = command_matches_issue_repro(
            command, markers, required_tokens=required, assets=assets
        )
    elif need_rt or need_cf:
        # Write-only issues may lack data fences; round-trip / casefold can stand alone.
        base_ok = True
    else:
        return False

    if not base_ok and need_rt:
        # Round-trip command that includes header_rows / format may omit raw fence text.
        base_ok = command_matches_roundtrip(
            command,
            formats=list(hints.get("roundtrip_formats") or []),
            kwargs=list(hints.get("roundtrip_kwargs") or []),
        )

    if not base_ok:
        return False

    if need_rt and not command_matches_roundtrip(
        command,
        formats=list(hints.get("roundtrip_formats") or []),
        kwargs=list(hints.get("roundtrip_kwargs") or []),
    ):
        return False

    if need_cf and not command_matches_casefold(
        command,
        casefold_assets=list(hints.get("casefold_assets") or []),
        base_assets=assets,
    ):
        return False

    return True


def is_successful_repro_result(result: dict[str, Any]) -> bool:
    """True only when the repro command actually succeeded."""
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").lower()
    if status in {"rejected", "error", "failed", "cancelled"}:
        return False
    summary = str(result.get("summary") or "")
    sm = summary.lower()
    if "sweb.eval failed" in sm or sm.strip().startswith("exit 1"):
        return False
    if re.search(r"\bexit\s+1\b|\bexit_code[=:]?\s*1\b", sm):
        return False
    code = result.get("exit_code")
    if code is not None and int(code) != 0:
        return False
    if status in {"passed", "executed", "ok", "completed"}:
        return True
    if code is not None and int(code) == 0:
        return True
    return False


def is_clearing_repro_result(
    result: dict[str, Any],
    *,
    fail_signals: list[str] | None = None,
    expect_signals: list[str] | None = None,
) -> bool:
    """Successful exit, and issue failure text must not still appear in output."""
    del expect_signals
    if not is_successful_repro_result(result):
        return False
    fails = [s for s in (fail_signals or []) if s and str(s).strip()]
    blob = _normalize_for_match(_result_blob(result))
    for sig in fails:
        s = _normalize_for_match(sig)
        if len(s) >= 5 and s in blob:
            return False
    return True


def is_green_test_result(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "")
    if status in {"rejected", "error", "failed", "cancelled"}:
        return False
    if status not in {"passed", "executed", "ok", "completed"}:
        if result.get("exit_code") is None and status:
            return False
    code = result.get("exit_code")
    if code is not None and int(code) != 0:
        return False
    summary = result.get("test_summary")
    if isinstance(summary, dict):
        if int(summary.get("failed") or 0) > 0:
            return False
        if int(summary.get("errors") or 0) > 0:
            return False
    sm = str(result.get("summary") or "").lower()
    if "sweb.eval failed" in sm:
        return False
    return True


def _should_require_roundtrip(
    text: str,
    write_formats: list[str],
    read_formats: list[str],
    roundtrip_kwargs: list[str],
) -> bool:
    """Require write→read when the issue demonstrates table/ascii write with options."""
    if not write_formats and not roundtrip_kwargs:
        return False
    # Pure docs / display-only: skip if no write call and no header_rows.
    if not re.search(r"\.write\s*\(", text):
        return bool(roundtrip_kwargs) and bool(_ASCII_FORMAT_RE.search(text))
    # New write kwargs (header_rows) or ascii.* writer shown in issue.
    if roundtrip_kwargs:
        return True
    if any(_ASCII_FORMAT_RE.search(f) or f.lower().startswith("ascii.") for f in write_formats):
        return True
    # Write + read of same family already in issue → still enforce post-edit round-trip.
    if write_formats and read_formats:
        return True
    return False


def _casefold_issue_sample(asset: str) -> str:
    """Lowercase non-comment lines of an issue sample (format/file-level claim)."""
    lines: list[str] = []
    for raw in (asset or "").splitlines():
        if raw.lstrip().startswith("!"):
            lines.append(raw)
        else:
            lines.append(raw.lower())
    return "\n".join(lines).strip()


def _suggest_commands(
    data_fences: list[str],
    formats: list[str],
    read_names: list[str],
    repl_lines: list[str],
    *,
    need_roundtrip: bool = False,
    roundtrip_kwargs: list[str] | None = None,
    need_casefold: bool = False,
    casefold_assets: list[str] | None = None,
) -> list[str]:
    """Build suggested repros only from pieces already present in the issue."""
    out: list[str] = []
    kwargs = list(roundtrip_kwargs or [])
    fmt = formats[0] if formats else ""

    if need_roundtrip and fmt:
        out.append(
            f"# round-trip required: write then read with format={fmt!r}"
            + (f" and {', '.join(kwargs)}" if kwargs else "")
            + " using the issue's own example table/bytes (do not skip read-back)"
        )
        write_line = next(
            (r for r in repl_lines if ".write(" in r and "format" in r.lower()),
            "",
        )
        if write_line:
            _add_unique(out, write_line)
            out.append(
                f"# then: Table.read(<same output>, format={fmt!r}"
                + (f", {kwargs[0]}=..." if kwargs else "")
                + ")"
            )

    if data_fences:
        body = data_fences[0]
        fname = read_names[0] if read_names else "_issue_sample.txt"
        shown = body if len(body) <= 240 else body[:240] + "\n..."
        write_hint = f"open({fname!r},'w').write({shown!r})"
        imports = [r for r in repl_lines if r.startswith(("from ", "import "))]
        call = next((r for r in repl_lines if "Table.read" in r or ".read(" in r), "")
        if call:
            call_adj = re.sub(
                r"(?:Q?Table|Table)\.read\s*\(\s*['\"][^'\"]+['\"]",
                f"Table.read({fname!r}",
                call,
                count=1,
            )
            prelude = "; ".join(imports[:2])
            bits = [write_hint]
            if prelude:
                bits.append(prelude)
            bits.append(call_adj)
            out.append("python -c \"" + "; ".join(bits) + "\"")
        elif fmt:
            out.append(
                f"# write issue sample to {fname}, then invoke the read(..., format={fmt!r}) from the issue"
            )
            out.append(write_hint)
        else:
            out.append(write_hint)

    if need_casefold:
        folded = (casefold_assets or [None])[0]
        if folded:
            shown = folded if len(folded) <= 200 else folded[:200] + "\n..."
            out.append(
                f"# casefold claim: also read this lowercased issue sample:\n{shown}"
            )
        else:
            out.append(
                "# casefold claim: after a working sample, apply .lower() to every "
                "non-comment line of the same file contents and read again"
            )

    for line in repl_lines[:2]:
        if ".read(" in line or ".write(" in line or line.startswith(("read ", "write ", "SELECT ")):
            _add_unique(out, line)
    return out


def _extract_repl_lines(text: str) -> list[str]:
    lines: list[str] = []
    for m in _REPL_RE.finditer(text or ""):
        s = (m.group(1) or "").strip()
        if not s or s.startswith(("...", "#")):
            continue
        if "Traceback" in s or s.endswith("Error:"):
            break
        _add_unique(lines, s)
        if len(lines) >= 8:
            break
    return lines


def _extract_fail_signals(text: str) -> list[str]:
    out: list[str] = []
    for m in _ERROR_LINE_RE.finditer(text or ""):
        etype = (m.group(1) or "").strip()
        msg = (m.group(2) or "").strip()
        if not etype:
            continue
        if msg and len(msg) >= 8:
            _add_unique(out, f"{etype}: {msg}"[:120])
        else:
            _add_unique(out, etype)
    for m in _RAISES_RE.finditer(text or ""):
        _add_unique(out, (m.group(1) or "").strip())
    return out[:_MAX_SIGNALS]


def _extract_expect_signals(text: str) -> list[str]:
    out: list[str] = []
    for m in _EXPECT_HDR_RE.finditer(text or ""):
        start = m.end()
        rest = text[start:]
        end_m = _HEADING_RE.search(rest)
        block = rest[: end_m.start()] if end_m else rest[:600]
        for fm in _FENCE_RE.finditer(block):
            body = _normalize_fence(fm.group(1) or "")
            if body and len(body) >= 3:
                _add_unique(out, body.splitlines()[0].strip()[:80])
        for line in block.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if _looks_like_marker_line(s) and len(s) <= 80:
                _add_unique(out, s)
            if len(out) >= _MAX_SIGNALS:
                break
    return out[:_MAX_SIGNALS]


def _asset_covered_by_command(asset: str, command: str) -> bool:
    a = _normalize_for_match(asset)
    c = _normalize_for_match(command)
    if len(a) < _MIN_ASSET_CHARS:
        return bool(a) and a in c
    if a in c:
        return True
    if a[: min(60, len(a))] in c:
        return True
    lines = [
        _normalize_for_match(ln)
        for ln in asset.splitlines()
        if _looks_like_marker_line(ln.strip())
        or (ln.strip() and not ln.strip().startswith((">", "#", "$")))
    ]
    lines = [ln for ln in lines if len(ln) >= 3][:6]
    if not lines:
        return False
    return all(ln in c for ln in lines)


def _normalize_for_match(text: str) -> str:
    s = (text or "").lower()
    s = s.replace("\\n", " ").replace("\\t", " ")
    s = s.replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def _result_blob(result: dict[str, Any]) -> str:
    parts = [
        str(result.get("summary") or ""),
        str(result.get("stdout") or ""),
        str(result.get("stderr") or ""),
        str(result.get("error") or ""),
    ]
    return "\n".join(parts)


def _token_in_command(token: str, cmd: str) -> bool:
    t = (token or "").lower()
    if not t:
        return False
    if len(t) <= 2:
        return re.search(rf"(^|[^a-z0-9_]){re.escape(t)}([^a-z0-9_]|$)", cmd) is not None
    return t in cmd


def _add_unique(items: list[str], value: str) -> None:
    v = (value or "").strip()
    if not v or v in items:
        return
    items.append(v)


def _normalize_fence(fence: str) -> str:
    lines: list[str] = []
    for raw in fence.splitlines():
        line = raw.rstrip()
        if line.startswith((">>>", "...", "$ ", "> ")):
            continue
        if line.startswith(">cat") or line.startswith("> cat"):
            continue
        if line in {"<EOF>", "EOF"}:
            continue
        if "Traceback" in line or line.startswith("ValueError:"):
            break
        lines.append(line)
    body = "\n".join(lines).strip()
    return body[:_MAX_FENCE_CHARS]


def _looks_like_data_file(fence: str) -> bool:
    body = fence.strip()
    if not body or len(body) > _MAX_FENCE_CHARS:
        return False
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines or len(lines) > 40:
        return False
    if any(ln.lstrip().startswith(("def ", "class ", "import ", "from ")) for ln in lines):
        return False
    if sum(1 for ln in lines if ln.strip().startswith(">>>")) >= 2:
        return False
    return True


def _looks_like_marker_line(line: str) -> bool:
    s = line.strip()
    if len(s) < 3 or len(s) > 80:
        return False
    if re.match(r"^[\d.\seE+-]+$", s):
        return False
    return bool(re.search(r"[A-Za-z]", s))


def _looks_like_repo_pytest(cmd: str) -> bool:
    return bool(
        re.search(r"\bpytest\b|\bpy\.test\b|\bunittest\b|\bpython\s+-m\s+pytest\b", cmd)
    )
