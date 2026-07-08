#!/usr/bin/env python3
"""L3 load smoke: concurrent turns + SSE reconnect."""

from __future__ import annotations

import concurrent.futures
import json
import sys
import urllib.request


def http_json(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def consume_sse_until_terminal(url: str, *, since_sequence: int | None = None) -> int:
    headers = {"Accept": "text/event-stream"}
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
