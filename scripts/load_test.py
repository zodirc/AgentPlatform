#!/usr/bin/env python3
"""L3 load smoke: concurrent turns + SSE reconnect."""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _strip_env_value(raw: str) -> str:
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


def http_json(method: str, url: str, body: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update(admin_headers())
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def consume_sse_until_terminal(url: str, *, since_sequence: int | None = None) -> int:
    headers = {"Accept": "text/event-stream"}
    headers.update(admin_headers())
    if since_sequence is not None:
        url = f"{url}?since_sequence={since_sequence}"
    req = urllib.request.Request(url, headers=headers)
    last_sequence = since_sequence or 0
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("id:"):
                continue
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[5:].strip())
            last_sequence = max(last_sequence, int(payload.get("sequence", last_sequence)))
            if payload["type"] in {"turn.completed", "turn.failed", "turn.cancelled"}:
                break
    return last_sequence


def run_turn(base: str, i: int) -> None:
    session = http_json("POST", f"{base}/api/v1/sessions", {"default_scenario_id": "writing"})
    turn = http_json(
        "POST",
        f"{base}/api/v1/sessions/{session['id']}/turns",
        {
            "message": f"L0 golden stub load-{i}",
            "scenario_id": "writing",
            "client_request_id": f"00000000-0000-4000-8000-{i:012d}",
        },
    )
    turn_id = turn["id"]
    url = f"{base}/api/v1/turns/{turn_id}/stream"
    last_sequence = consume_sse_until_terminal(url)
    view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
    if view["status"] != "completed":
        raise RuntimeError(f"turn {turn_id} status {view['status']}")


def run_sse_reconnect(base: str) -> None:
    session = http_json("POST", f"{base}/api/v1/sessions", {"default_scenario_id": "writing"})
    turn = http_json(
        "POST",
        f"{base}/api/v1/sessions/{session['id']}/turns",
        {
            "message": "shared.02 sse reconnect load test",
            "scenario_id": "writing",
            "client_request_id": "00000000-0000-4000-8000-000000000099",
        },
    )
    turn_id = turn["id"]
    url = f"{base}/api/v1/turns/{turn_id}/stream"
    headers = {"Accept": "text/event-stream"}
    headers.update(admin_headers())
    req = urllib.request.Request(url, headers=headers)
    seen_types: list[str] = []
    last_sequence = 0
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[5:].strip())
            last_sequence = max(last_sequence, int(payload.get("sequence", last_sequence)))
            seen_types.append(payload["type"])
            if payload["type"] == "turn.accepted":
                break
    if "turn.accepted" not in seen_types:
        raise RuntimeError("SSE reconnect test: missing turn.accepted on first connect")
    consume_sse_until_terminal(url, since_sequence=last_sequence)
    view = http_json("GET", f"{base}/api/v1/turns/{turn_id}/view")
    if view["status"] != "completed":
        raise RuntimeError(f"SSE reconnect turn {turn_id} status {view['status']}")


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost"
    workers = 5
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_turn, base, i) for i in range(workers)]
        for fut in concurrent.futures.as_completed(futures):
            fut.result()
    run_sse_reconnect(base)
    print(f"L3 load OK ({workers} concurrent turns + SSE reconnect)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
