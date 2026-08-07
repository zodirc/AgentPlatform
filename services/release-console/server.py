#!/usr/bin/env python3
"""Release console — per-module health + one-click actions.

Left: each module/row has its own action. Right: detail board.
Auto-refreshes; no manual「刷新检查」. Loopback may skip secret.
"""

from __future__ import annotations

import json
import os
import re
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
_plan_cache: dict = {"at": 0.0, "data": None, "mode": None}
_PLAN_TTL_SEC = 8.0
_PLAN_DISK = STATUS_DIR / "plan_snapshot.json"
_rebuild_lock = threading.Lock()
sys.path.insert(0, str(ROOT / "scripts" / "release"))

GIT_PULL_SH = ROOT / "scripts" / "release" / "git_pull.sh"

ALLOWED_ACTIONS = {
    "up-api": ["bash", str(RELEASE_SH), "run", "--modules=api"],
    "up-runtime": ["bash", str(RELEASE_SH), "run", "--modules=runtime"],
    "up-web": ["bash", str(RELEASE_SH), "run", "--modules=web"],
    "up-gateway": ["bash", str(RELEASE_SH), "run", "--modules=gateway"],
    "sync-sources": ["make", "-C", str(ROOT), "sync-sources"],
    "sync-ops-indexes": ["make", "-C", str(ROOT), "sync-ops-indexes"],
    "git-pull": ["bash", str(GIT_PULL_SH)],
}

