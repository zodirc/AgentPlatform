"""常驻 ruff。优先复用一次拉起的 `ruff server`，失败则退回单次 `ruff check`。"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

_lock = asyncio.Lock()
_proc: asyncio.subprocess.Process | None = None
_disabled = False
_seq = 0


async def ruff_concise(paths: list[str], *, cwd: Path, timeout_s: float) -> str:
    """对若干相对路径返回 concise 文本。一条进程覆盖全部路径。"""
    rels = [path for path in paths if path]
    if not rels:
        return ""
    async with _lock:
        if not _disabled:
            try:
                text = await asyncio.wait_for(_via_server(rels, cwd=cwd), timeout=min(timeout_s, 8.0))
                if text is not None:
                    return text
            except Exception:
                await _stop()
        return await _via_check(rels, cwd=cwd, timeout_s=timeout_s)


async def _via_check(rels: list[str], *, cwd: Path, timeout_s: float) -> str:
    binary = shutil.which("ruff")
    argv = [binary or "python", *(["check"] if binary else ["-m", "ruff", "check"]), *rels, "--output-format", "concise"]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        return ""
    return (stdout + b"\n" + stderr).decode("utf-8", errors="replace")


async def _via_server(rels: list[str], *, cwd: Path) -> str | None:
    global _proc, _disabled, _seq
    if shutil.which("ruff") is None:
        _disabled = True
        return None
    if _proc is None or _proc.returncode is not None:
        _proc = await asyncio.create_subprocess_exec(
            "ruff",
            "server",
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        init = await _request(
            "initialize",
            {"processId": None, "rootUri": cwd.as_uri(), "capabilities": {"textDocument": {"diagnostic": {}}}},
        )
        if init is None:
            _disabled = True
            await _stop()
            return None
        await _notify("initialized", {})
    lines: list[str] = []
    for rel in rels:
        target = cwd / rel
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        uri = target.resolve().as_uri()
        await _notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": text[:200_000]}},
        )
        diag = await _request("textDocument/diagnostic", {"textDocument": {"uri": uri}})
        items = []
        if isinstance(diag, dict):
            items = list(diag.get("items") or [])
        if not items and isinstance(diag, dict) and diag.get("error"):
            _disabled = True
            await _stop()
            return None
        for item in items:
            rng = (item.get("range") or {}).get("start") or {}
            line = int(rng.get("line") or 0) + 1
            col = int(rng.get("character") or 0) + 1
            code = item.get("code") or ""
            message = str(item.get("message") or "").splitlines()[0][:180]
            lines.append(f"{rel}:{line}:{col}: {code} {message}".strip())
    return "\n".join(lines)


async def _request(method: str, params: dict) -> dict | None:
    global _seq
    _seq += 1
    number = _seq
    await _send({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
    while True:
        message = await _read()
        if message is None:
            return None
        if message.get("id") == number:
            if "error" in message:
                return {"error": message["error"]}
            result = message.get("result")
            return result if isinstance(result, dict) else {"result": result}


async def _notify(method: str, params: dict) -> None:
    await _send({"jsonrpc": "2.0", "method": method, "params": params})


async def _send(payload: dict) -> None:
    if _proc is None or _proc.stdin is None:
        return
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    _proc.stdin.write(header + body)
    await _proc.stdin.drain()


async def _read() -> dict | None:
    if _proc is None or _proc.stdout is None:
        return None
    header = await _proc.stdout.readuntil(b"\r\n\r\n")
    length = 0
    for line in header.decode("ascii", errors="replace").splitlines():
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip() or "0")
    if length <= 0:
        return None
    body = await _proc.stdout.readexactly(length)
    parsed = json.loads(body.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else None


async def _stop() -> None:
    global _proc
    proc = _proc
    _proc = None
    if proc is None:
        return
    if proc.returncode is None:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            return
