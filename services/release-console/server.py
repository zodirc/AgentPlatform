#!/usr/bin/env python3
"""Release console — per-module health + one-click actions.

Left: each module/row has its own action. Right: detail board.
Auto-refreshes; no manual「刷新检查」. Loopback may skip secret.
"""

from __future__ import annotations

import json
import os
import re
import signal
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
    "up-ast-indexer": ["bash", str(RELEASE_SH), "run", "--modules=ast_indexer"],
    "up-web": ["bash", str(RELEASE_SH), "run", "--modules=web"],
    "up-gateway": ["bash", str(RELEASE_SH), "run", "--modules=gateway"],
    "up-all": ["bash", str(RELEASE_SH), "run", "--force-all"],
    "sync-sources": ["make", "-C", str(ROOT), "sync-sources"],
    "sync-ops-indexes": ["make", "-C", str(ROOT), "sync-ops-indexes"],
    "sync-ops-cmteb": ["make", "-C", str(ROOT), "sync-ops-cmteb"],
    "ensure-ops-cmteb": ["bash", str(ROOT / "scripts" / "release" / "ensure_ops_cmteb.sh")],
    "pull-swe-eval-images": ["make", "-C", str(ROOT), "official-bench-coding-pull-images"],
    "start-bench": ["make", "-C", str(ROOT), "start-bench"],
    "up-bench": ["make", "-C", str(ROOT), "up-bench"],
    "git-pull": ["bash", str(GIT_PULL_SH)],
    "cancel-jobs": ["__cancel__"],  # handled in-process, not spawned
    "restart-console": ["__restart__"],  # detach stop+ensure; not queued
}

# Console action / plan item id → per-module log stem under logs/
ACTION_LOG_KEY = {
    "up-api": "api",
    "up-runtime": "runtime",
    "up-ast-indexer": "ast_indexer",
    "up-web": "web",
    "up-gateway": "gateway",
    "up-all": "misc",
    "sync-sources": "index_product",
    "sync-ops-indexes": "index_ops",
    "sync-ops-cmteb": "index_ops_zh",
    "ensure-ops-cmteb": "index_ops_zh",
    "pull-swe-eval-images": "swe_eval_images",
    "start-bench": "ops_bench",
    "up-bench": "ops_bench",
    "git-pull": "git",
    "cancel-jobs": "misc",
    "restart-console": "misc",
}
ITEM_LOG_KEY = {
    "api": "api",
    "runtime": "runtime",
    "ast_indexer": "ast_indexer",
    "web": "web",
    "gateway": "gateway",
    "embedding": "runtime",  # 换模走 runtime 重建
    "ops_embedding_ref": "runtime",
    "index_product": "index_product",
    "index_ops": "index_ops",
    "index_ops_zh": "index_ops_zh",
    "swe_eval_images": "swe_eval_images",
    "ops_bench": "ops_bench",
    "git": "git",
}