# Console action / plan item id → per-module log stem under logs/
ACTION_LOG_KEY = {
    "up-api": "api",
    "up-runtime": "runtime",
    "up-web": "web",
    "up-gateway": "gateway",
    "sync-sources": "index_product",
    "sync-ops-indexes": "index_ops",
    "git-pull": "git",
}
ITEM_LOG_KEY = {
    "api": "api",
    "runtime": "runtime",
    "web": "web",
    "gateway": "gateway",
    "embedding": "runtime",  # 换模走 runtime 重建
    "index_product": "index_product",
    "index_ops": "index_ops",
    "git": "git",
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


def _build_plan(mode: str = "local") -> dict:
    os.environ["RELEASE_STATUS_DIR"] = str(STATUS_DIR)
    from plan import build_plan  # type: ignore

    return build_plan(mode=mode)


def _disk_path(mode: str) -> Path:
    return STATUS_DIR / f"plan_snapshot.{mode}.json"


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


def _persist_plan(plan: dict, mode: str) -> None:
    try:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(plan, ensure_ascii=False)
        _disk_path(mode).write_text(payload, encoding="utf-8")
        # legacy path for older clients
        _PLAN_DISK.write_text(payload, encoding="utf-8")
    except OSError:
        pass


def _load_disk_plan(mode: str) -> dict | None:
    for path in (_disk_path(mode), _PLAN_DISK):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("items"):
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _compute_plan(mode: str = "local") -> dict:
    plan = _build_plan(mode=mode)
    for it in plan.get("items") or []:
        it["button"] = _button_for(it)
    plan = _with_deploy(plan)
    plan["stale"] = False
    _plan_cache["at"] = time.time()
    _plan_cache["data"] = plan
    _plan_cache["mode"] = mode
    _persist_plan(plan, mode)
    return plan


def _rebuild_in_background(mode: str) -> None:
    if not _rebuild_lock.acquire(blocking=False):
        return

    def _job() -> None:
        try:
            _compute_plan(mode=mode)
        except Exception:  # noqa: BLE001
            pass
        finally:
            _rebuild_lock.release()

    threading.Thread(target=_job, daemon=True, name="plan-rebuild").start()


def _norm_mode(raw: str | None) -> str:
    m = (raw or "local").strip().lower()
    return m if m in {"local", "sync"} else "local"


def _snapshot(*, force: bool = False, mode: str = "local") -> dict:
    """Prefer instant stale cache; rebuild sync only when forced or cold-empty."""
    mode = _norm_mode(mode)
    now = time.time()
    cached = _plan_cache["data"]
    same_mode = _plan_cache.get("mode") == mode
    age = now - float(_plan_cache["at"]) if cached is not None and same_mode else 1e9

    if force:
        return _compute_plan(mode=mode)

    if cached is not None and same_mode and age < _PLAN_TTL_SEC:
        return _with_deploy(cached)

    if cached is not None and same_mode:
        _rebuild_in_background(mode)
        snap = _with_deploy(cached)
        snap["stale"] = True
        return snap

    disk = _load_disk_plan(mode)
    if disk is not None:
        _plan_cache["data"] = disk
        _plan_cache["at"] = 0.0
        _plan_cache["mode"] = mode
        _rebuild_in_background(mode)
        snap = _with_deploy(disk)
        snap["stale"] = True
        return snap

    return _compute_plan(mode=mode)


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


_LOG_ENTRY_RE = re.compile(
    r"^==> (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$",
    re.MULTILINE,
)
_MANAGED_LOG_KEYS = (
    "git",
    "api",
    "runtime",
    "web",
    "gateway",
    "index_product",
    "index_ops",
    "misc",
)


def _spawn(cmd: list[str], *, action: str) -> None:
    env = os.environ.copy()
    env["RELEASE_STATUS_DIR"] = str(STATUS_DIR)
    log_dir = STATUS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    key = ACTION_LOG_KEY.get(action, "misc")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    out = open(log_dir / f"{key}.log", "a", encoding="utf-8")  # noqa: SIM115
    out.write(f"\n==> {stamp} [{key}] {' '.join(cmd)}\n")
    out.flush()
    subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=out,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _fmt_local(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def _parse_log_entries(key: str, text: str, file_mtime: float) -> list[dict]:
    """Split a module log into timestamped entries."""
    text = text or ""
    matches = list(_LOG_ENTRY_RE.finditer(text))
    if not matches:
        if not text.strip():
            return []
        return [
            {
                "ts": _fmt_local(file_mtime),
                "ts_epoch": file_mtime,
                "module": key,
                "title": "（整文件，无分段时间戳）",
                "body": text.strip()[-8_000:],
            }
        ]
    entries: list[dict] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        ts = m.group(1)
        title = (m.group(2) or "").strip() or "(no title)"
        try:
            epoch = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            epoch = file_mtime
        body = text[start:end].strip()
        entries.append(
            {
                "ts": ts,
                "ts_epoch": epoch,
                "module": key,
                "title": title[:200],
                "body": body[-8_000:] if body else "(无输出)",
            }
        )
    return entries


def _collect_entries(module: str | None = None) -> list[dict]:
    log_dir = STATUS_DIR / "logs"
    keys = _MANAGED_LOG_KEYS if module in {None, "", "all", "*"} else [ITEM_LOG_KEY.get(module, module)]
    entries: list[dict] = []
    for key in keys:
        p = log_dir / f"{key}.log"
        if not p.is_file() or p.stat().st_size <= 0:
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        entries.extend(_parse_log_entries(key, raw, p.stat().st_mtime))

    # Optional: one blob for active release.sh run (mtime-based)
    if module in {None, "", "all", "*"}:
        dep = _read_deploy_status()
        rel = dep.get("log_file") or ""
        if rel:
            p = STATUS_DIR / rel
            if p.is_file() and p.stat().st_size > 0:
                mt = p.stat().st_mtime
                body = p.read_text(encoding="utf-8", errors="replace")[-8_000:].strip()
                entries.append(
                    {
                        "ts": _fmt_local(mt),
                        "ts_epoch": mt,
                        "module": f"release:{Path(rel).name}",
                        "title": "release.sh run",
                        "body": body,
                    }
                )
    return entries


def _format_timeline(entries: list[dict], *, log_key: str) -> str:
    if not entries:
        return (
            f"（尚无「{log_key}」任务日志）\n"
            "有输出后形如：[2026-08-07 12:00:00] 内容"
        )
    entries = sorted(entries, key=lambda e: float(e["ts_epoch"]), reverse=True)
    lines: list[str] = []
    for i, e in enumerate(entries):
        tag = e["ts"]  # YYYY-MM-DD HH:MM:SS
        mod = e.get("module") or log_key
        title = (e.get("title") or "").strip()
        body = (e.get("body") or "").rstrip()
        newest = " (最新)" if i == 0 else ""
        # 段头一行
        head = f"[{tag}]{newest} [{mod}]"
        if title and title not in {"(无输出)", "（整文件，无分段时间戳）"}:
            head = f"{head} {title}"
        lines.append(head)
        if body:
            for raw in body.splitlines():
                # 正文每行也带同一时间戳，方便扫读
                lines.append(f"[{tag}] {raw}")
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > 48_000:
        text = "…(截断更早记录)…\n" + text[:48_000]
    return text


def _read_module_log(module: str) -> dict:
    """Return timeline text for one module/item id, or combined ``all``."""
    key = "all" if module in {"all", "*"} else ITEM_LOG_KEY.get(module, module)
    entries = _collect_entries(module)
    return {
        "module": module,
        "log_key": key,
        "newest_ts": entries and max(entries, key=lambda e: e["ts_epoch"])["ts"] or None,
        "count": len(entries),
        "text": _format_timeline(entries, log_key=key),
    }


def _clear_logs(module: str) -> dict:
    """Clear managed console logs. module=all clears every managed file."""
    mod = (module or "").strip() or "all"
    if mod in {"all", "*"}:
        targets = list(_MANAGED_LOG_KEYS)
    else:
        key = ITEM_LOG_KEY.get(mod, mod)
        if key not in _MANAGED_LOG_KEYS and key != "misc":
            return {"ok": False, "error": f"unknown log module: {mod}"}
        targets = [key]

    log_dir = STATUS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    cleared: list[str] = []
    for key in targets:
        p = log_dir / f"{key}.log"
        if p.is_file():
            p.write_text("", encoding="utf-8")
            cleared.append(key)
        else:
            # touch empty so UI stays consistent
            p.write_text("", encoding="utf-8")
            cleared.append(key)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    return {"ok": True, "cleared": cleared, "at": stamp, "module": mod}


def _list_module_logs() -> dict:
    keys = ("git", "api", "runtime", "web", "gateway", "index_product", "index_ops")
    modules: dict = {}
    any_has = False
    newest = 0.0
    for key in keys:
        p = STATUS_DIR / "logs" / f"{key}.log"
        has = p.is_file() and p.stat().st_size > 0
        any_has = any_has or has
        mt = p.stat().st_mtime if p.is_file() else None
        if mt and mt > newest:
            newest = mt
        modules[key] = {
            "has_log": has,
            "bytes": (p.stat().st_size if p.is_file() else 0),
            "mtime": mt,
            "mtime_label": _fmt_local(mt) if mt else None,
        }
    modules["all"] = {
        "has_log": any_has,
        "bytes": sum(m["bytes"] for m in modules.values()),
        "mtime": newest or None,
        "mtime_label": _fmt_local(newest) if newest else None,
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
                mode = _norm_mode((qs.get("mode") or ["local"])[0])
                self._send_json(200, _snapshot(force=force, mode=mode))
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"summary": "error", "headline": str(exc), "items": []})
            return
        if path == "/api/logs":
            self._send_json(200, _list_module_logs())
            return
        if path == "/api/log":
            qs = parse_qs(urlparse(self.path).query)
            module = (qs.get("module") or qs.get("item") or ["all"])[0].strip() or "all"
            self._send_json(200, _read_module_log(module))
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

        if path == "/api/log/clear":
            if not _authorize(self):
                return
            module = str(body.get("module") or "all").strip() or "all"
            result = _clear_logs(module)
            code = 200 if result.get("ok") else 400
            self._send_json(code, result)
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
