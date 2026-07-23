#!/usr/bin/env python3
"""Probe api→runtime StartTurn path (docs/28 gate / eval-run-isolated).

Expects HTTP 422/400 (validation) or 202 with a well-formed body.
Fails fast on 401 (INTERNAL_SERVICE_TOKEN mismatch) or connection errors.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from uuid import uuid4


def main() -> int:
    base = os.environ.get("RUNTIME_URL", "http://runtime:8001").rstrip("/")
    token = os.environ.get("INTERNAL_SERVICE_TOKEN", "")
    if not token:
        print("INTERNAL_SERVICE_TOKEN missing", file=sys.stderr)
        return 2

    # Intentionally incomplete → runtime should 422, proving auth + routing.
    payload = {
        "turn_id": str(uuid4()),
        "run_id": str(uuid4()),
        "session_id": str(uuid4()),
        "scenario_id": "agent",
        "message": "probe",
        "trace_id": str(uuid4()),
    }
    req = urllib.request.Request(
        f"{base}/internal/commands/start-turn",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Internal-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(resp.status)
            return 0 if resp.status in {200, 202} else 1
    except urllib.error.HTTPError as exc:
        print(exc.code)
        if exc.code == 401:
            return 3
        if exc.code in {400, 422, 202}:
            return 0
        return 1
    except Exception as exc:
        print(f"0 ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
