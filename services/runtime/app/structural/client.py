from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url

from app.structural.providers import ProviderSpec, initialization_options
from app.tools.core.shell import _safe_env

logger = logging.getLogger(__name__)


def path_to_uri(path: Path) -> str:
    resolved = path.resolve()
    return "file://" + pathname2url(str(resolved))


def uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return uri
    return unquote(parsed.path)


class LspSession:
    """Thin JSON-RPC LSP client over stdio (initialize / didOpen / query / shutdown)."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        provider: ProviderSpec,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.provider = provider
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._diagnostics: dict[str, list[dict[str, Any]]] = {}
        self._diag_events: dict[str, asyncio.Event] = {}
        self._next_id = 1
        self._write_lock = asyncio.Lock()
        self._opened: set[str] = set()
        self._healthy = False
        self._cold_start = True
        self._supports_pull_diagnostic = False
        self._buffer = bytearray()

    @property
    def healthy(self) -> bool:
        return self._healthy and self._proc is not None and self._proc.returncode is None

    @property
    def cold_start(self) -> bool:
        return self._cold_start

    async def start(self, *, timeout_s: float) -> None:
        env = _safe_env()
        env["HOME"] = str(self.workspace_root)
        env["PWD"] = str(self.workspace_root)
        self._proc = await asyncio.create_subprocess_exec(
            *self.provider.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workspace_root),
            env=env,
            start_new_session=True,
        )
        assert self._proc.stdout is not None
        self._reader_task = asyncio.create_task(self._read_loop())
        try:
            result = await asyncio.wait_for(
                self.request(
                    "initialize",
                    {
                        "processId": None,
                        "rootUri": path_to_uri(self.workspace_root),
                        "rootPath": str(self.workspace_root),
                        "capabilities": {
                            "textDocument": {
                                "publishDiagnostics": {"relatedInformation": False},
                                "diagnostic": {"dynamicRegistration": False},
                                "definition": {"linkSupport": False},
                                "references": {},
                                "documentSymbol": {
                                    "hierarchicalDocumentSymbolSupport": True,
                                },
                            },
                            "workspace": {
                                "symbol": {},
                                "configuration": True,
                            },
                        },
                        "initializationOptions": initialization_options(self.provider.name),
                        "workspaceFolders": [
                            {
                                "uri": path_to_uri(self.workspace_root),
                                "name": self.workspace_root.name,
                            }
                        ],
                    },
                ),
                timeout=timeout_s,
            )
        except Exception:
            await self.shutdown()
            raise

        caps = (result or {}).get("capabilities") or {}
        self._supports_pull_diagnostic = "diagnosticProvider" in caps
        await self.notify("initialized", {})
        self._healthy = True

    async def shutdown(self) -> None:
        self._healthy = False
        if self._proc is None:
            return
        try:
            if self._proc.returncode is None:
                with_context = True
                try:
                    await asyncio.wait_for(self.request("shutdown", None), timeout=2.0)
                    await self.notify("exit", None)
                except Exception:
                    with_context = False
                if not with_context and self._proc.returncode is None:
                    self._proc.kill()
        finally:
            if self._reader_task is not None:
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except (asyncio.CancelledError, Exception):
                    pass
            if self._proc.returncode is None:
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except Exception:
                pass
            self._proc = None
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("LSP session closed"))
            self._pending.clear()

    async def ensure_open(self, path: Path, *, language_id: str = "python") -> None:
        abs_path = path.resolve()
        uri = path_to_uri(abs_path)
        text = abs_path.read_text(encoding="utf-8", errors="replace")
        if uri in self._opened:
            await self.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": 2},
                    "contentChanges": [{"text": text}],
                },
            )
            return
        await self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 1,
                    "text": text,
                }
            },
        )
        self._opened.add(uri)
        self._diag_events.setdefault(uri, asyncio.Event())

    async def diagnostics_for(
        self,
        path: Path,
        *,
        timeout_s: float,
        language_id: str = "python",
    ) -> list[dict[str, Any]]:
        abs_path = path.resolve()
        uri = path_to_uri(abs_path)
        await self.ensure_open(abs_path, language_id=language_id)
        if self._supports_pull_diagnostic:
            try:
                result = await asyncio.wait_for(
                    self.request(
                        "textDocument/diagnostic",
                        {"textDocument": {"uri": uri}},
                    ),
                    timeout=timeout_s,
                )
                self._cold_start = False
                items = (result or {}).get("items") or []
                return list(items)
            except Exception as exc:
                logger.debug("pull diagnostic failed, falling back to push: %s", exc)

        event = self._diag_events.setdefault(uri, asyncio.Event())
        event.clear()
        # Re-open nudge for servers that only push on open/change.
        await self.ensure_open(abs_path, language_id=language_id)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            # Return whatever we have (may be empty).
            pass
        self._cold_start = False
        return list(self._diagnostics.get(uri, []))

    async def workspace_symbols(self, query: str, *, timeout_s: float) -> list[dict[str, Any]]:
        result = await asyncio.wait_for(
            self.request("workspace/symbol", {"query": query}),
            timeout=timeout_s,
        )
        self._cold_start = False
        return list(result or [])

    async def definition(
        self,
        path: Path,
        line: int,
        col: int,
        *,
        timeout_s: float,
        language_id: str = "python",
    ) -> list[dict[str, Any]]:
        await self.ensure_open(path, language_id=language_id)
        uri = path_to_uri(path.resolve())
        result = await asyncio.wait_for(
            self.request(
                "textDocument/definition",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": max(0, line - 1), "character": max(0, col - 1)},
                },
            ),
            timeout=timeout_s,
        )
        self._cold_start = False
        return _as_location_list(result)

    async def references(
        self,
        path: Path,
        line: int,
        col: int,
        *,
        timeout_s: float,
        language_id: str = "python",
        include_declaration: bool = True,
    ) -> list[dict[str, Any]]:
        await self.ensure_open(path, language_id=language_id)
        uri = path_to_uri(path.resolve())
        result = await asyncio.wait_for(
            self.request(
                "textDocument/references",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": max(0, line - 1), "character": max(0, col - 1)},
                    "context": {"includeDeclaration": include_declaration},
                },
            ),
            timeout=timeout_s,
        )
        self._cold_start = False
        return _as_location_list(result)

    async def request(self, method: str, params: Any) -> Any:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("LSP process not running")
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = fut
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return await fut

    async def notify(self, method: str, params: Any) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, message: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("LSP process not running")
        body = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        async with self._write_lock:
            self._proc.stdin.write(header + body)
            await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    break
                self._buffer.extend(chunk)
                while True:
                    msg = self._pop_message()
                    if msg is None:
                        break
                    self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("LSP read loop ended: %s", exc)
            self._healthy = False
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("LSP stdout closed"))
            self._pending.clear()

    def _pop_message(self) -> dict[str, Any] | None:
        sep = self._buffer.find(b"\r\n\r\n")
        if sep < 0:
            return None
        header = bytes(self._buffer[:sep]).decode("ascii", errors="replace")
        length = None
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
                break
        if length is None:
            # Resync: drop one byte
            del self._buffer[0]
            return None
        total = sep + 4 + length
        if len(self._buffer) < total:
            return None
        body = bytes(self._buffer[sep + 4 : total])
        del self._buffer[:total]
        return json.loads(body.decode("utf-8"))

    def _dispatch(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            fut = self._pending.pop(message["id"], None)
            if fut is None or fut.done():
                return
            if "error" in message:
                fut.set_exception(RuntimeError(str(message["error"])))
            else:
                fut.set_result(message.get("result"))
            return
        method = message.get("method")
        params = message.get("params") or {}
        if method == "textDocument/publishDiagnostics":
            uri = str(params.get("uri") or "")
            diags = list(params.get("diagnostics") or [])
            self._diagnostics[uri] = diags
            event = self._diag_events.setdefault(uri, asyncio.Event())
            event.set()
        elif method == "workspace/configuration":
            # Respond with empty configs if server asked (id present).
            if "id" in message:
                asyncio.create_task(self._reply(message["id"], []))
        elif method == "window/workDoneProgress/create":
            if "id" in message:
                asyncio.create_task(self._reply(message["id"], None))

    async def _reply(self, req_id: Any, result: Any) -> None:
        await self._send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _as_location_list(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []
