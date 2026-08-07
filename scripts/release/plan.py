#!/usr/bin/env python3
"""Release health plan — what needs change vs what is fine.

Outputs JSON for the release console / ``release.sh plan``.
Checks (modular):
  - code: api / runtime / web / gateway (git vs last deployed + container up)
  - embedding: resolved profile vs runtime container bake/env
  - index: product + ops source_index_meta vs current embed space
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS_FILE = Path(os.environ.get("RELEASE_STATUS_DIR", ROOT / "reports" / "release")) / "status.json"
PATHS_ENV = Path(__file__).resolve().parent / "paths.env"
AUTO_ENV = ROOT / "deploy" / "embedding.auto.env"
DEFAULT_ENV = ROOT / "deploy" / "embedding.defaults.env"

MODULES = ("api", "runtime", "web", "gateway")
CONTAINERS = {
    "api": "agent-api",
    "runtime": "agent-runtime",
    "web": "agent-web",
    "gateway": "agent-gateway",
    "postgres": "agent-postgres",
    "bench_postgres": "agent-bench-postgres",
}


def _run(cmd: list[str], timeout: float = 8) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def _git(*args: str) -> str:
    code, out, _ = _run(["git", "-C", str(ROOT), *args])
    return out if code == 0 else ""


def _commit_meta(sha: str) -> dict:
    """Short sha + subject (+ date) for UI. Empty if sha missing/invalid."""
    if not sha:
        return {"sha": None, "subject": None, "date": None}
    short = sha[:10]
    # %s subject, %ci committer date ISO-ish
    blob = _git("log", "-1", "--format=%s%n%ci", sha)
    if not blob:
        return {"sha": short, "subject": None, "date": None}
    lines = blob.splitlines()
    return {
        "sha": short,
        "subject": (lines[0] if lines else None) or None,
        "date": (lines[1] if len(lines) > 1 else None) or None,
    }


def _load_paths() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not PATHS_ENV.is_file():
        return out
    for line in PATHS_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key.startswith("MODULE_"):
            continue
        mod = key[len("MODULE_") :]
        raw = val.strip().strip('"').strip("'")
        out[mod] = [p for p in raw.split("|") if p]
    return out


def _read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def _status_doc() -> dict:
    if not STATUS_FILE.is_file():
        return {}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _running_containers() -> set[str]:
    """One docker ps instead of N inspect calls."""
    code, out, _ = _run(
        ["docker", "ps", "--format", "{{.Names}}"],
        timeout=5,
    )
    if code != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def _worktree_changed_files() -> list[str]:
    """Uncommitted (staged + unstaged) + untracked."""
    blob = "\n".join(
        [
            _git("diff", "--name-only"),
            _git("diff", "--cached", "--name-only"),
            _git("ls-files", "--others", "--exclude-standard"),
        ]
    )
    return [f.strip() for f in blob.splitlines() if f.strip()]


def _upstream_info() -> dict:
    """How local HEAD compares to @{upstream} (no network)."""
    info = {
        "upstream": None,
        "ahead": None,
        "behind": None,
        "hint": None,
    }
    up = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if not up:
        info["hint"] = "无 upstream（未设置跟踪分支）"
        return info
    info["upstream"] = up
    blob = _git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if not blob or "\t" not in blob:
        return info
    left, _, right = blob.partition("\t")
    try:
        ahead, behind = int(left.strip()), int(right.strip())
    except ValueError:
        return info
    info["ahead"] = ahead
    info["behind"] = behind
    if behind > 0:
        info["hint"] = f"落后远程 {behind} 个提交，换机器/同步部署请先「拉取」"
    elif ahead > 0:
        info["hint"] = f"本地超前远程 {ahead} 个提交（未 push）"
    else:
        info["hint"] = "与远程同步"
    return info


def _committed_since(deployed_sha: str) -> list[str]:
    if not deployed_sha:
        return []
    code, _, _ = _run(["git", "-C", str(ROOT), "cat-file", "-e", f"{deployed_sha}^{{commit}}"])
    if code != 0:
        return []
    blob = _git("diff", "--name-only", deployed_sha, "HEAD")
    return [f.strip() for f in blob.splitlines() if f.strip()]


def _match_files(files: list[str], prefixes: list[str]) -> list[str]:
    hit = []
    for f in files:
        for p in prefixes:
            if f.startswith(p):
                hit.append(f)
                break
    return hit


def _module_dirty(
    mod: str,
    prefixes: list[str],
    deployed_sha: str,
    *,
    running: set[str],
    worktree_files: list[str],
    include_worktree: bool,
) -> tuple[bool, str]:
    cname = CONTAINERS.get(mod, "")
    if mod != "gateway" and cname and cname not in running:
        return True, f"容器 {cname} 未运行"
    if not deployed_sha:
        if mod == "gateway":
            return False, "无基线（gateway 仅配置变更时重建）"
        return True, "尚未记录过该模块的已部署版本"
    code, _, _ = _run(["git", "-C", str(ROOT), "cat-file", "-e", f"{deployed_sha}^{{commit}}"])
    if code != 0:
        return True, "已部署 sha 无效，需重新发布"

    committed = _match_files(_committed_since(deployed_sha), prefixes)
    dirty_wt = _match_files(worktree_files, prefixes) if include_worktree else []
    hit = committed + [f for f in dirty_wt if f not in committed]
    if hit:
        kinds = []
        if committed:
            kinds.append("已提交")
        if dirty_wt:
            kinds.append("未提交")
        sample = ", ".join(hit[:3])
        more = f" 等{len(hit)}个文件" if len(hit) > 3 else ""
        return True, f"存在变动（{'+'.join(kinds)}）：{sample}{more}"
    if include_worktree:
        return False, "相对已部署；已检查未提交"
    return False, "相对已部署；仅看已提交"


def _container_running(name: str, running: set[str] | None = None) -> bool:
    if running is not None:
        return name in running
    code, out, _ = _run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        timeout=4,
    )
    return code == 0 and out.strip() == "true"

def _index_version_for_model(model: str, dims: int) -> int:
    m = (model or "").lower()
    if "bge-m3" in m:
        return 11
    if "gte-large" in m:
        return 10
    if dims >= 1024:
        return 11
    if "minilm" in m:
        return 8
    return 9


def _docker_exec(container: str, *args: str, timeout: float = 8) -> tuple[int, str]:
    code, out, err = _run(["docker", "exec", container, *args], timeout=timeout)
    return code, out if code == 0 else err


def _embedding_item(
    want_model: str, want_dims: int, want_ver: int, *, running: set[str]
) -> dict:
    item = {
        "id": "embedding",
        "kind": "model",
        "title": "向量模型",
        "want": want_model,
        "want_dims": want_dims,
        "want_index_version": want_ver,
        "status": "unknown",
        "action": None,
        "detail": "",
    }
    if not _container_running("agent-runtime", running):
        item["status"] = "action"
        item["action"] = "make up   # 或只重建 runtime"
        item["detail"] = "runtime 未运行，无法核对容器内模型"
        return item

    # One exec for both values
    _, blob = _docker_exec(
        "agent-runtime",
        "sh",
        "-c",
        'echo "BAKE=$(cat /data/models/.baked_embedding_model 2>/dev/null)"; echo "ENV=${EMBEDDING_MODEL:-}"',
        timeout=6,
    )
    baked = ""
    env_model = ""
    for line in (blob or "").splitlines():
        if line.startswith("BAKE="):
            baked = line[5:].strip()
        elif line.startswith("ENV="):
            env_model = line[4:].strip()
    item["baked"] = baked or None
    item["container_env"] = env_model or None

    if baked and baked != want_model:
        item["status"] = "action"
        item["action"] = "make up-runtime && make sync-sources"
        item["detail"] = f"容器已烘 {baked}，当前配置要 {want_model}（换模后需重建 runtime 并重嵌索引）"
        return item
    if env_model and env_model != want_model:
        item["status"] = "action"
        item["action"] = "make up-runtime"
        item["detail"] = f"容器 ENV={env_model}，配置要 {want_model}"
        return item
    if not baked and not env_model:
        item["status"] = "action"
        item["action"] = "make up-runtime"
        item["detail"] = "读不到容器内模型戳记"
        return item

    item["status"] = "ok"
    item["detail"] = f"{want_model} @ {want_dims}d / INDEX {want_ver}"
    return item


def _psql_meta(container: str, user: str, db: str) -> dict[str, str]:
    sql = (
        "SELECT key, value FROM source_index_meta "
        "WHERE key IN ('version','embedding_model','embedding_dimensions','embedding_backend') "
        "OR key LIKE 'scope:seed:%' "
        "ORDER BY key;"
    )
    code, out = _docker_exec(
        container,
        "psql",
        "-U",
        user,
        "-d",
        db,
        "-At",
        "-F",
        "|",
        "-c",
        sql,
        timeout=12,
    )
    meta: dict[str, str] = {}
    if code != 0 or not out:
        return meta
    for line in out.splitlines():
        if "|" not in line:
            continue
        k, _, v = line.partition("|")
        meta[k.strip()] = v.strip()
    return meta


def _index_item(
    *,
    item_id: str,
    title: str,
    container: str,
    user: str,
    db: str,
    want_model: str,
    want_dims: int,
    want_ver: int,
    sync_action: str,
    running: set[str],
) -> dict:
    item = {
        "id": item_id,
        "kind": "index",
        "title": title,
        "status": "unknown",
        "action": None,
        "detail": "",
        "stored": {},
    }
    if not _container_running(container, running):
        item["status"] = "action"
        item["action"] = "make start  # 先起数据库"
        item["detail"] = f"{container} 未运行"
        return item

    meta = _psql_meta(container, user, db)
    item["stored"] = {
        "version": meta.get("version") or meta.get("scope:seed:version"),
        "embedding_model": meta.get("embedding_model") or meta.get("scope:seed:embedding_model"),
        "embedding_dimensions": meta.get("embedding_dimensions")
        or meta.get("scope:seed:embedding_dimensions"),
    }
    stored_model = (item["stored"].get("embedding_model") or "").strip()
    stored_ver = (item["stored"].get("version") or "").strip()
    stored_dims = (item["stored"].get("embedding_dimensions") or "").strip()

    if not stored_model and not stored_ver:
        item["status"] = "action"
        item["action"] = sync_action
        item["detail"] = "尚无索引戳记（可能从未 sync）"
        return item

    mismatches = []
    if stored_model and stored_model != want_model:
        mismatches.append(f"模型 {stored_model}→{want_model}")
    if stored_ver and stored_ver != str(want_ver):
        mismatches.append(f"INDEX {stored_ver}→{want_ver}")
    if stored_dims and stored_dims != str(want_dims):
        mismatches.append(f"维数 {stored_dims}→{want_dims}")

    if mismatches:
        item["status"] = "action"
        item["action"] = sync_action
        item["detail"] = "嵌入空间漂移：" + "；".join(mismatches) + "（需重嵌，不是改业务代码）"
        return item

    item["status"] = "ok"
    item["detail"] = f"{want_model} / INDEX {want_ver}"
    return item


def build_plan(mode: str | None = None) -> dict:
    mode_raw = (mode or os.environ.get("RELEASE_DETECT_MODE") or "local").strip().lower()
    mode = mode_raw if mode_raw in {"local", "sync"} else "local"
    include_worktree = mode == "local"

    paths = _load_paths()
    st = _status_doc()
    deployed = st.get("deployed") or {}
    head = _git("rev-parse", "HEAD") or "nogit"
    head_short = _git("rev-parse", "--short", "HEAD") or "nogit"
    head_meta = _commit_meta(head)
    remote = _upstream_info()

    auto = {**_read_env_file(DEFAULT_ENV), **_read_env_file(AUTO_ENV)}
    env_file = _read_env_file(ROOT / ".env")
    want_model = (
        auto.get("EMBEDDING_MODEL")
        or env_file.get("EMBEDDING_MODEL")
        or "thenlper/gte-small"
    )
    want_dims = int(auto.get("EMBEDDING_DIMENSIONS") or env_file.get("EMBEDDING_DIMENSIONS") or "384")
    want_ver = int(
        auto.get("EMBEDDING_INDEX_VERSION")
        or str(_index_version_for_model(want_model, want_dims))
    )

    running = _running_containers()
    worktree_files = _worktree_changed_files() if include_worktree else []

    items: list[dict] = []
    dirty_code: list[str] = []

    for mod in MODULES:
        sha = ((deployed.get(mod) or {}) if isinstance(deployed.get(mod), dict) else {}).get(
            "git_sha"
        ) or ""
        dirty, detail = _module_dirty(
            mod,
            paths.get(mod, []),
            sha,
            running=running,
            worktree_files=worktree_files,
            include_worktree=include_worktree,
        )
        action = None
        if dirty:
            dirty_code.append(mod)
            if mod == "api":
                action = "make up-api"
            elif mod == "runtime":
                action = "make up-runtime"
            elif mod == "web":
                action = "make up-web"
            elif mod == "gateway":
                action = "make release RELEASE_MODULES=gateway"
        dep_meta = _commit_meta(sha) if sha else {"sha": None, "subject": None, "date": None}
        items.append(
            {
                "id": mod,
                "kind": "code",
                "title": f"代码 · {mod}",
                "status": "action" if dirty else "ok",
                "action": action,
                "detail": detail,
                "deployed_sha": dep_meta["sha"],
                "deployed_subject": dep_meta["subject"],
                "deployed_date": dep_meta["date"],
            }
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_emb = pool.submit(_embedding_item, want_model, want_dims, want_ver, running=running)
        fut_prod = pool.submit(
            _index_item,
            item_id="index_product",
            title="索引 · 产品库",
            container="agent-postgres",
            user=env_file.get("POSTGRES_USER") or "agent",
            db=env_file.get("POSTGRES_DB") or "agent",
            want_model=want_model,
            want_dims=want_dims,
            want_ver=want_ver,
            sync_action="make sync-sources",
            running=running,
        )
        fut_ops = pool.submit(
            _index_item,
            item_id="index_ops",
            title="索引 · Ops/BEIR 库",
            container="agent-bench-postgres",
            user=env_file.get("BENCH_POSTGRES_USER") or "bench",
            db=env_file.get("BENCH_POSTGRES_DB") or "bench",
            want_model=want_model,
            want_dims=want_dims,
            want_ver=want_ver,
            sync_action="make sync-ops-indexes",
            running=running,
        )
        emb = fut_emb.result()
        idx_prod = fut_prod.result()
        idx_ops = fut_ops.result()

    items.extend([emb, idx_prod, idx_ops])

    actions = [i for i in items if i.get("status") == "action"]
    oks = [i for i in items if i.get("status") == "ok"]

    if not actions:
        summary = "healthy"
        headline = "全部已是最新：代码、向量模型、索引均无待处理变动"
    else:
        summary = "action_needed"
        bits = []
        if dirty_code:
            bits.append("代码 " + ",".join(dirty_code))
        if emb.get("status") == "action":
            bits.append("向量模型")
        if any(i["id"].startswith("index_") and i["status"] == "action" for i in items):
            bits.append("索引")
        headline = "存在变动：" + "；".join(bits)

    if mode == "local":
        detect_scope = "本地开发：已提交(相对已部署) + 未提交"
        workflow = "改代码 → 可不 commit 先重建试 → 确认后再 commit"
    else:
        detect_scope = "同步部署：仅已提交(相对已部署)；忽略未提交"
        workflow = "换机器 → 拉取远程 → 按已提交变更重建"

    return {
        "summary": summary,
        "headline": headline,
        "mode": mode,
        "workflow": workflow,
        "git_sha": head,
        "git_sha_short": head_short,
        "git_subject": head_meta.get("subject"),
        "git_date": head_meta.get("date"),
        "git_remote": remote,
        "embedding_want": {
            "model": want_model,
            "dims": want_dims,
            "index_version": want_ver,
        },
        "dirty_code_modules": dirty_code,
        "detect_scope": detect_scope,
        "counts": {"ok": len(oks), "action": len(actions), "total": len(items)},
        "items": items,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "product_url": "http://localhost/",
        "console_hint": "发布只动代码模块；换模后另做 sync-sources / sync-ops-indexes",
    }


def main() -> None:
    import sys

    mode = None
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
    print(json.dumps(build_plan(mode=mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