# Actions that must not double-spawn while a matching job/sync is live.
_ACTION_ITEM = {
    "up-api": "api",
    "up-runtime": "runtime",
    "up-ast-indexer": "ast_indexer",
    "up-web": "web",
    "up-gateway": "gateway",
    "up-all": "api",  # attach if any deploy live; cancel covers all
    "sync-sources": "index_product",
    "sync-ops-indexes": "index_ops",
    "sync-ops-cmteb": "index_ops_zh",
    "ensure-ops-cmteb": "index_ops_zh",
    "pull-swe-eval-images": "swe_eval_images",
    "start-bench": "ops_bench",
    "up-bench": "ops_bench",
    "git-pull": "git",
}
_ITEM_DEFAULT_ACTION = {
    "api": "up-api",
    "runtime": "up-runtime",
    "ast_indexer": "up-ast-indexer",
    "web": "up-web",
    "gateway": "up-gateway",
    "index_product": "sync-sources",
    "index_ops": "sync-ops-indexes",
    "index_ops_zh": "ensure-ops-cmteb",
    "swe_eval_images": "pull-swe-eval-images",
    "ops_bench": "start-bench",
}
_SYNC_ACTIVE = frozenset(
    {
        "starting",
        "prepare",
        "loading_embedder",
        "scope",
        "scan",
        "chunk",
        "plan",
        "embed",
        "write",
        "index",
    }
)
_jobs_lock = threading.Lock()
_JOBS_FILE = STATUS_DIR / "jobs.json"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _load_jobs() -> list[dict]:
    if not _JOBS_FILE.is_file():
        return []
    try:
        data = json.loads(_JOBS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save_jobs(jobs: list[dict]) -> None:
    try:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        _JOBS_FILE.write_text(
            json.dumps(jobs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _reap_jobs() -> list[dict]:
    with _jobs_lock:
        alive = [j for j in _load_jobs() if _pid_alive(int(j.get("pid") or 0))]
        _save_jobs(alive)
        return alive


def _register_job(*, action: str, pid: int, log_key: str) -> None:
    with _jobs_lock:
        jobs = [j for j in _load_jobs() if _pid_alive(int(j.get("pid") or 0))]
        jobs.append(
            {
                "action": action,
                "pid": int(pid),
                "log_key": log_key,
                "item_id": _ACTION_ITEM.get(action),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        _save_jobs(jobs)


# --- serial action queue (deploy + index + cancel) ---------------------------------
_QUEUE_FILE = STATUS_DIR / "queue.json"
_queue_lock = threading.Lock()
_queue_cv = threading.Condition(_queue_lock)
_queue_state: dict = {"items": [], "seq": 0}
_queue_abort = False
_queue_current_pid: int | None = None
_queue_worker_started = False

_ACTION_LABELS = {
    "up-api": "重建 api",
    "up-runtime": "重建 runtime",
    "up-ast-indexer": "重建 ast_indexer",
    "up-web": "重建 web",
    "up-gateway": "重建 gateway",
    "up-all": "全部重建",
    "sync-sources": "同步产品索引",
    "sync-ops-indexes": "同步 Ops BEIR",
    "sync-ops-cmteb": "同步 C-MTEB",
    "ensure-ops-cmteb": "拉取并嵌入中文库",
    "pull-swe-eval-images": "预拉 SWE eval 镜像",
    "start-bench": "启动 Ops Bench",
    "up-bench": "重建 Ops Bench",
    "git-pull": "拉取远程",
    "cancel-jobs": "取消任务",
    "restart-console": "重启看板",
}


def _schedule_console_restart() -> dict:
    """Detach stop+ensure so the HTTP reply finishes before this process dies."""
    script = ROOT / "scripts" / "release" / "restart_console.sh"
    if not script.is_file():
        return {"ok": False, "error": "restart_console.sh missing"}
    log_dir = STATUS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "misc.log"
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(f"\n[{stamp}] restart-console scheduled from API\n")
    except OSError:
        pass
    try:
        logf = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 — kept for child lifetime
    except OSError:
        logf = subprocess.DEVNULL
    env = os.environ.copy()
    env["RELEASE_CONSOLE"] = "1"
    try:
        subprocess.Popen(
            ["bash", str(script)],
            cwd=str(ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
            close_fds=logf is subprocess.DEVNULL,
        )
    except OSError as exc:
        if logf is not subprocess.DEVNULL:
            try:
                logf.close()
            except OSError:
                pass
        return {"ok": False, "error": f"failed to spawn restart: {exc}"}
    return {
        "ok": True,
        "restarting": True,
        "queued": False,
        "attached": False,
        "action": "restart-console",
        "message": "看板即将重启（约 1–3 秒），页面会自动刷新",
    }


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _queue_save_unlocked() -> None:
    try:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        _QUEUE_FILE.write_text(
            json.dumps(_queue_state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _queue_trim_unlocked() -> None:
    items = _queue_state["items"]
    active = [i for i in items if i.get("status") in {"pending", "running"}]
    done = [i for i in items if i.get("status") not in {"pending", "running"}]
    _queue_state["items"] = done[-30:] + active


def _queue_load_disk() -> None:
    global _queue_state
    if not _QUEUE_FILE.is_file():
        return
    try:
        raw = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict):
        return
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    fixed: list[dict] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("action"):
            continue
        row = dict(it)
        # Console restart: resume interrupted running items.
        if row.get("status") == "running":
            row["status"] = "pending"
            row.pop("started_at", None)
            row["message"] = "控制台重启后重新排队"
        if row.get("status") in {"pending", "done", "error", "cancelled"}:
            fixed.append(row)
    seq = int(raw.get("seq") or 0)
    for row in fixed:
        try:
            n = int(str(row.get("id") or "").lstrip("q") or 0)
            seq = max(seq, n)
        except ValueError:
            pass
    with _queue_cv:
        _queue_state = {"items": fixed, "seq": seq}
        _queue_trim_unlocked()
        _queue_save_unlocked()


def _queue_public() -> dict:
    with _queue_lock:
        items = [dict(i) for i in _queue_state["items"]]
    pending = [i for i in items if i.get("status") in {"pending", "running"}]
    recent = [i for i in items if i.get("status") not in {"pending", "running"}][-8:]
    bits = []
    for i in pending:
        mark = "▶" if i.get("status") == "running" else "等待"
        bits.append(f"{mark} {i.get('label') or i.get('action')}")
    return {
        "pending": pending,
        "recent": recent,
        "summary": " → ".join(bits) if bits else "",
        "count": len(pending),
    }


def _queue_finish_unlocked(qid: str, status: str, message: str = "") -> None:
    for i in _queue_state["items"]:
        if i.get("id") == qid:
            i["status"] = status
            i["finished_at"] = _utc_now()
            if message:
                i["message"] = message
            break
    _queue_trim_unlocked()
    _queue_save_unlocked()


def _enqueue_action(action: str) -> dict:
    """Append to serial queue. cancel-jobs clears pending and aborts current."""
    global _queue_abort, _queue_current_pid

    label = _ACTION_LABELS.get(action, action)
    kill_pid: int | None = None

    with _queue_cv:
        items = _queue_state["items"]

        if action == "cancel-jobs":
            if any(
                i.get("action") == "cancel-jobs" and i.get("status") == "pending"
                for i in items
            ):
                return {
                    "ok": True,
                    "queued": True,
                    "already": True,
                    "action": action,
                    "queue": _queue_public_unlocked(items),
                    "message": "取消已在队列中",
                }
            if any(
                i.get("action") == "cancel-jobs" and i.get("status") == "running"
                for i in items
            ):
                return {
                    "ok": True,
                    "attached": True,
                    "queued": False,
                    "action": action,
                    "queue": _queue_public_unlocked(items),
                    "message": "正在执行取消",
                }
            new_items: list[dict] = []
            for i in items:
                st = i.get("status")
                if st == "pending":
                    row = dict(i)
                    row["status"] = "cancelled"
                    row["finished_at"] = _utc_now()
                    row["message"] = "入队取消时清除"
                    new_items.append(row)
                else:
                    new_items.append(i)
            _queue_state["seq"] = int(_queue_state.get("seq") or 0) + 1
            item = {
                "id": f"q{_queue_state['seq']}",
                "action": action,
                "label": label,
                "status": "pending",
                "enqueued_at": _utc_now(),
            }
            new_items.append(item)
            _queue_state["items"] = new_items
            _queue_abort = True
            kill_pid = _queue_current_pid
            _queue_trim_unlocked()
            _queue_save_unlocked()
            _queue_cv.notify_all()
            qpub = _queue_public_unlocked(_queue_state["items"])
        else:
            for i in items:
                if i.get("action") == action and i.get("status") == "running":
                    return {
                        "ok": True,
                        "attached": True,
                        "queued": False,
                        "action": action,
                        "item": dict(i),
                        "queue": _queue_public_unlocked(items),
                        "message": f"已在执行 · {label}",
                    }
                if i.get("action") == action and i.get("status") == "pending":
                    return {
                        "ok": True,
                        "queued": True,
                        "already": True,
                        "action": action,
                        "item": dict(i),
                        "queue": _queue_public_unlocked(items),
                        "message": f"已在队列中 · {label}",
                    }
            _queue_state["seq"] = int(_queue_state.get("seq") or 0) + 1
            item = {
                "id": f"q{_queue_state['seq']}",
                "action": action,
                "label": label,
                "status": "pending",
                "enqueued_at": _utc_now(),
            }
            items.append(item)
            _queue_trim_unlocked()
            _queue_save_unlocked()
            _queue_cv.notify_all()
            qpub = _queue_public_unlocked(_queue_state["items"])

    if kill_pid:
        _kill_pid_tree(int(kill_pid))

    return {
        "ok": True,
        "queued": True,
        "attached": False,
        "already": False,
        "action": action,
        "item": item,
        "queue": qpub,
        "message": f"已入队 · {label}",
    }


def _queue_public_unlocked(items: list[dict]) -> dict:
    pending = [dict(i) for i in items if i.get("status") in {"pending", "running"}]
    recent = [dict(i) for i in items if i.get("status") not in {"pending", "running"}][-8:]
    bits = []
    for i in pending:
        mark = "▶" if i.get("status") == "running" else "等待"
        bits.append(f"{mark} {i.get('label') or i.get('action')}")
    return {
        "pending": pending,
        "recent": recent,
        "summary": " → ".join(bits) if bits else "",
        "count": len(pending),
    }


def _queue_worker_loop() -> None:
    global _queue_abort, _queue_current_pid
    while True:
        with _queue_cv:
            item = None
            while True:
                for i in _queue_state["items"]:
                    if i.get("status") == "pending":
                        item = i
                        break
                if item is not None:
                    break
                _queue_cv.wait(timeout=5.0)
            qid = str(item.get("id"))
            action = str(item.get("action") or "")
            for i in _queue_state["items"]:
                if i.get("id") == qid:
                    i["status"] = "running"
                    i["started_at"] = _utc_now()
                    i.pop("message", None)
                    break
            _queue_abort = False
            _queue_save_unlocked()

        _plan_cache["at"] = 0.0

        if action == "cancel-jobs":
            try:
                result = _cancel_all_jobs()
                msg = str(result.get("message") or "已取消")
                st = "done" if result.get("ok") else "error"
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                st = "error"
            with _queue_cv:
                _queue_finish_unlocked(qid, st, msg)
                _queue_abort = False
                _queue_current_pid = None
                _queue_cv.notify_all()
            _plan_cache["at"] = 0.0
            continue

        cmd = ALLOWED_ACTIONS.get(action)
        if not cmd or cmd in (["__cancel__"], ["__restart__"]):
            with _queue_cv:
                _queue_finish_unlocked(qid, "error", f"unknown action {action}")
                _queue_cv.notify_all()
            continue

        # Serial with release.lock: wait out any orphan/outside deploy before up-*.
        if action.startswith("up-"):
            waited_out = False
            deadline = time.time() + 2 * 60 * 60
            while time.time() < deadline:
                with _queue_cv:
                    if _queue_abort:
                        waited_out = True
                        break
                if not _release_deploy_alive():
                    break
                time.sleep(1.0)
            else:
                with _queue_cv:
                    _queue_finish_unlocked(qid, "error", "等待发布锁超时")
                    _queue_cv.notify_all()
                continue
            if waited_out:
                with _queue_cv:
                    _queue_finish_unlocked(qid, "cancelled", "已中止")
                    _queue_abort = False
                    _queue_cv.notify_all()
                continue

        try:
            proc = _spawn(cmd, action=action)
        except Exception as exc:  # noqa: BLE001
            with _queue_cv:
                _queue_finish_unlocked(qid, "error", str(exc))
                _queue_cv.notify_all()
            continue

        with _queue_cv:
            _queue_current_pid = int(proc.pid)

        aborted = False
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            with _queue_cv:
                aborted = _queue_abort
            if aborted:
                _kill_pid_tree(int(proc.pid))
                try:
                    proc.wait(timeout=8)
                except Exception:  # noqa: BLE001
                    pass
                break
            time.sleep(0.45)

        with _queue_cv:
            aborted = aborted or _queue_abort
            _queue_current_pid = None
            if aborted:
                _queue_finish_unlocked(qid, "cancelled", "已中止")
                _queue_abort = False
            elif int(proc.returncode or 0) == 0:
                _queue_finish_unlocked(qid, "done", "完成")
            else:
                _queue_finish_unlocked(
                    qid, "error", f"退出码 {proc.returncode}"
                )
            _queue_cv.notify_all()
        # Drop cached plan so the next poll cannot keep「存在变动」after a successful up-*.
        _plan_cache["at"] = 0.0
        _plan_cache["data"] = None
        if (not aborted) and int(proc.returncode or 0) == 0 and action.startswith("up-"):
            try:
                mode = _norm_mode(os.environ.get("RELEASE_DETECT_MODE"))
                _compute_plan(mode=mode)
            except Exception:  # noqa: BLE001
                pass


def _ensure_queue_worker() -> None:
    global _queue_worker_started
    with _queue_lock:
        if _queue_worker_started:
            return
        _queue_worker_started = True
    _queue_load_disk()
    threading.Thread(
        target=_queue_worker_loop, daemon=True, name="release-queue"
    ).start()


def _internal_token() -> str:
    tok = (os.environ.get("INTERNAL_SERVICE_TOKEN") or "").strip()
    if tok:
        return tok
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("INTERNAL_SERVICE_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'").strip('"')
    return ""


def _cancel_runtime_sync() -> dict:
    """Ask runtime to abort in-flight sources/ops index sync."""
    token = _internal_token()
    if not token:
        return {"ok": False, "error": "INTERNAL_SERVICE_TOKEN missing"}
    try:
        out = subprocess.check_output(
            [
                "docker",
                "exec",
                "-e",
                f"INTERNAL_SERVICE_TOKEN={token}",
                "agent-runtime",
                "python",
                "-c",
                (
                    "import os,urllib.request;"
                    "req=urllib.request.Request("
                    "'http://127.0.0.1:8001/internal/commands/cancel-sources-index',"
                    "data=b'',method='POST',"
                    "headers={'X-Internal-Token':os.environ['INTERNAL_SERVICE_TOKEN'],"
                    "'Accept':'application/json'});"
                    "print(urllib.request.urlopen(req,timeout=8).read().decode())"
                ),
            ],
            stderr=subprocess.STDOUT,
            timeout=15,
        )
        raw = out.decode("utf-8", errors="replace").strip()
        try:
            return {"ok": True, "result": json.loads(raw)}
        except json.JSONDecodeError:
            return {"ok": True, "raw": raw[-500:]}
    except (subprocess.SubprocessError, OSError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}


def _kill_pid_tree(pid: int) -> bool:
    if pid <= 0 or not _pid_alive(pid):
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return False
    time.sleep(0.4)
    if _pid_alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                return False
    return True


_ACTIVE_DEPLOY_PHASES = frozenset({"detecting", "building", "switching", "verifying"})
_status_write_lock = threading.Lock()


def _write_deploy_status(dep: dict) -> None:
    with _status_write_lock:
        try:
            STATUS_DIR.mkdir(parents=True, exist_ok=True)
            STATUS_FILE.write_text(
                json.dumps(dep, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass


def _release_deploy_alive() -> bool:
    """True iff release.sh (or equivalent up-*) still holds the deploy."""
    lock = STATUS_DIR / "release.lock"
    if lock.is_file():
        try:
            raw = lock.read_text(encoding="utf-8").strip()
            pid = int(raw) if raw.isdigit() else 0
        except (OSError, ValueError):
            pid = 0
        if pid > 0 and _pid_alive(pid):
            return True
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass
    for job in _discover_host_action_jobs():
        act = str(job.get("action") or "")
        if act.startswith("up-"):
            return True
    return False


def _mark_deploy_aborted(reason: str) -> dict:
    """Force status.json out of building/switching after cancel or orphan detect."""
    dep: dict = {}
    if STATUS_FILE.is_file():
        try:
            raw = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                dep = raw
        except (OSError, json.JSONDecodeError):
            dep = {}
    phase = str(dep.get("phase") or "")
    if phase not in _ACTIVE_DEPLOY_PHASES:
        return dep
    healed = dict(dep)
    healed["phase"] = "failed"
    healed["message"] = reason
    healed["error"] = reason
    healed["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_deploy_status(healed)
    return healed


def _heal_stale_deploy(dep: dict) -> dict:
    """If status says deploying but no process/lock, reset — avoids sticky busy UI."""
    if not isinstance(dep, dict):
        return {"phase": "idle", "message": "", "changed": [], "deployed": {}}
    phase = str(dep.get("phase") or "")
    if phase not in _ACTIVE_DEPLOY_PHASES:
        return dep
    if _release_deploy_alive():
        return dep
    return _mark_deploy_aborted("发布已中断（无活动进程），状态已复位")


def _cancel_all_jobs() -> dict:
    """Stop console-spawned / discovered rebuild+sync work and runtime embed."""
    killed: list[dict] = []
    seen: set[int] = set()
    for job in list(_reap_jobs()) + _discover_host_action_jobs():
        pid = int(job.get("pid") or 0)
        if pid <= 0 or pid in seen:
            continue
        seen.add(pid)
        if _kill_pid_tree(pid):
            killed.append(
                {
                    "pid": pid,
                    "action": job.get("action"),
                    "item_id": job.get("item_id"),
                }
            )
    # Orphan docker pull (make killed but pull reparented) — kill explicitly.
    for pid in _discover_swe_pull_pids():
        if pid in seen:
            continue
        seen.add(pid)
        if _kill_pid_tree(pid):
            killed.append(
                {
                    "pid": pid,
                    "action": "pull-swe-eval-images",
                    "item_id": "swe_eval_images",
                }
            )
    _mark_swe_images_progress_cancelled("已取消预拉")
    with _jobs_lock:
        _save_jobs([])

    # Release modular deploy lock holder (release.sh run / up).
    lock = STATUS_DIR / "release.lock"
    release_killed = False
    if lock.is_file():
        try:
            raw = lock.read_text(encoding="utf-8").strip()
            rpid = int(raw) if raw.isdigit() else 0
        except (OSError, ValueError):
            rpid = 0
        if rpid and rpid not in seen and _kill_pid_tree(rpid):
            killed.append({"pid": rpid, "action": "release", "item_id": None})
            release_killed = True
            seen.add(rpid)
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass

    _mark_deploy_aborted("已取消")

    sync = _cancel_runtime_sync()
    # Append a timeline breadcrumb.
    log_dir = STATUS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    note = (
        f"\n==> {stamp} [misc] cancel-jobs "
        f"killed={len(killed)} sync_ok={bool(sync.get('ok'))} "
        f"release_lock={release_killed}\n"
    )
    try:
        with (log_dir / "misc.log").open("a", encoding="utf-8") as fh:
            fh.write(note)
            for row in killed:
                fh.write(f"  - pid={row.get('pid')} action={row.get('action')}\n")
    except OSError:
        pass

    return {
        "ok": True,
        "killed": killed,
        "sync": sync,
        "release_lock_cleared": release_killed or not lock.is_file(),
        "message": (
            f"已取消 {len(killed)} 个进程"
            + (" · 已请求停止索引" if sync.get("ok") else " · 索引取消失败/无任务")
        ),
    }


def _discover_host_action_jobs() -> list[dict]:
    """Find long-running make/ensure/sync processes even after console restart."""
    # (substring in cmdline, action, item_id)
    patterns = (
        ("ensure_ops_cmteb.sh", "ensure-ops-cmteb", "index_ops_zh"),
        ("sync_cli --mode ops-cmteb", "sync-ops-cmteb", "index_ops_zh"),
        ("--mode ops-cmteb", "sync-ops-cmteb", "index_ops_zh"),
        ("sync_cli --mode ops-beir", "sync-ops-indexes", "index_ops"),
        ("--mode ops-beir", "sync-ops-indexes", "index_ops"),
        ("sync_cli --mode sources", "sync-sources", "index_product"),
        ("official-bench-coding-pull-images", "pull-swe-eval-images", "swe_eval_images"),
        ("coding --phase pull-images", "pull-swe-eval-images", "swe_eval_images"),
        ("docker pull swebench/sweb.eval", "pull-swe-eval-images", "swe_eval_images"),
        ("docker pull ", "pull-swe-eval-images", "swe_eval_images"),  # filtered: only sweb.eval
        ("start-bench", "start-bench", "ops_bench"),
        ("up-bench", "up-bench", "ops_bench"),
        ("COMPOSE_PROFILES=bench", "up-bench", "ops_bench"),
        ("release.sh run --modules=api", "up-api", "api"),
        ("release.sh run --modules=runtime", "up-runtime", "runtime"),
        ("release.sh run --modules=ast_indexer", "up-ast-indexer", "ast_indexer"),
        ("release.sh run --modules=web", "up-web", "web"),
        ("release.sh run --modules=gateway", "up-gateway", "gateway"),
        ("release.sh run --force-all", "up-all", "api"),
        ("release.sh up", "up-all", "api"),
        ("make up-ast-indexer", "up-ast-indexer", "ast_indexer"),
    )
    found: list[dict] = []
    try:
        my_pid = os.getpid()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == my_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
            if not cmd.strip():
                continue
            for needle, action, item_id in patterns:
                if needle not in cmd:
                    continue
                # Generic docker-pull needle must still be an SWE eval image.
                if needle == "docker pull " and "sweb.eval" not in cmd:
                    continue
                found.append(
                    {
                        "action": action,
                        "pid": pid,
                        "log_key": ACTION_LOG_KEY.get(action, "misc"),
                        "item_id": item_id,
                        "started_at": None,
                        "source": "host-proc",
                    }
                )
                break
    except OSError:
        pass
    # Dedup by item_id for UI attach; cancel path also scans SWE pulls separately.
    by_item: dict[str, dict] = {}
    for job in sorted(found, key=lambda j: int(j["pid"])):
        iid = str(job.get("item_id") or "")
        if iid and iid not in by_item:
            by_item[iid] = job
    return list(by_item.values())


def _iter_host_cmdlines() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    my_pid = os.getpid()
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == my_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
            if cmd.strip():
                out.append((pid, cmd))
    except OSError:
        pass
    return out


def _discover_swe_pull_pids() -> list[int]:
    """All PIDs related to SWE eval image pull (make + orphan docker pull)."""
    needles = (
        "official-bench-coding-pull-images",
        "coding --phase pull-images",
        "sweb.eval",
    )
    pids: list[int] = []
    for pid, cmd in _iter_host_cmdlines():
        if "docker pull" in cmd and "sweb.eval" in cmd:
            pids.append(pid)
            continue
        if any(n in cmd for n in needles[:2]):
            pids.append(pid)
    return pids


def _mark_swe_images_progress_cancelled(reason: str = "已取消") -> None:
    """Clear sticky 看板 live strip after cancel / orphan pull."""
    path = STATUS_DIR / "swe_eval_images_progress.json"
    prev: dict = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                prev = raw
        except (OSError, json.JSONDecodeError):
            prev = {}
    st = str(prev.get("status") or "")
    last = str(prev.get("last_status") or "")
    if st in {"ready", "cancelled"} and last != "pulling":
        return
    body = {
        **{k: prev.get(k) for k in ("tier", "images_total", "images_done", "current_ref", "current_short")},
        "status": "cancelled",
        "phase": "cancelled",
        "last_status": "cancelled",
        "error": reason,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _read_runtime_sync_progress() -> dict | None:
    """Best-effort: sync_progress.json inside agent-runtime (/data volume)."""
    try:
        out = subprocess.check_output(
            [
                "docker",
                "exec",
                "agent-runtime",
                "cat",
                "/data/vectorstore/sync_progress.json",
            ],
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None
    try:
        data = json.loads(out.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sync_progress_fresh(prog: dict, *, max_age_s: float = 180.0) -> bool:
    """True when progress looks recently updated (avoid attaching to a dead hang)."""
    raw = str(prog.get("updated_at") or "").strip()
    if not raw:
        return False
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (time.time() - dt.timestamp()) <= max_age_s
    except Exception:
        return False


def _sync_item_id(prog: dict) -> str | None:
    path = str(prog.get("path") or "")
    reason = str(prog.get("reason") or "").lower()
    if "cmteb" in path.lower() or "cmteb" in reason or "ops-cmteb" in reason:
        return "index_ops_zh"
    if "beir-index" in path or "ops-beir" in reason or "make-ops-beir" in reason:
        return "index_ops"
    if path.startswith("ops-l1") or "/ops-l1/" in path:
        return "index_ops"
    return "index_product"


def _sync_summary(prog: dict) -> tuple[str, float | None]:
    phase = str(prog.get("phase") or "")
    path = str(prog.get("path") or "")
    short = path
    for token in ("/data/", "ops-l1/"):
        if token in short:
            short = short.split(token, 1)[-1]
    short = short[-48:] if len(short) > 48 else short
    pct: float | None = None
    chunk_bit = file_bit = ""
    try:
        done, total = prog.get("chunks_embedded"), prog.get("chunks_total")
        if done is not None and total is not None and int(total) > 0:
            pct = round(100.0 * int(done) / int(total), 1)
            chunk_bit = f"{int(done)}/{int(total)}块"
        fd, ft = prog.get("files_done"), prog.get("files_total")
        if fd is not None and ft is not None and int(ft) > 0:
            file_bit = f"{int(fd)}/{int(ft)}文件"
            if pct is None:
                pct = round(100.0 * int(fd) / int(ft), 1)
    except (TypeError, ValueError):
        pct = None
    bits = [f"同步·{phase or 'running'}"]
    if short:
        bits.append(short)
    try:
        st = prog.get("scopes_total")
        if st is not None and int(st) > 0:
            bits.append(f"库{int(prog.get('scopes_done') or 0)}/{int(st)}")
    except (TypeError, ValueError):
        pass
    if pct is not None:
        bits.append(f"{pct}%")
    if chunk_bit:
        bits.append(chunk_bit)
    elif file_bit:
        bits.append(file_bit)
    try:
        rate = prog.get("rate_chunks_per_s")
        if rate is not None and float(rate) > 0:
            r = float(rate)
            bits.append(f"{r:.0f}/s" if r >= 10 else f"{r:.1f}/s")
        eta = prog.get("eta_s")
        if eta is not None and float(eta) > 1:
            bits.append(f"ETA {int(float(eta))}s")
    except (TypeError, ValueError):
        pass
    return " · ".join(bits), pct


def _read_swe_eval_images_progress() -> dict | None:
    """Progress written by official_bench.swe_images during board/make pull."""
    path = STATUS_DIR / "swe_eval_images_progress.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _swe_eval_images_summary(prog: dict) -> tuple[str, float | None]:
    total = prog.get("images_total")
    done = prog.get("images_done")
    layer_pct = prog.get("layer_pct")
    pct: float | None = None
    try:
        if total is not None and int(total) > 0 and done is not None:
            base = float(int(done))
            # Blend in-image layer progress so the bar moves during a long pull.
            try:
                frac = max(0.0, min(1.0, float(layer_pct) / 100.0)) if layer_pct is not None else 0.0
            except (TypeError, ValueError):
                frac = 0.0
            if int(done) < int(total):
                pct = round(100.0 * (base + frac) / int(total), 1)
            else:
                pct = 100.0
    except (TypeError, ValueError):
        pct = None
    status = str(prog.get("status") or "")
    last = str(prog.get("last_status") or "")
    short = str(prog.get("current_short") or prog.get("current_ref") or "").strip()
    if short and "/" in short:
        short = short.rsplit("/", 1)[-1]
    if len(short) > 40:
        short = short[-40:]
    bits: list[str] = []
    if status == "error":
        bits.append("预拉失败")
        err = str(prog.get("error") or "").strip()
        if err:
            bits.append(err[:80])
    elif status == "ready" or last == "finished":
        bits.append("预拉完成")
    else:
        bits.append("预拉镜像")
        if last == "pulling":
            bits.append("下载中")
        elif last == "cached":
            bits.append("已缓存跳过")
        elif last == "pulled":
            bits.append("已拉取")
    try:
        if total is not None and done is not None:
            bits.append(f"{int(done)}/{int(total)}")
    except (TypeError, ValueError):
        pass
    if pct is not None:
        bits.append(f"{pct}%")
    speed = str(prog.get("speed_label") or "").strip()
    detail = str(prog.get("layer_detail") or "").strip()
    # Prefer explicit speed up front (网速感); skip if already inside layer_detail.
    if (
        speed
        and last == "pulling"
        and status not in {"ready"}
        and speed not in detail
    ):
        bits.append(speed)
    if detail and status not in {"ready"} and last != "finished":
        bits.append(detail)
    elif layer_pct is not None and last == "pulling":
        bits.append(f"本图 {layer_pct}%")
    if short and status not in {"ready"} and last != "finished":
        bits.append(short)
    try:
        cached = prog.get("images_cached")
        pulled = prog.get("images_pulled")
        if cached is not None or pulled is not None:
            bits.append(f"cache {int(cached or 0)} · pull {int(pulled or 0)}")
    except (TypeError, ValueError):
        pass
    return " · ".join(bits), pct


def _collect_live() -> dict[str, dict]:
    """item_id → live job descriptor (console pid and/or runtime sync / deploy)."""
    out: dict[str, dict] = {}

    for job in list(_reap_jobs()) + _discover_host_action_jobs():
        item_id = str(job.get("item_id") or _ACTION_ITEM.get(str(job.get("action") or "")) or "")
        if not item_id:
            continue
        action = str(job.get("action") or _ITEM_DEFAULT_ACTION.get(item_id) or "")
        # Prefer already-recorded console job over rediscovered host proc.
        if item_id in out and out[item_id].get("source") == "console":
            continue
        out[item_id] = {
            "item_id": item_id,
            "action": action,
            "kind": "job",
            "pid": job.get("pid"),
            "summary": f"任务进行中 · {action} (pid {job.get('pid')})",
            "pct": None,
            "source": job.get("source") or "console",
        }

    # Overlay structured SWE image pull progress onto a live pull job only.
    # Never invent "进行中" from a stale progress file alone (cancel must clear UI).
    swe_prog = _read_swe_eval_images_progress()
    if isinstance(swe_prog, dict):
        st = str(swe_prog.get("status") or "")
        phase = str(swe_prog.get("phase") or "")
        last = str(swe_prog.get("last_status") or "")
        active = st == "building" or phase == "pull" or last == "pulling"
        if (
            "swe_eval_images" in out
            and active
            and st not in {"ready", "error", "cancelled"}
            and _sync_progress_fresh(swe_prog, max_age_s=900.0)
        ):
            summary, pct = _swe_eval_images_summary(swe_prog)
            prev = out["swe_eval_images"]
            out["swe_eval_images"] = {
                "item_id": "swe_eval_images",
                "action": prev.get("action") or "pull-swe-eval-images",
                "kind": "swe_images",
                "pid": prev.get("pid"),
                "summary": summary,
                "pct": pct,
                "source": prev.get("source") or "progress",
            }
        elif st == "error" and _sync_progress_fresh(swe_prog, max_age_s=120.0):
            summary, pct = _swe_eval_images_summary(swe_prog)
            if "swe_eval_images" not in out:
                out["swe_eval_images"] = {
                    "item_id": "swe_eval_images",
                    "action": "pull-swe-eval-images",
                    "kind": "swe_images",
                    "pid": None,
                    "summary": summary,
                    "pct": pct,
                    "source": "progress",
                }
        elif active and "swe_eval_images" not in out:
            # Orphan progress after kill/cancel — heal sticky strip.
            _mark_swe_images_progress_cancelled("预拉已中断（无活动进程）")

    prog = _read_runtime_sync_progress()
    if isinstance(prog, dict):
        status = str(prog.get("status") or "")
        phase = str(prog.get("phase") or "")
        active = status == "building" or phase in _SYNC_ACTIVE
        if (
            active
            and phase not in {"finished", "error", ""}
            and _sync_progress_fresh(prog, max_age_s=900.0)
        ):
            item_id = _sync_item_id(prog) or "index_product"
            summary, pct = _sync_summary(prog)
            action = _ITEM_DEFAULT_ACTION.get(item_id, "sync-sources")
            prev = out.get(item_id)
            out[item_id] = {
                "item_id": item_id,
                "action": (prev or {}).get("action") or action,
                "kind": "sync",
                "pid": (prev or {}).get("pid"),
                "summary": summary,
                "pct": pct,
                "phase": phase,
                "path": prog.get("path"),
                "reason": prog.get("reason"),
                "source": "runtime",
                "chunks_embedded": prog.get("chunks_embedded"),
                "chunks_total": prog.get("chunks_total"),
                "scopes_done": prog.get("scopes_done"),
                "scopes_total": prog.get("scopes_total"),
                "rate_chunks_per_s": prog.get("rate_chunks_per_s"),
                "eta_s": prog.get("eta_s"),
                "files_done": prog.get("files_done"),
                "files_total": prog.get("files_total"),
            }

    dep = _read_deploy_status()
    phase = str(dep.get("phase") or "")
    # Only surface deploy as live when a process still holds it (healed above otherwise).
    if phase in _ACTIVE_DEPLOY_PHASES and _release_deploy_alive():
        mod = str(dep.get("current_module") or "").strip()
        if mod in _ITEM_DEFAULT_ACTION:
            action = _ITEM_DEFAULT_ACTION[mod]
            msg = str(dep.get("message") or phase)
            out[mod] = {
                "item_id": mod,
                "action": action,
                "kind": "deploy",
                "summary": f"构建中 · {mod} · {msg}",
                "pct": None,
                "phase": phase,
                "source": "release",
                "run_id": dep.get("run_id"),
            }

    return out


def _find_live_for_action(action: str) -> dict | None:
    item_id = _ACTION_ITEM.get(action)
    live_map = _collect_live()
    if item_id and item_id in live_map:
        return live_map[item_id]
    # Same log-key family (ensure-ops-cmteb ↔ sync-ops-cmteb).
    want_key = ACTION_LOG_KEY.get(action)
    for live in live_map.values():
        if ACTION_LOG_KEY.get(str(live.get("action") or "")) == want_key:
            return live
        if live.get("item_id") and ITEM_LOG_KEY.get(str(live["item_id"])) == want_key:
            return live
    return None


def _with_live(plan: dict) -> dict:
    """Overlay live jobs onto plan items (always fresh; cheap docker exec)."""
    snap = dict(plan)
    live_map = _collect_live()
    snap["live"] = list(live_map.values())
    items = []
    for raw in snap.get("items") or []:
        it = dict(raw)
        live = live_map.get(str(it.get("id") or ""))
        if live:
            it["live"] = live
            it["status"] = "running"
            it["detail"] = live.get("summary") or it.get("detail") or "进行中"
            action = str(
                live.get("action")
                or (it.get("button") or {}).get("action")
                or _ITEM_DEFAULT_ACTION.get(str(it.get("id") or ""))
                or ""
            )
            if action:
                it["button"] = {
                    "action": action,
                    "label": "查看进度",
                    "attach": True,
                }
        items.append(it)
    snap["items"] = items
    return _with_queue(snap)


def _with_queue(plan: dict) -> dict:
    """Annotate items that are waiting / running in the serial console queue."""
    snap = dict(plan)
    qpub = _queue_public()
    snap["queue"] = qpub
    by_item: dict[str, dict] = {}
    for qi in qpub.get("pending") or []:
        iid = _ACTION_ITEM.get(str(qi.get("action") or ""))
        if not iid:
            continue
        # Prefer running overlay if both somehow present.
        prev = by_item.get(iid)
        if prev and prev.get("status") == "running":
            continue
        by_item[iid] = qi
    items = []
    for raw in snap.get("items") or []:
        it = dict(raw)
        qi = by_item.get(str(it.get("id") or ""))
        if qi and it.get("status") != "running":
            it["queue"] = qi
            label = qi.get("label") or qi.get("action")
            if qi.get("status") == "pending":
                it["detail"] = f"队列等待 · {label}"
                btn = dict(it.get("button") or {})
                action = btn.get("action") or qi.get("action")
                if action:
                    it["button"] = {
                        "action": action,
                        "label": "排队中",
                        "queued": True,
                    }
            elif qi.get("status") == "running":
                it["status"] = "running"
                it["detail"] = f"队列执行中 · {label}"
                if qi.get("action"):
                    it["button"] = {
                        "action": qi["action"],
                        "label": "查看进度",
                        "attach": True,
                    }
        elif qi and it.get("status") == "running":
            it["queue"] = qi
        items.append(it)
    snap["items"] = items
    return snap


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
        dep = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"phase": "error", "message": str(exc), "changed": [], "deployed": {}}
    return _heal_stale_deploy(dep if isinstance(dep, dict) else {})


def _build_plan(mode: str = "local") -> dict:
    """Reload release scripts every time — console is long-lived; plan/worktree_sig
    change on disk must not stick as「存在变动」after a successful up-*.
    """
    os.environ["RELEASE_STATUS_DIR"] = str(STATUS_DIR)
    import importlib

    # worktree_sig first: plan imports it; reload(plan) alone leaves a stale helper.
    if "worktree_sig" in sys.modules:
        importlib.reload(sys.modules["worktree_sig"])
    else:
        import worktree_sig  # noqa: F401  # type: ignore

    import plan as plan_mod  # type: ignore

    importlib.reload(plan_mod)
    # STATUS_FILE is bound at import — force re-bind after RELEASE_STATUS_DIR set.
    plan_mod.STATUS_FILE = Path(STATUS_DIR) / "status.json"
    return plan_mod.build_plan(mode=mode)


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
    return _with_live(plan)


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
    """Prefer instant stale cache; rebuild sync only when forced or cold-empty.

    Live job overlay is always applied so progress stays fresh without full plan rebuild.
    """
    mode = _norm_mode(mode)
    now = time.time()
    cached = _plan_cache["data"]
    same_mode = _plan_cache.get("mode") == mode
    age = now - float(_plan_cache["at"]) if cached is not None and same_mode else 1e9

    if force:
        return _compute_plan(mode=mode)

    if cached is not None and same_mode and age < _PLAN_TTL_SEC:
        return _with_live(_with_deploy(cached))

    if cached is not None and same_mode:
        _rebuild_in_background(mode)
        snap = _with_live(_with_deploy(cached))
        snap["stale"] = True
        return snap

    disk = _load_disk_plan(mode)
    if disk is not None:
        _plan_cache["data"] = disk
        _plan_cache["at"] = 0.0
        _plan_cache["mode"] = mode
        _rebuild_in_background(mode)
        snap = _with_live(_with_deploy(disk))
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
        "ast_indexer": ("up-ast-indexer", "重建 ast_indexer"),
        "web": ("up-web", "重建 web"),
        "gateway": ("up-gateway", "重建 gateway"),
        "embedding": ("up-runtime", "重建 runtime（换模）"),
        "ops_embedding_ref": ("up-runtime", "重建 runtime（换模）"),
        "index_product": ("sync-sources", "同步产品索引"),
        "index_ops": ("sync-ops-indexes", "同步 Ops BEIR"),
        "index_ops_zh": ("ensure-ops-cmteb", "拉取并嵌入中文库"),
        "swe_eval_images": ("pull-swe-eval-images", "预拉 SWE eval 镜像"),
        "ops_bench": ("start-bench", "启动 Ops Bench"),
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
_LOG_BODY_TAIL = 80_000
_LOG_TIMELINE_MAX = 160_000
_MANAGED_LOG_KEYS = (
    "git",
    "api",
    "runtime",
    "ast_indexer",
    "web",
    "gateway",
    "index_product",
    "index_ops",
    "index_ops_zh",
    "swe_eval_images",
    "ops_bench",
    "misc",
)


def _spawn(cmd: list[str], *, action: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["RELEASE_STATUS_DIR"] = str(STATUS_DIR)
    log_dir = STATUS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    key = ACTION_LOG_KEY.get(action, "misc")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    out = open(log_dir / f"{key}.log", "a", encoding="utf-8")  # noqa: SIM115
    out.write(f"\n==> {stamp} [{key}] {' '.join(cmd)}\n")
    out.flush()
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=out,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _register_job(action=action, pid=int(proc.pid), log_key=key)
    return proc


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
                "body": text.strip()[-_LOG_BODY_TAIL:],
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
                "body": body[-_LOG_BODY_TAIL:] if body else "(无输出)",
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

    # release.sh tee log — show under all / code module tabs (查看进度).
    code_mods = {"api", "runtime", "ast_indexer", "web", "gateway"}
    if module in {None, "", "all", "*", *code_mods}:
        dep = _read_deploy_status()
        rel = str(dep.get("log_file") or "")
        if rel:
            p = STATUS_DIR / rel
            if p.is_file() and p.stat().st_size > 0:
                mt = p.stat().st_mtime
                body = p.read_text(encoding="utf-8", errors="replace")[-_LOG_BODY_TAIL:].strip()
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


def _live_log_note(log_key: str) -> str:
    for live in _collect_live().values():
        if live.get("kind") != "sync":
            continue
        item = str(live.get("item_id") or "")
        if log_key not in {ITEM_LOG_KEY.get(item, ""), "all", item}:
            continue
        summary = str(live.get("summary") or "").strip()
        if summary:
            return f"【实时 {time.strftime('%Y-%m-%d %H:%M:%S')}】{summary}"
    return ""


def _format_timeline(entries: list[dict], *, log_key: str) -> str:
    if not entries:
        return (
            f"（尚无「{log_key}」任务日志）\n"
            "有输出后形如：[2026-08-07 12:00:00] 内容"
        )
    entries = sorted(entries, key=lambda e: float(e["ts_epoch"]), reverse=True)
    lines: list[str] = []
    for i, e in enumerate(entries):
        tag = e["ts"]
        mod = e.get("module") or log_key
        title = (e.get("title") or "").strip()
        body = (e.get("body") or "").rstrip()
        newest = " (最新)" if i == 0 else ""
        head = f"[{tag}]{newest} [{mod}] 任务开始"
        if title and title not in {"(无输出)", "（整文件，无分段时间戳）"}:
            head = f"{head} · {title}"
        lines.append(head)
        if i == 0:
            note = _live_log_note(str(e.get("module") or log_key))
            if note:
                lines.append(note)
        if body:
            for raw in body.splitlines():
                lines.append(raw)
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > _LOG_TIMELINE_MAX:
        text = "…(截断更早记录)…\n" + text[:_LOG_TIMELINE_MAX]
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
    keys = (
        "git",
        "api",
        "runtime",
        "ast_indexer",
        "web",
        "gateway",
        "index_product",
        "index_ops",
        "index_ops_zh",
    )
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
        if path == "/api/live":
            live_map = _collect_live()
            self._send_json(200, {"ok": True, "live": list(live_map.values())})
            return
        if path == "/api/queue":
            self._send_json(200, {"ok": True, "queue": _queue_public()})
            return
        if path in ("/", "/index.html"):
            self.path = "/index.html"
            # Always re-read static HTML/JS after console updates (avoid sticky old refresh logic).
            try:
                data = (STATIC_DIR / "index.html").read_bytes()
            except OSError as exc:
                self.send_error(404, str(exc))
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
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

            # Soft-restart: reply first, then detached stop+ensure (not via serial queue).
            if action == "restart-console":
                result = _schedule_console_restart()
                code = 200 if result.get("ok") else 500
                self._send_json(code, result)
                return

            _ensure_queue_worker()

            # Outside-queue orphan still running → attach (do not double-enqueue).
            if action != "cancel-jobs":
                live = _find_live_for_action(action)
                if action == "up-all" and not live:
                    for cand in _collect_live().values():
                        act = str(cand.get("action") or "")
                        if cand.get("kind") == "deploy" or act.startswith("up-"):
                            live = cand
                            break
                if live:
                    # If our queue already tracks it, enqueue will attach/dedupe.
                    q = _queue_public()
                    tracked = any(
                        str(i.get("action")) == action
                        and i.get("status") in {"pending", "running"}
                        for i in (q.get("pending") or [])
                    )
                    if not tracked:
                        _plan_cache["at"] = 0.0
                        self._send_json(
                            200,
                            {
                                "ok": True,
                                "attached": True,
                                "queued": False,
                                "action": action,
                                "live": live,
                                "queue": q,
                                "message": f"已接上进行中的任务 · {live.get('summary') or action}",
                            },
                        )
                        return

            result = _enqueue_action(action)
            _plan_cache["at"] = 0.0
            code = 200 if result.get("ok") else 500
            self._send_json(code, result)
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
    _ensure_queue_worker()

    # Avoid "address already in use" after quick restart; bind all interfaces for WSL→Windows.
    ThreadingHTTPServer.allow_reuse_address = True
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), partial(Handler))
    except OSError as exc:
        print(f"ERROR: bind 0.0.0.0:{PORT} failed: {exc}", flush=True)
        raise SystemExit(1) from exc
    print(f"release-console http://127.0.0.1:{PORT}/", flush=True)
    print(f"local_trust={LOCAL_TRUST} (loopback actions without secret)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
