#!/usr/bin/env python3
"""Run golden turn eval cases against a live stack."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "eval" / "golden"
CONTRACTS_DIR = ROOT / "packages" / "contracts"
DEFAULT_EVAL_WORKSPACE = ROOT / ".eval-workspace"
DAILY_WORKSPACE = ROOT / "workspace"
if str(CONTRACTS_DIR) not in sys.path:
    sys.path.insert(0, str(CONTRACTS_DIR))

_golden_validator = None


def get_golden_validator():
    global _golden_validator
    if _golden_validator is None:
        from jsonschema import Draft202012Validator

        schema = json.loads((CONTRACTS_DIR / "eval" / "golden_turn.schema.json").read_text())
        _golden_validator = Draft202012Validator(schema)
    return _golden_validator


def http_json(
    method: str,
    url: str,
    body: dict | None = None,
    *,
    extra_headers: dict[str, str] | None = None,
    retries: int = 5,
) -> dict:
    """JSON HTTP helper. Retries transient 502/503 (runtime recreate races)."""
    data = None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update(admin_headers())
    if extra_headers:
        headers.update(extra_headers)
    if body is not None:
        data = json.dumps(body).encode()
    last_exc: Exception | None = None
    attempts = max(1, retries)
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            last_exc = exc
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            if exc.code in {502, 503} and attempt + 1 < attempts:
                print(
                    f"    retry {method} {url} after HTTP {exc.code} "
                    f"(attempt {attempt + 1}/{attempts})"
                    + (f" body={err_body}" if err_body else ""),
                    flush=True,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            if err_body:
                print(f"    HTTP {exc.code} body: {err_body}", flush=True)
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                print(
                    f"    retry {method} {url} after {type(exc).__name__}: {exc} "
                    f"(attempt {attempt + 1}/{attempts})",
                    flush=True,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    assert last_exc is not None
    raise last_exc


def stream_headers() -> dict[str, str]:
    headers = {"Accept": "text/event-stream"}
    headers.update(admin_headers())
    return headers


def _strip_env_value(raw: str) -> str:
    """Strip CR, spaces, unquoted inline # comments, and matching quotes."""
    v = raw.strip().strip("\r")
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if "#" in v:
        v = v.split("#", 1)[0].rstrip()
    return v.strip().strip("\r")


