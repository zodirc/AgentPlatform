#!/usr/bin/env python3
"""Release console — per-module health + one-click actions.

Left: each module/row has its own action. Right: detail board.
Auto-refreshes; no manual「刷新检查」. Loopback may skip secret.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
RELEASE_SH = ROOT / "scripts" / "release" / "release.sh"
STATUS_DIR = Path(os.environ.get("RELEASE_STATUS_DIR", ROOT / "reports" / "release"))
STATUS_FILE = STATUS_DIR / "status.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"
PORT = int(os.environ.get("RELEASE_CONSOLE_PORT", "9090"))
SECRET = os.environ.get("RELEASE_CONSOLE_SECRET", "").strip()
# Dev single-machine: trust 127.0.0.1 without secret (still require secret for non-local).
LOCAL_TRUST = os.environ.get("RELEASE_CONSOLE_LOCAL_TRUST", "1").strip() not in {
    "0",
    "false",
    "no",
}

_run_lock = threading.Lock()
_plan_cache: dict = {"at": 0.0, "data": None}
_PLAN_TTL_SEC = 8.0
_PLAN_DISK = STATUS_DIR / "plan_snapshot.json"
_rebuild_lock = threading.Lock()
sys.path.insert(0, str(ROOT / "scripts" / "release"))

ALLOWED_ACTIONS = {
    "up-api": ["bash", str(RELEASE_SH), "run", "--modules=api"],
    "up-runtime": ["bash", str(RELEASE_SH), "run", "--modules=runtime"],
    "up-web": ["bash", str(RELEASE_SH), "run", "--modules=web"],
    "up-gateway": ["bash", str(RELEASE_SH), "run", "--modules=gateway"],
    "sync-sources": ["make", "-C", str(ROOT), "sync-sources"],
    "sync-ops-indexes": ["make", "-C", str(ROOT), "sync-ops-indexes"],
}

# Console action / plan item id → per-module log stem under logs/
ACTION_LOG_KEY = {
    "up-api": "api",
    "up-runtime": "runtime",
    "up-web": "web",
    "up-gateway": "gateway",
    "sync-sources": "index_product",
    "sync-ops-indexes": "index_ops",
}
ITEM_LOG_KEY = {
    "api": "api",
    "runtime": "runtime",
    "web": "web",
    "gateway": "gateway",
    "embedding": "runtime",  # 换模走 runtime 重建
    "index_product": "index_product",
    "index_ops": "index_ops",
}


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _read_deploy_status() -> dict:
    if not STATUS_FILE.is_file():
        return {"phase": "idle", "message": "", "changed": [], "deployed": {}}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"phase": "error", "message": str(exc), "changed": [], "deployed": {}}


def _build_plan() -> dict:
    os.environ["RELEASE_STATUS_DIR"] = str(STATUS_DIR)
    from plan import build_plan  # type: ignore

    return build_plan()


def _with_deploy(plan: dict) -> dict:
    snap = dict(plan)
    dep = _read_deploy_status()
    snap["deploy"] = {
        "phase": dep.get("phase") or "idle",
        "message": dep.get("message") or "",
        "error": dep.get("error"),
        "run_id": dep.get("run_id"),
        "log_file": dep.get("log_file"),
        "current_module": dep.get("current_module"),
        "changed": dep.get("changed") or snap.get("dirty_code_modules") or [],
        "deployed": dep.get("deployed") or {},
    }
    return snap


def _persist_plan(plan: dict) -> None:
    try:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        _PLAN_DISK.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_disk_plan() -> dict | None:
    if not _PLAN_DISK.is_file():
        return None
    try:
        data = json.loads(_PLAN_DISK.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("items") else None
    except (OSError, json.JSONDecodeError):
        return None


def _compute_plan() -> dict:
    plan = _build_plan()
    for it in plan.get("items") or []:
        it["button"] = _button_for(it)
    plan = _with_deploy(plan)
    plan["stale"] = False
    _plan_cache["at"] = time.time()
    _plan_cache["data"] = plan
    _persist_plan(plan)
    return plan


def _rebuild_in_background() -> None:
    if not _rebuild_lock.acquire(blocking=False):
        return

    def _job() -> None:
        try:
            _compute_plan()
        except Exception:  # noqa: BLE001
            pass
        finally:
            _rebuild_lock.release()

    threading.Thread(target=_job, daemon=True, name="plan-rebuild").start()


def _snapshot(*, force: bool = False) -> dict:
    """Prefer instant stale cache; rebuild sync only when forced or cold-empty."""
    now = time.time()
    cached = _plan_cache["data"]
    age = now - float(_plan_cache["at"]) if cached is not None else 1e9

    if force:
        return _compute_plan()

    if cached is not None and age < _PLAN_TTL_SEC:
        return _with_deploy(cached)

    if cached is not None:
        _rebuild_in_background()
        snap = _with_deploy(cached)
        snap["stale"] = True
        return snap

    disk = _load_disk_plan()
    if disk is not None:
        _plan_cache["data"] = disk
        _plan_cache["at"] = 0.0
        _rebuild_in_background()
        snap = _with_deploy(disk)
        snap["stale"] = True
        return snap

    # First ever visit: must compute once.
    return _compute_plan()


def _button_for(it: dict) -> dict | None:
    """UI button when status=action."""
    if it.get("status") != "action":
        return None
    iid = it.get("id")
    mapping = {
        "api": ("up-api", "重建 api"),
        "runtime": ("up-runtime", "重建 runtime"),
        "web": ("up-web", "重建 web"),
        "gateway": ("up-gateway", "重建 gateway"),
        "embedding": ("up-runtime", "重建 runtime（换模）"),
        "index_product": ("sync-sources", "同步产品索引"),
        "index_ops": ("sync-ops-indexes", "同步 Ops 索引"),
    }
    if iid not in mapping:
        return None
    action, label = mapping[iid]
    return {"action": action, "label": label}


def _client_is_local(handler: SimpleHTTPRequestHandler) -> bool:
    host = (handler.client_address[0] or "").strip()
    return host in {"127.0.0.1", "::1", "localhost"}


def _authorize(handler: SimpleHTTPRequestHandler) -> bool:
    if LOCAL_TRUST and _client_is_local(handler):
        return True
    if not SECRET:
        handler.send_error(503, "RELEASE_CONSOLE_SECRET not set")
        return False
    got = handler.headers.get("X-Release-Secret", "")
    if got != SECRET:
        handler.send_error(401, "invalid X-Release-Secret")
        return False
    return True


def _spawn(cmd: list[str], *, action: str) -> None:
    env = os.environ.copy()
    env["RELEASE_STATUS_DIR"] = str(STATUS_DIR)
    log_dir = STATUS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    key = ACTION_LOG_KEY.get(action, "misc")
    out = open(log_dir / f"{key}.log", "a", encoding="utf-8")  # noqa: SIM115
    out.write(f"\n==> {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)}\n")
    out.flush()
    subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=out,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _read_module_log(module: str) -> dict:
    """Return log text for one module/item id."""
    key = ITEM_LOG_KEY.get(module, module)
    chunks: list[str] = []
    mod_log = STATUS_DIR / "logs" / f"{key}.log"
    if mod_log.is_file():
        chunks.append(mod_log.read_text(encoding="utf-8", errors="replace")[-40_000:])

    # Include active release.sh run log when it belongs to this module.
    dep = _read_deploy_status()
    cur = (dep.get("current_module") or "").strip()
    rel = dep.get("log_file") or ""
    if rel and (cur == key or (key == "runtime" and cur == "runtime")):
        p = STATUS_DIR / rel
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")[-40_000:]
            if text and text not in "".join(chunks):
                chunks.append(f"\n--- release run ({rel}) ---\n{text}")

    return {
        "module": module,
        "log_key": key,
        "text": "\n".join(chunks).strip() or f"（尚无「{key}」任务日志）",
    }


def _list_module_logs() -> dict:
    keys = ("api", "runtime", "web", "gateway", "index_product", "index_ops")
    modules: dict = {}
    for key in keys:
        p = STATUS_DIR / "logs" / f"{key}.log"
        has = p.is_file() and p.stat().st_size > 0
        modules[key] = {
            "has_log": has,
            "bytes": (p.stat().st_size if p.is_file() else 0),
            "mtime": (p.stat().st_mtime if p.is_file() else None),
        }
    return {"modules": modules}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[release-console] {self.address_string()} {fmt % args}")

    def _send_json(self, code: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/api/status", "/api/plan", "/api/detect"):
            try:
                qs = parse_qs(urlparse(self.path).query)
                force = (qs.get("force") or [""])[0] in {"1", "true", "yes"}
                self._send_json(200, _snapshot(force=force))
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"summary": "error", "headline": str(exc), "items": []})
            return
        if path == "/api/logs":
            self._send_json(200, _list_module_logs())
            return
        if path == "/api/log":
            qs = parse_qs(urlparse(self.path).query)
            module = (qs.get("module") or qs.get("item") or [""])[0].strip()
            if module:
                self._send_json(200, _read_module_log(module))
                return
            # No module: keep a short combined tail for backwards compat.
            chunks: list[str] = []
            log_dir = STATUS_DIR / "logs"
            if log_dir.is_dir():
                for p in sorted(log_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:4]:
                    if p.name == "action.log":
                        continue
                    chunks.append(
                        f"=== {p.stem} ===\n"
                        + p.read_text(encoding="utf-8", errors="replace")[-8_000:]
                    )
            self._send_json(200, {"module": "", "text": "\n\n".join(chunks) or ""})
            return
        if path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send_error(400, "invalid JSON")
            return

        if path == "/api/action":
            if not _authorize(self):
                return
            action = str(body.get("action") or "").strip()
            if action not in ALLOWED_ACTIONS:
                self._send_json(400, {"ok": False, "error": f"unknown action: {action}"})
                return
            dep = _read_deploy_status()
            if dep.get("phase") in ("building", "switching", "verifying"):
                if (STATUS_DIR / "release.lock").is_file():
                    self._send_json(409, {"ok": False, "error": "已有发布任务进行中"})
                    return
            if not _run_lock.acquire(blocking=False):
                self._send_json(409, {"ok": False, "error": "busy"})
                return
            try:
                _spawn(ALLOWED_ACTIONS[action], action=action)
                _plan_cache["at"] = 0.0  # invalidate; next force/refresh rebuilds
                self._send_json(202, {"ok": True, "action": action, "message": f"started {action}"})
            finally:
                _run_lock.release()
            return

        self.send_error(404, "not found")


def main() -> None:
    _load_dotenv()
    global SECRET, PORT, LOCAL_TRUST
    SECRET = os.environ.get("RELEASE_CONSOLE_SECRET", "").strip()
    PORT = int(os.environ.get("RELEASE_CONSOLE_PORT", "9090"))
    LOCAL_TRUST = os.environ.get("RELEASE_CONSOLE_LOCAL_TRUST", "1").strip() not in {
        "0",
        "false",
        "no",
    }
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    (STATUS_DIR / "logs").mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), partial(Handler))
    print(f"release-console http://127.0.0.1:{PORT}/", flush=True)
    print(f"local_trust={LOCAL_TRUST} (loopback actions without secret)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)


if __name__ == "__main__":
    main()
