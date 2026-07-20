from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# High-confidence secret patterns only (docs/13 S2 A16). Keep the set small so
# normal prose stays under the sync budget.
_SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("openai_api_key", r"\bsk-[A-Za-z0-9]{20,}\b"),
    (
        "private_key",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    ),
    ("github_pat", r"\bghp_[A-Za-z0-9]{36}\b"),
    ("github_oauth", r"\bgho_[A-Za-z0-9]{36}\b"),
)

_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in _SECRET_PATTERNS)

_CHUNK = 48_000
_OVERLAP = 256


@dataclass(frozen=True)
class SecretScanResult:
    findings: tuple[str, ...]
    timed_out: bool
    elapsed_ms: float

    @property
    def blocked(self) -> bool:
        return bool(self.findings) and not self.timed_out


def scan_text_for_secrets(text: str, *, timeout_ms: float) -> SecretScanResult:
    """Synchronous scan with a hard wall-clock budget.

    On timeout: return empty findings + timed_out=True (caller may allow write
    and schedule an async rescan). Matches found within budget block the write.
    """
    start = time.perf_counter()
    deadline = start + max(0.0, timeout_ms) / 1000.0
    if not text:
        return SecretScanResult((), False, (time.perf_counter() - start) * 1000.0)

    found: list[str] = []
    length = len(text)
    offset = 0
    while offset < length:
        if time.perf_counter() >= deadline:
            return SecretScanResult(
                tuple(found),
                True,
                (time.perf_counter() - start) * 1000.0,
            )
        end = min(offset + _CHUNK, length)
        chunk = text[offset:end]
        for name, pattern in _COMPILED:
            if pattern.search(chunk):
                if name not in found:
                    found.append(name)
        if end >= length:
            break
        offset = max(0, end - _OVERLAP)

    return SecretScanResult(
        tuple(found),
        False,
        (time.perf_counter() - start) * 1000.0,
    )


def _async_rescan(text: str, *, path: str) -> None:
    result = scan_text_for_secrets(text, timeout_ms=5_000.0)
    if result.findings:
        logger.warning(
            "secret_scan_async_hit path=%s findings=%s elapsed_ms=%.1f",
            path,
            ",".join(result.findings),
            result.elapsed_ms,
        )
        try:
            from app.observability.metrics import metrics

            metrics.inc("secret_scan_async_hit", findings=",".join(result.findings))
        except Exception:
            pass


def gate_write_content(content: str, *, path: str) -> dict | None:
    """Return an error payload if the write should be blocked; else None.

    Timeout → allow write, log, and fire async rescan (non-blocking).
    """
    from app.settings import settings

    if not settings.secret_scan_enabled:
        return None

    result = scan_text_for_secrets(
        content, timeout_ms=float(settings.secret_scan_timeout_ms)
    )
    if result.timed_out:
        logger.warning(
            "secret_scan_timeout path=%s elapsed_ms=%.1f budget_ms=%s; allowing write",
            path,
            result.elapsed_ms,
            settings.secret_scan_timeout_ms,
        )
        try:
            from app.observability.metrics import metrics

            metrics.inc("secret_scan_timeout")
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, lambda: _async_rescan(content, path=path))
        except RuntimeError:
            _async_rescan(content, path=path)
        return None

    if result.findings:
        try:
            from app.observability.metrics import metrics

            metrics.inc("secret_scan_blocked", findings=",".join(result.findings))
        except Exception:
            pass
        return {
            "error": "secret_scan_blocked",
            "path": path,
            "secret_findings": list(result.findings),
            "status": "blocked",
            "summary": (
                f"Write blocked: potential secret(s) detected "
                f"({', '.join(result.findings)})"
            ),
        }
    return None