def _env_value(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return default
    for line in env_path.read_text().splitlines():
        line = line.strip("\r")
        if line.startswith(f"{name}="):
            return _strip_env_value(line.split("=", 1)[1])
    return default


def admin_headers() -> dict[str, str]:
    auth_on = _env_value("AUTH_ENABLED", "false").lower() in {"true", "1", "yes"}
    force = os.environ.get("CI", "").lower() in {"true", "1"} or os.environ.get(
        "SMOKE_FORCE_AUTH", ""
    ).lower() in {"true", "1"}
    if not auth_on and not force:
        return {}
    password = _env_value("ADMIN_PASSWORD", "admin") or "admin"
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def compose_workspace_path(raw_path: str) -> Path:
    """Resolve a Compose bind source relative to the base compose file."""
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = ROOT / "deploy" / path
    return path.resolve()


def validate_workspace(workspace: Path, *, allow_shared_workspace: bool) -> Path:
    resolved = workspace.expanduser().resolve()
    daily = DAILY_WORKSPACE.resolve()
    if resolved in {ROOT.resolve(), daily} and not allow_shared_workspace:
        raise ValueError(
            f"refusing shared repository workspace {resolved}; "
            "use the dedicated .eval-workspace or pass --allow-shared-workspace "
            "for legacy behavior"
        )

    runtime_workspace = compose_workspace_path(
        _env_value("WORKSPACE_HOST_PATH", "../workspace")
    )
    if runtime_workspace != resolved:
        raise ValueError(
            "eval workspace does not match the runtime bind mount: "
            f"runner={resolved}, WORKSPACE_HOST_PATH={runtime_workspace}. "
            "Start eval through a make eval-* target or set both paths explicitly."
        )
    return resolved


def _is_mount_point(path: Path) -> bool:
    try:
        return path.is_mount()
    except OSError:
        return False


def _rm_tree_skip_mounts(path: Path) -> None:
    """Remove a file/dir tree but never delete bind-mount roots (e.g. seed RO)."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if not path.is_dir():
        path.unlink(missing_ok=True)
        return
    if _is_mount_point(path):
        return
    for child in list(path.iterdir()):
        if child.is_dir() and not child.is_symlink():
            if _is_mount_point(child):
                continue
            _rm_tree_skip_mounts(child)
        else:
            try:
                child.unlink()
            except IsADirectoryError:
                _rm_tree_skip_mounts(child)
            except FileNotFoundError:
                pass
            except PermissionError:
                # Root-owned residue from a previous container run — skip.
                continue
    try:
        path.rmdir()
    except OSError:
        # Still contains a mount or unreadable children; leave the directory.
        pass


def reset_workspace(workspace: Path) -> None:
    """Clear one eval case's files without replacing the bind-mounted root inode.

    Compose mounts the standing seed corpus at ``sources/seed/writing`` (RO).
    That mount must not be rmtree'd — otherwise eval dies with PermissionError
    on ``writing`` (docs/15 · docs/28 gate / make eval-*).
    """
    workspace.mkdir(parents=True, exist_ok=True)
    for child in list(workspace.iterdir()):
        if child.name == "sources" and child.is_dir() and not child.is_symlink():
            for sub in list(child.iterdir()):
                if sub.name == "seed":
                    # RO seed bind (or its parent dir); never delete.
                    continue
                _rm_tree_skip_mounts(sub)
            continue
        _rm_tree_skip_mounts(child)

    for directory in (workspace, workspace / "sections", workspace / "sources", workspace / "exports"):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o777)
        except OSError:
            pass


def admin_create_provider(base: str, cmd: dict) -> None:
    body = {
        "label": cmd["label"],
        "provider": cmd["provider"],
        "model_name": cmd["model_name"],
        "api_key": cmd["api_key"],
        "activate": cmd.get("activate", True),
    }
    http_json(
        "POST",
        f"{base}/api/v1/admin/model-providers",
        body,
    )


def collect_sse_events(
    base: str,
    turn_id: str,
    terminal: set[str],
    *,
    since: int = 0,
) -> list[str]:
    records, _, _ = collect_sse_event_records(base, turn_id, terminal, since=since)
    return [e["type"] for e in records]


def collect_sse_event_records(
    base: str,
    turn_id: str,
    terminal: set[str],
    *,
    since: int = 0,
    stop_after: str | None = None,
    started_at: float | None = None,
    max_attempts: int = 3,
) -> tuple[list[dict], float | None, float | None]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _collect_sse_event_records_once(
                base,
                turn_id,
                terminal,
                since=since,
                stop_after=stop_after,
                started_at=started_at,
            )
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise
            time.sleep(min(2 * attempt, 5))
    raise last_error  # type: ignore[misc]


def _collect_sse_event_records_once(
    base: str,
    turn_id: str,
    terminal: set[str],
    *,
    since: int = 0,
    stop_after: str | None = None,
    started_at: float | None = None,
) -> tuple[list[dict], float | None, float | None]:
    url = f"{base}/api/v1/turns/{turn_id}/stream?since_sequence={since}"
    req = urllib.request.Request(url, headers=stream_headers())
    events: list[dict] = []
    ttfb_ms: float | None = None
    first_token_ms: float | None = None
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("data:"):
                if started_at is not None and ttfb_ms is None:
                    ttfb_ms = (time.perf_counter() - started_at) * 1000.0
                payload = json.loads(line[5:].strip())
                if started_at is not None and first_token_ms is None and payload.get("type") == "turn.token":
                    first_token_ms = (time.perf_counter() - started_at) * 1000.0
                events.append(payload)
                if stop_after and payload["type"] == stop_after:
                    break
                if payload["type"] in terminal:
                    break
    return events, ttfb_ms, first_token_ms


def collect_sse_after_cancel(
    base: str,
    turn_id: str,
    terminal: set[str],
    *,
    since: int = 0,
) -> tuple[list[dict], float | None]:
    """POST cancel then collect SSE until terminal; return cancel→turn.cancelled latency."""
    cancel_at = time.perf_counter()
    http_json("POST", f"{base}/api/v1/turns/{turn_id}/cancel", {"force": False})
    url = f"{base}/api/v1/turns/{turn_id}/stream?since_sequence={since}"
    req = urllib.request.Request(url, headers=stream_headers())
    events: list[dict] = []
    cancel_latency_ms: float | None = None
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[5:].strip())
            events.append(payload)
            if cancel_latency_ms is None and payload.get("type") == "turn.cancelled":
                cancel_latency_ms = (time.perf_counter() - cancel_at) * 1000.0
            if payload.get("type") in terminal:
                break
    return events, cancel_latency_ms


def collect_ws_event_records(
    base: str,
    turn_id: str,
    terminal: set[str],
    *,
    started_at: float | None = None,
) -> tuple[list[dict], float | None, float | None]:
    try:
        import websockets
    except ImportError as exc:
        raise AssertionError("websockets package required for ws.stream eval") from exc

    ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
    uri = f"{ws_base}/api/v1/turns/{turn_id}/ws"

    async def _consume() -> tuple[list[dict], float | None, float | None]:
        events: list[dict] = []
        ttfb_ms: float | None = None
        first_token_ms: float | None = None
        async with websockets.connect(uri, additional_headers=admin_headers()) as ws:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                if started_at is not None and ttfb_ms is None:
                    ttfb_ms = (time.perf_counter() - started_at) * 1000.0
                payload = json.loads(raw)
                if started_at is not None and first_token_ms is None and payload.get("type") == "turn.token":
                    first_token_ms = (time.perf_counter() - started_at) * 1000.0
                events.append(payload)
                if payload.get("type") in terminal:
                    break
        return events, ttfb_ms, first_token_ms

    return asyncio.run(_consume())


def stream_until_event(
    base: str,
    turn_id: str,
    *,
    after_type: str,
    terminal: set[str],
) -> tuple[list[dict], threading.Event]:
    done = threading.Event()
    records: list[dict] = []
    error: list[Exception] = []

    def worker() -> None:
        url = f"{base}/api/v1/turns/{turn_id}/stream"
        req = urllib.request.Request(url, headers=stream_headers())
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw in resp:
                    if done.is_set():
                        break
                    line = raw.decode().strip()
                    if not line.startswith("data:"):
                        continue
                    payload = json.loads(line[5:].strip())
                    records.append(payload)
                    if payload["type"] == after_type:
                        done.set()
                    if payload["type"] in terminal:
                        break
        except Exception as exc:  # noqa: BLE001
            error.append(exc)
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    if not done.wait(timeout=60):
        raise TimeoutError(f"timed out waiting for {after_type}")
    thread.join(timeout=2)
    if error:
        raise error[0]
    return records, done


def collect_sse_with_reconnect(
    base: str,
    turn_id: str,
    terminal: set[str],
    *,
    reconnect_after: str,
) -> list[str]:
    first_batch, _ = stream_until_event(
        base,
        turn_id,
        after_type=reconnect_after,
        terminal=terminal,
    )
    if not first_batch:
        raise AssertionError("no events before reconnect")
    last_sequence = max(e["sequence"] for e in first_batch)
    second_batch, _, _ = collect_sse_event_records(
        base,
        turn_id,
        terminal,
        since=last_sequence,
    )
    merged = first_batch + second_batch
    types = [e["type"] for e in merged]
    sequences = [e["sequence"] for e in merged]
    if len(sequences) != len(set(sequences)):
        raise AssertionError(f"duplicate sequences after reconnect: {sequences}")
    if sequences != sorted(sequences):
        raise AssertionError(f"sequence order broken after reconnect: {sequences}")
    return types


def sequence_contains(events: list[str], required: list[str]) -> bool:
    idx = 0
    for need in required:
        while idx < len(events) and events[idx] != need:
            idx += 1
        if idx >= len(events):
            return False
        idx += 1
    return True


def sequence_equals(events: list[str], required: list[str]) -> bool:
    return events == required


def _first_patch_id(artifacts: list) -> str:
    for art in artifacts:
        if isinstance(art, dict) and art.get("patch_id"):
            return str(art["patch_id"])
    raise AssertionError("no patch_id in turn artifacts")


def _wait_for_patch_applied(base: str, turn_id: str, patch_id: str, timeout: int = 30) -> None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
        if any(
            a.get("patch_id") == patch_id and a.get("status") == "applied"
            for a in view.get("artifacts", [])
        ):
            return
        time.sleep(0.5)
    raise TimeoutError(f"patch {patch_id} not applied on turn {turn_id}")


def _wait_for_patch_rejected(base: str, turn_id: str, patch_id: str, timeout: int = 30) -> None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
        if any(
            a.get("patch_id") == patch_id and a.get("status") == "rejected"
            for a in view.get("artifacts", [])
        ):
            return
        time.sleep(0.5)
    raise TimeoutError(f"patch {patch_id} not rejected on turn {turn_id}")


def _wait_for_view_status(base: str, turn_id: str, status: str, timeout: int = 30) -> None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
        if view.get("status") == status:
            return
        time.sleep(0.5)
    raise TimeoutError(f"turn {turn_id} did not reach status {status}")


def _wait_for_tool_approval(
    base: str,
    turn_id: str,
    *,
    previous_tool_call_id: str | None = None,
    timeout: int = 90,
) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        last = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
        status = last.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return last
        if status == "waiting_approval":
            tool_call_id = (last.get("interrupt") or {}).get("tool_call_id")
            if tool_call_id and tool_call_id != previous_tool_call_id:
                return last
        time.sleep(0.25)
    raise TimeoutError(
        f"turn {turn_id} did not reach waiting_approval"
        f" (previous_tool_call_id={previous_tool_call_id!r}, last={last!r})"
    )


def read_workspace_file(workspace: Path, rel: str) -> str | None:
    if any(ch in rel for ch in "*?[]"):
        matches = sorted(
            workspace.glob(rel),
            key=lambda p: p.stat().st_mtime if p.is_file() else 0.0,
            reverse=True,
        )
        for target in matches:
            if target.is_file():
                return target.read_text(encoding="utf-8", errors="replace")
        return None
    target = (workspace / rel).resolve()
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8", errors="replace")


def apply_fixtures(workspace: Path, case: dict) -> None:
    fixtures = case.get("fixtures", {})
    for item in fixtures.get("workspace", []):
        rel = item["path"]
        content = item.get("content", "")
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    setup = case.get("setup", {})
    chars = setup.get("large_file_chars")
    if chars:
        target = workspace / "large_file.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("A" * int(chars) + "\n", encoding="utf-8")


def check_runtime_logs(needle: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "deploy" / "docker-compose.yml"),
                "--env-file",
                str(ROOT / ".env"),
                "logs",
                "runtime",
                "--tail=200",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ROOT),
        )
        return needle in proc.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def wait_for_index_content(needle: str, *, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    last_error: str | None = None
    while time.time() < deadline:
        try:
            proc = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(ROOT / "deploy" / "docker-compose.yml"),
                    "--env-file",
                    str(ROOT / ".env"),
                    "exec",
                    "-T",
                    "runtime",
                    "cat",
                    "/data/vectorstore/sources.json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(ROOT),
            )
            if proc.returncode == 0 and needle in proc.stdout:
                return
            last_error = proc.stderr.strip() or f"exit {proc.returncode}"
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            last_error = str(exc)
        time.sleep(1.0)
    raise TimeoutError(f"vector index missing {needle!r} (last_error={last_error!r})")


def p95(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))
    return float(ordered[idx])


def count_steps(events: list[str]) -> int:
    return sum(1 for event in events if event == "step.started")


def assert_event_payloads(case_id: str, records: list[dict]) -> None:
    from validate_payload import indexed_event_types, validate_event_payload

    indexed = indexed_event_types()
    for record in records:
        event_type = record.get("type")
        if event_type not in indexed:
            continue
        payload = record.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        try:
            validate_event_payload(event_type, payload)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"{case_id}: invalid payload for {event_type}: {exc}"
            ) from exc


def merge_sse_records(events: list[str], event_records: list[dict], records: list[dict]) -> None:
    event_records.extend(records)
    events.extend(e["type"] for e in records)


def _max_event_sequence(event_records: list[dict]) -> int:
    return max((int(e.get("sequence", 0)) for e in event_records), default=0)


def run_case(path: Path, base: str, workspace: Path) -> None:
    case = yaml.safe_load(path.read_text())
    get_golden_validator().validate(case)
    case_id = case["id"]
    scenario_id = case["scenario_id"]
    message = case["input"]["message"]
    client_request_id = case.get("input", {}).get("client_request_id")

    print(f"==> {case_id} ({path.name})", flush=True)

    apply_fixtures(workspace, case)

    commands = case.get("commands", [])
    for cmd in commands:
        if cmd.get("type") == "add-fixture":
            apply_fixtures(workspace, {"fixtures": cmd})
        elif cmd.get("type") == "admin.create-provider":
            admin_create_provider(base, cmd)

    session = http_json("POST", f"{base}/api/v1/sessions", {"default_scenario_id": scenario_id})
    terminal_events = {"turn.completed", "turn.failed", "turn.cancelled"}
    for cmd in commands:
        if cmd.get("type") == "warmup-turn":
            warmup_body = {
                "message": cmd.get("message", "warmup"),
                "scenario_id": cmd.get("scenario_id", scenario_id),
            }
            warmup_turn = http_json(
                "POST",
                f"{base}/api/v1/sessions/{session['id']}/turns",
                warmup_body,
            )
            collect_sse_event_records(base, warmup_turn["id"], terminal_events)
        elif cmd.get("type") == "wait-index":
            wait_for_index_content(str(cmd.get("contains", "")))

    needs_approval = any(
        c.get("type") in {"approve-tool-call", "deny-tool-call"} for c in commands
    )
    has_reconnect = any(c.get("type") == "sse.reconnect" for c in commands)
    has_cancel = any(c.get("type") == "cancel" for c in commands)
    has_duplicate = any(c.get("type") == "duplicate-turn" for c in commands)
    has_new_turn = any(c.get("type") == "new-turn" for c in commands)
    has_session_turns = any(c.get("type") == "session-turns" for c in commands)
    has_ws_stream = any(c.get("type") == "ws.stream" for c in commands)

    events: list[str] = []
    event_records: list[dict] = []
    step_counts: list[int] = []
    runner_ids: list[str] = []
    turn_id: str | None = None
    ttfb_ms: float | None = None
    first_token_ms: float | None = None
    cancel_latency_ms: float | None = None
    turn_started_at: float | None = None

    if has_session_turns:
        session_cmd = next(c for c in commands if c["type"] == "session-turns")
        count = int(session_cmd.get("count", 1))
        turn_message = session_cmd.get("message", message)
        for i in range(count):
            req_id = f"00000000-0000-4000-8000-{i:012d}"
            body = {
                "message": turn_message,
                "scenario_id": scenario_id,
                "client_request_id": req_id,
            }
            turn = http_json("POST", f"{base}/api/v1/sessions/{session['id']}/turns", body)
            turn_id = turn["id"]
            turn_events_records, _, _ = collect_sse_event_records(base, turn_id, terminal_events)
            merge_sse_records(events, event_records, turn_events_records)
            step_counts.append(count_steps([e["type"] for e in turn_events_records]))
            view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
            rid = view.get("runner_id")
            if rid:
                runner_ids.append(str(rid))
    else:
        turn_body: dict = {"message": message, "scenario_id": scenario_id}
        if client_request_id:
            turn_body["client_request_id"] = client_request_id
        started_at = time.perf_counter()
        turn_started_at = started_at
        turn = http_json("POST", f"{base}/api/v1/sessions/{session['id']}/turns", turn_body)
        turn_id = turn["id"]

        if has_reconnect:
            reconnect_cmd = next(c for c in commands if c["type"] == "sse.reconnect")
            events = collect_sse_with_reconnect(
                base,
                turn_id,
                terminal_events,
                reconnect_after=reconnect_cmd.get("after", "step.started"),
            )
            event_records, _, _ = collect_sse_event_records(base, turn_id, terminal_events, since=0)
        elif has_cancel:
            cancel_cmd = next(c for c in commands if c["type"] == "cancel")
            after = cancel_cmd.get("after", "tool.started")
            delay_ms = int(cancel_cmd.get("delay_ms", 300))
            partial, ready = stream_until_event(
                base,
                turn_id,
                after_type=after,
                terminal=terminal_events,
            )
            merge_sse_records(events, event_records, partial)
            time.sleep(delay_ms / 1000.0)
            tail, cancel_latency_ms = collect_sse_after_cancel(
                base,
                turn_id,
                terminal_events,
                since=max((e["sequence"] for e in partial), default=0),
            )
            merge_sse_records(events, event_records, tail)
            ready.set()
            if has_new_turn:
                _wait_for_view_status(base, turn_id, "cancelled")
                new_cmd = next(c for c in commands if c["type"] == "new-turn")
                new_body: dict = {
                    "message": new_cmd["message"],
                    "scenario_id": scenario_id,
                }
                if new_cmd.get("client_request_id"):
                    new_body["client_request_id"] = new_cmd["client_request_id"]
                new_turn = http_json(
                    "POST",
                    f"{base}/api/v1/sessions/{session['id']}/turns",
                    new_body,
                )
                turn_id = new_turn["id"]
                resume_records, _, _ = collect_sse_event_records(base, turn_id, terminal_events)
                merge_sse_records(events, event_records, resume_records)
        elif has_ws_stream:
            turn_records, ttfb_ms, first_token_ms = collect_ws_event_records(
                base, turn_id, terminal_events, started_at=started_at
            )
            merge_sse_records(events, event_records, turn_records)
        elif needs_approval:
            approval_records, _, approval_first_token = collect_sse_event_records(
                base, turn_id, {"approval.requested"}, started_at=turn_started_at
            )
            if first_token_ms is None:
                first_token_ms = approval_first_token
            merge_sse_records(events, event_records, approval_records)
        elif has_duplicate:
            dup = http_json(
                "POST",
                f"{base}/api/v1/sessions/{session['id']}/turns",
                turn_body,
            )
            if dup["id"] != turn_id:
                raise AssertionError(
                    f"{case_id}: duplicate client_request_id returned new turn {dup['id']}"
                )
            turn_records, _, _ = collect_sse_event_records(base, turn_id, terminal_events)
            merge_sse_records(events, event_records, turn_records)
        else:
            turn_records, ttfb_ms, first_token_ms = collect_sse_event_records(
                base, turn_id, terminal_events, started_at=started_at
            )
            merge_sse_records(events, event_records, turn_records)
        step_counts.append(count_steps(events))

    last_tool_call_id: str | None = None
    for cmd in commands:
        if cmd["type"] in {
            "sse.reconnect",
            "ws.stream",
            "cancel",
            "duplicate-turn",
            "new-turn",
            "add-fixture",
            "session-turns",
            "admin.create-provider",
            "warmup-turn",
            "wait-index",
        }:
            continue
        if cmd["type"] == "patch.accept":
            patch_id = cmd["patch_id"]
            if patch_id == "auto":
                view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
                patch_id = _first_patch_id(view.get("artifacts", []))
            http_json(
                "POST",
                f"{base}/api/v1/turns/{turn_id}/patch/accept",
                {"patch_id": patch_id},
            )
            _wait_for_patch_applied(base, turn_id, patch_id)
            events.append("patch.applied")
        elif cmd["type"] == "patch.reject":
            patch_id = cmd["patch_id"]
            if patch_id == "auto":
                view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
                patch_id = _first_patch_id(view.get("artifacts", []))
            http_json(
                "POST",
                f"{base}/api/v1/turns/{turn_id}/patch/reject",
                {"patch_id": patch_id},
            )
            _wait_for_patch_rejected(base, turn_id, patch_id)
            events.append("patch.rejected")
        elif cmd["type"] == "approve-tool-call":
            view = _wait_for_tool_approval(
                base,
                turn_id,
                previous_tool_call_id=last_tool_call_id,
            )
            if view.get("status") in {"completed", "failed", "cancelled"}:
                continue
            tool_call_id = cmd["tool_call_id"]
            if tool_call_id == "auto":
                interrupt = view.get("interrupt") or {}
                tool_call_id = interrupt.get("tool_call_id")
                if not tool_call_id:
                    raise AssertionError(f"{case_id}: no interrupt tool_call_id")
            http_json(
                "POST",
                f"{base}/api/v1/turns/{turn_id}/approve-tool-call",
                {"tool_call_id": tool_call_id},
            )
            last_tool_call_id = tool_call_id
            since = _max_event_sequence(event_records)
            resume_records, _, resume_first_token = collect_sse_event_records(
                base,
                turn_id,
                terminal_events | {"approval.requested"},
                since=since,
                started_at=turn_started_at if first_token_ms is None else None,
            )
            if first_token_ms is None and resume_first_token is not None:
                first_token_ms = resume_first_token
            merge_sse_records(events, event_records, resume_records)
        elif cmd["type"] == "deny-tool-call":
            view = _wait_for_tool_approval(
                base,
                turn_id,
                previous_tool_call_id=last_tool_call_id,
            )
            if view.get("status") in {"completed", "failed", "cancelled"}:
                continue
            tool_call_id = cmd["tool_call_id"]
            if tool_call_id == "auto":
                interrupt = view.get("interrupt") or {}
                tool_call_id = interrupt.get("tool_call_id")
                if not tool_call_id:
                    raise AssertionError(f"{case_id}: no interrupt tool_call_id")
            body: dict = {"tool_call_id": tool_call_id}
            if cmd.get("reason"):
                body["reason"] = cmd["reason"]
            http_json(
                "POST",
                f"{base}/api/v1/turns/{turn_id}/deny-tool-call",
                body,
            )
            last_tool_call_id = tool_call_id
            since = _max_event_sequence(event_records)
            resume_records, _, resume_first_token = collect_sse_event_records(
                base,
                turn_id,
                terminal_events | {"approval.requested"},
                since=since,
                started_at=turn_started_at if first_token_ms is None else None,
            )
            if first_token_ms is None and resume_first_token is not None:
                first_token_ms = resume_first_token
            merge_sse_records(events, event_records, resume_records)

    assertions = case.get("assertions", {})
    event_asserts = assertions.get("events", {})

    if event_asserts.get("payload_validates", True) and event_records:
        assert_event_payloads(case_id, event_records)

    event_payload_assert = assertions.get("event_payload", {})
    for event_type, expected_fields in event_payload_assert.items():
        matched = [r for r in event_records if r.get("type") == event_type]
        if not matched:
            raise AssertionError(f"{case_id}: missing event {event_type} for payload assert")
        payload = matched[0].get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        for key, expected in expected_fields.items():
            if payload.get(key) != expected:
                raise AssertionError(
                    f"{case_id}: {event_type} payload[{key!r}]={payload.get(key)!r} != {expected!r}"
                )

    if "sequence_equals" in event_asserts:
        if not sequence_equals(events, event_asserts["sequence_equals"]):
            raise AssertionError(f"{case_id}: expected {event_asserts['sequence_equals']}, got {events}")

    if "sequence_contains" in event_asserts:
        if not sequence_contains(events, event_asserts["sequence_contains"]):
            raise AssertionError(f"{case_id}: missing subsequence in {events}")

    for forbidden in event_asserts.get("sequence_not_contains", []):
        if forbidden in events:
            raise AssertionError(f"{case_id}: forbidden event {forbidden}")

    turn_assert = assertions.get("turn", {})
    if "status" in turn_assert:
        if turn_id is None:
            raise AssertionError(f"{case_id}: missing turn_id for status assertion")
        view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
        if view["status"] != turn_assert["status"]:
            raise AssertionError(f"{case_id}: status {view['status']} != {turn_assert['status']}")

    tool_assert = assertions.get("tool", {})
    if tool_assert and turn_id is not None:
        view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
        timeline = view.get("tool_timeline", []) or []
        needle = tool_assert.get("result_matches", "")
        tool_name = tool_assert.get("name", "")
        expected_retrieval = tool_assert.get("retrieval")
        matched = False
        retrieval_matched = expected_retrieval is None
        name_seen = False
        for item in timeline:
            if item.get("tool_name") != tool_name:
                continue
            name_seen = True
            summary = str(item.get("summary", ""))
            if needle and re.search(needle, summary, re.S):
                matched = True
            elif not needle:
                matched = True
        if expected_retrieval:
            allowed = (
                {expected_retrieval}
                if isinstance(expected_retrieval, str)
                else set(expected_retrieval)
            )
            for artifact in view.get("artifacts", []):
                if artifact.get("type") != "retrieval":
                    continue
                if artifact.get("mode") in allowed:
                    retrieval_matched = True
                    break
        if tool_name and not name_seen:
            raise AssertionError(f"{case_id}: tool {tool_name!r} missing from tool_timeline")
        if needle and not matched:
            raise AssertionError(f"{case_id}: tool {tool_name!r} missing result match {needle!r}")
        forbidden_result = tool_assert.get("result_not_matches", "")
        if forbidden_result:
            leaked = False
            for item in timeline:
                if tool_name and item.get("tool_name") != tool_name:
                    continue
                summary = str(item.get("summary", ""))
                if re.search(forbidden_result, summary, re.S):
                    leaked = True
                    break
            if leaked:
                raise AssertionError(
                    f"{case_id}: tool {tool_name!r} unexpectedly matched "
                    f"{forbidden_result!r}"
                )
        if expected_retrieval and not retrieval_matched:
            raise AssertionError(
                f"{case_id}: tool {tool_name!r} missing retrieval mode {expected_retrieval!r}"
            )
        forbidden = tool_assert.get("forbidden_names") or []
        if forbidden:
            seen = {item.get("tool_name") for item in timeline}
            for name in forbidden:
                if name in seen:
                    raise AssertionError(f"{case_id}: forbidden tool {name!r} in tool_timeline")
        max_calls = tool_assert.get("max_calls") or {}
        if max_calls:
            counts: dict[str, int] = {}
            for item in timeline:
                name = item.get("tool_name")
                if not name:
                    continue
                counts[name] = counts.get(name, 0) + 1
            for name, limit in max_calls.items():
                if counts.get(name, 0) > int(limit):
                    raise AssertionError(
                        f"{case_id}: tool {name!r} called {counts.get(name, 0)} > max {limit}"
                    )

    retrieval_assert = assertions.get("retrieval", {})
    if retrieval_assert and turn_id is not None:
        view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
        artifacts = view.get("artifacts") or []
        retrieval_arts = [a for a in artifacts if a.get("type") == "retrieval"]
        if "mode" in retrieval_assert:
            expected_mode = retrieval_assert["mode"]
            if not any(a.get("mode") == expected_mode for a in retrieval_arts):
                raise AssertionError(
                    f"{case_id}: no retrieval artifact with mode {expected_mode!r}"
                )
        if "filters_path_prefix" in retrieval_assert:
            want = retrieval_assert["filters_path_prefix"]
            matched = any(
                (a.get("filters") or {}).get("path_prefix") == want for a in retrieval_arts
            )
            if not matched:
                raise AssertionError(
                    f"{case_id}: no retrieval artifact with filters.path_prefix {want!r}"
                )
        if retrieval_assert.get("min_hit_count") is not None:
            min_hits = int(retrieval_assert["min_hit_count"])
            if not any(int(a.get("hit_count") or 0) >= min_hits for a in retrieval_arts):
                raise AssertionError(f"{case_id}: retrieval hit_count < {min_hits}")

    output_assert = assertions.get("output", {})
    if "matches" in output_assert:
        if turn_id is None:
            raise AssertionError(f"{case_id}: missing turn_id for output assertion")
        view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
        output = view.get("latest_output") or ""
        if not re.search(output_assert["matches"], output, re.S):
            raise AssertionError(f"{case_id}: output does not match {output_assert['matches']!r}")

    for ws in assertions.get("workspace", []):
        content = read_workspace_file(workspace, ws["path"])
        if content is None:
            raise AssertionError(f"{case_id}: missing workspace file {ws['path']}")
        if "matches" in ws and not re.search(ws["matches"], content, re.S):
            raise AssertionError(f"{case_id}: workspace {ws['path']} does not match {ws['matches']}")
        if "not_matches" in ws and re.search(ws["not_matches"], content, re.S):
            raise AssertionError(
                f"{case_id}: workspace {ws['path']} unexpectedly matches {ws['not_matches']}"
            )

    log_assert = assertions.get("logs", {})
    if "contains" in log_assert:
        if not check_runtime_logs(log_assert["contains"]):
            raise AssertionError(f"{case_id}: runtime logs missing {log_assert['contains']!r}")

    metrics_assert = assertions.get("metrics", {})
    if metrics_assert and step_counts:
        max_steps = int(metrics_assert.get("max_steps_per_turn", 999))
        if any(steps > max_steps for steps in step_counts):
            raise AssertionError(f"{case_id}: step count exceeded {max_steps}: {step_counts}")
        if "max_p95_step_ratio" in metrics_assert and len(step_counts) >= 20:
            early = step_counts[:10]
            late = step_counts[-10:]
            ratio = p95(late) / max(p95(early), 1.0)
            limit = float(metrics_assert["max_p95_step_ratio"])
            if ratio > limit:
                raise AssertionError(
                    f"{case_id}: p95 step ratio {ratio:.2f} > {limit} (early={early}, late={late})"
                )

    runners_assert = assertions.get("runners", {})
    if "min_distinct" in runners_assert:
        min_distinct = int(runners_assert["min_distinct"])
        distinct = len(set(runner_ids))
        if distinct < min_distinct:
            raise AssertionError(
                f"{case_id}: expected >= {min_distinct} distinct runner_id(s), "
                f"got {distinct}: {runner_ids}"
            )

    latency_assert = assertions.get("latency", {})
    if "ttfb_ms_max" in latency_assert:
        if ttfb_ms is None:
            raise AssertionError(f"{case_id}: missing ttfb measurement for latency assert")
        limit = float(latency_assert["ttfb_ms_max"])
        if ttfb_ms > limit:
            raise AssertionError(f"{case_id}: ttfb {ttfb_ms:.0f}ms > {limit}ms")
    if "first_token_ms_max" in latency_assert:
        if first_token_ms is None:
            raise AssertionError(f"{case_id}: missing first_token measurement for latency assert")
        limit = float(latency_assert["first_token_ms_max"])
        if first_token_ms > limit:
            raise AssertionError(f"{case_id}: first_token {first_token_ms:.0f}ms > {limit}ms")
    if "cancel_latency_ms_max" in latency_assert:
        if cancel_latency_ms is None:
            raise AssertionError(f"{case_id}: missing cancel latency measurement for latency assert")
        limit = float(latency_assert["cancel_latency_ms_max"])
        if cancel_latency_ms > limit:
            raise AssertionError(f"{case_id}: cancel_latency {cancel_latency_ms:.0f}ms > {limit}ms")

    session_assert = assertions.get("session", {})
    if session_assert and session:
        _assert_session_view(base, case_id, session["id"], session_assert)

    print("    OK", flush=True)


def _assert_session_view(base: str, case_id: str, session_id: str, spec: dict) -> None:
    deadline = time.time() + 15
    last: dict | None = None
    while time.time() < deadline:
        try:
            last = http_json("GET", f"{base}/api/v1/sessions/{session_id}/view")
            if "min_turn_count" in spec and int(last.get("turn_count", 0)) >= int(spec["min_turn_count"]):
                return
            if last.get("context_summary") and spec.get("require_context_summary"):
                return
        except urllib.error.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError(f"{case_id}: session view assert failed, last={last!r}")


def live_model_configured() -> bool:
    import os

    key = os.environ.get("MODEL_API_KEY", "").strip()
    if key and key != "stub":
        return True
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return False
    for line in env_path.read_text().splitlines():
        if line.startswith("MODEL_API_KEY="):
            value = line.split("=", 1)[1].strip()
            return bool(value) and value != "stub"
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run golden turn eval cases")
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--workspace", default=str(DEFAULT_EVAL_WORKSPACE))
    parser.add_argument(
        "--allow-shared-workspace",
        action="store_true",
        help="Allow the legacy repository workspace (it will be cleared between cases)",
    )
    parser.add_argument("--filter", default="", help="Substring filter for case id/path")
    parser.add_argument("--phase", default="", help="Filter by phase tag in yaml (e.g. 1, 1b)")
    parser.add_argument(
        "--mode",
        default="",
        help="Eval mode filter: live (only live cases) or stub (exclude live)",
    )
    parser.add_argument(
        "--include-recorded",
        action="store_true",
        help="Include golden cases with model_mode recorded (require MODEL_MODE=recorded)",
    )
    parser.add_argument(
        "--include-stall",
        action="store_true",
        help="Include golden cases tagged stall (require STALL_AUTO_FAIL runtime)",
    )
    parser.add_argument(
        "--include-ha",
        action="store_true",
        help="Include golden cases tagged ha (require make up-ha / dual runtime)",
    )
    parser.add_argument(
        "--include-queue",
        action="store_true",
        help="Include golden cases tagged queue (require make eval-queue / worker profile)",
    )
    parser.add_argument("cases", nargs="*", help="Specific golden yaml paths")
    args = parser.parse_args()

    try:
        workspace = validate_workspace(
            Path(args.workspace),
            allow_shared_workspace=args.allow_shared_workspace,
        )
    except ValueError as exc:
        parser.error(str(exc))

    paths: list[Path]
    if args.cases:
        paths = [Path(p) for p in args.cases]
    else:
        paths = sorted(GOLDEN_DIR.rglob("*.yaml"))

    if args.filter:
        filtered: list[Path] = []
        needle = args.filter.lower()
        for p in paths:
            if needle in str(p).lower():
                filtered.append(p)
                continue
            case_id = str(yaml.safe_load(p.read_text()).get("id", "")).lower()
            if needle in case_id:
                filtered.append(p)
        paths = filtered

    if args.phase:
        filtered: list[Path] = []
        for p in paths:
            case = yaml.safe_load(p.read_text())
            phase = str(case.get("phase", ""))
            if phase == args.phase or phase.startswith(args.phase):
                filtered.append(p)
        paths = filtered

    if args.mode == "live":
        paths = [p for p in paths if yaml.safe_load(p.read_text()).get("model_mode") == "live"]
        if not paths:
            print("No live golden cases found", file=sys.stderr)
            return 1
        if not live_model_configured():
            strict = os.environ.get("EVAL_LIVE_STRICT", "1") == "1"
            in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
            if in_ci and strict:
                print("Live eval requires MODEL_API_KEY in CI", file=sys.stderr)
                return 1
            print("Skipping live eval: MODEL_API_KEY not configured", file=sys.stderr)
            return 0
    elif args.mode == "recorded":
        paths = [p for p in paths if yaml.safe_load(p.read_text()).get("model_mode") == "recorded"]
        if not paths:
            print("No recorded golden cases found", file=sys.stderr)
            return 1
    elif args.mode == "stub" or not args.mode:
        paths = [
            p
            for p in paths
            if yaml.safe_load(p.read_text()).get("model_mode", "stub") not in {"live", "recorded"}
        ]

    if not args.include_recorded:
        paths = [
            p
            for p in paths
            if yaml.safe_load(p.read_text()).get("model_mode") != "recorded"
        ]

    if not args.include_stall:
        paths = [
            p
            for p in paths
            if "stall" not in yaml.safe_load(p.read_text()).get("tags", [])
        ]

    if not args.include_ha:
        paths = [
            p
            for p in paths
            if "ha" not in yaml.safe_load(p.read_text()).get("tags", [])
        ]

    if not args.include_queue:
        paths = [
            p
            for p in paths
            if "queue" not in yaml.safe_load(p.read_text()).get("tags", [])
        ]

    if not paths:
        print("No golden cases found", file=sys.stderr)
        return 1

    failed = 0
    skipped_flaky = 0
    for path in paths:
        case = yaml.safe_load(path.read_text())
        try:
            reset_workspace(workspace)
            run_case(path, args.base_url.rstrip("/"), workspace)
        except (AssertionError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            if case.get("flaky") and args.mode == "live":
                print(f"    FLAKY FAIL (allowed): {exc}", file=sys.stderr)
                skipped_flaky += 1
                continue
            print(f"    FAIL: {exc}", file=sys.stderr)
            failed += 1

    if failed:
        print(f"{failed} case(s) failed", file=sys.stderr)
        return 1
    total = len(paths)
    if skipped_flaky:
        print(f"All {total} case(s) passed ({skipped_flaky} flaky failure(s) tolerated)", flush=True)
    else:
        print(f"All {total} golden case(s) passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
