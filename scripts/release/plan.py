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
import sys
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
    "bench": "agent-bench",
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
    deployed_entry: dict | None = None,
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

    try:
        from worktree_sig import (  # type: ignore
            baked_content_matches,
            module_worktree_digest,
            verify_image_files,
        )
    except ImportError:
        from scripts.release.worktree_sig import (  # type: ignore
            baked_content_matches,
            module_worktree_digest,
            verify_image_files,
        )

    prev = ""
    if isinstance(deployed_entry, dict):
        prev = str(deployed_entry.get("worktree_digest") or "").strip()
    baked_match = False

    def _image_out_of_sync(paths: list[str], kind: str) -> tuple[bool, str] | None:
        """If container bytes diverge from host, return a dirty verdict.

        ``skip`` (no mapping / docker unavailable) keeps digest-only behavior.
        """
        if not paths or not cname:
            return None
        status, bad = verify_image_files(mod, paths, container=cname)
        if status != "mismatch":
            return None
        sample = ", ".join(bad[:3])
        more = f" 等{len(bad)}个文件" if len(bad) > 3 else ""
        return True, f"镜像未同步{kind}（需强制重建）：{sample}{more}"

    # Local mode: uncommitted files already baked by last up-* should not stay dirty.
    # Digest match alone is insufficient (Docker COPY cache can leave /app stale).
    if include_worktree and dirty_wt:
        cur = module_worktree_digest(prefixes, files=worktree_files)
        if prev and cur and prev == cur:
            stale = _image_out_of_sync(dirty_wt, "工作区")
            if stale is not None:
                return stale
            dirty_wt = []
            baked_match = True
        elif prev == "" and cur == "":
            dirty_wt = []

    # Same bytes later committed: digest still matches → not a real redeploy need.
    if committed and prev and baked_content_matches(prev, committed):
        stale = _image_out_of_sync(committed, "已提交内容")
        if stale is not None:
            return stale
        committed = []
        baked_match = True

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
        dep = deployed_entry if isinstance(deployed_entry, dict) else {}
        if baked_match and dep.get("worktree_digest"):
            if _match_files(worktree_files, prefixes):
                return False, "已是最新 — 未提交改动已编入当前镜像"
            return False, "已是最新 — 已提交内容与部署时编入镜像一致"
        if dep.get("worktree_digest") and _match_files(worktree_files, prefixes):
            return False, "已是最新 — 未提交改动已编入当前镜像"
        return False, "已是最新 — 与已部署一致"
    return False, "已是最新 — 与已部署一致（仅核对已提交）"


def _container_running(name: str, running: set[str] | None = None) -> bool:
    """True if ``name`` is up (exact or compose-prefixed ``*_name``)."""
    if running is not None:
        if name in running:
            return True
        return any(n.endswith("_" + name) for n in running)
    code, out, _ = _run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        timeout=4,
    )
    return code == 0 and out.strip() == "true"


def _ops_bench_item(*, running: set[str]) -> dict:
    """Ops official meta / L1 jobs need the dedicated bench worker container."""
    item: dict = {
        "id": "ops_bench",
        "kind": "ops",
        "lane": "ops",
        "title": "Ops Bench worker",
        "status": "ok",
        "action": None,
        "detail": "",
        "optional": False,
    }
    name = CONTAINERS["bench"]
    actual = name if name in running else next(
        (n for n in running if n.endswith("_" + name)),
        None,
    )
    if actual:
        # Prefer compose health when present; missing Health → treat as up.
        code, health, _ = _run(
            [
                "docker",
                "inspect",
                "-f",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                actual,
            ],
            timeout=4,
        )
        st = (health or "").strip().lower() if code == 0 else "none"
        if st in {"", "none", "healthy", "starting"}:
            item["status"] = "ok"
            detail = "agent-bench 运行中 · Ops /official/meta 与真向量评测依赖"
            if st == "starting":
                detail = "agent-bench 启动中（health=starting）"
            item["detail"] = detail
            return item
        item["status"] = "action"
        item["action"] = "make start-bench"
        item["detail"] = (
            f"agent-bench 不健康（health={st}）— Ops meta 会失败；先 start-bench（不 rebuild）"
        )
        return item

    item["status"] = "action"
    item["action"] = "make start-bench"
    item["detail"] = (
        "agent-bench 未运行 — Ops meta/真向量会失败；一键 start-bench（不 rebuild）"
    )
    return item

def _index_version_for_model(model: str, dims: int) -> int:
    m = (model or "").lower()
    if "bge-m3" in m:
        # Default GPU profile truncates max_seq=512 → INDEX 12 (see resolve_embedding).
        return 12
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


def _ops_eval_sock_enabled(env_file: dict[str, str]) -> bool:
    """True when api is intended to drive SWE harness via docker.sock."""
    auto = ROOT / "deploy" / "ops-eval.auto.env"
    vals: dict[str, str] = {}
    if auto.is_file():
        for line in auto.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip().strip('"').strip("'")
    raw = (
        vals.get("OPS_EVAL_DOCKER_SOCK")
        or env_file.get("OPS_EVAL_DOCKER_SOCK")
        or os.environ.get("OPS_EVAL_DOCKER_SOCK")
        or "0"
    )
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _swe_eval_images_item(*, env_file: dict[str, str]) -> dict:
    """Ops readiness: local sweb.eval images for official resolve scoring.

    Shown when ops-eval docker.sock is enabled; otherwise skip (product stack
    does not need these multi-GB images).
    """
    item: dict = {
        "id": "swe_eval_images",
        "kind": "ops",
        "lane": "ops",
        "title": "SWE eval 镜像",
        "status": "ok",
        "action": None,
        "detail": "",
        "optional": True,
    }
    if not _ops_eval_sock_enabled(env_file):
        item["status"] = "skip"
        item["detail"] = "可选 · 未启用 ops-eval（make up-ops-eval）；产品栈不需要"
        return item

    # Import lazily — scripts/ is on path via release console / make release-plan.
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from official_bench.swe_images import harness_cfg, local_image_status  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        item["status"] = "action"
        item["action"] = "make official-bench-coding-pull-images"
        item["detail"] = f"无法检查镜像状态：{exc}"
        return item

    h = harness_cfg()
    st = local_image_status(h["board_tier"])
    item["tier"] = st["tier"]
    item["n"] = st["n"]
    item["present_n"] = len(st["present"])
    item["missing_n"] = len(st["missing"])
    item["approx_mib"] = st["approx_mib_total"]
    item["cache_level"] = st["cache_level"]
    gb = round(st["approx_mib_total"] / 1024.0, 1)
    if st["ready"]:
        item["status"] = "ok"
        item["detail"] = (
            f"{st['tier']} · {st['n']}/{st['n']} 本地就绪 "
            f"（约 {gb} GiB 压缩 · cache_level={st['cache_level']}）"
        )
        return item

    miss = st["missing"]
    sample = ", ".join(Path(m).name for m in miss[:2])
    more = f" 等{len(miss)}个" if len(miss) > 2 else ""
    item["status"] = "action"
    item["action"] = "make official-bench-coding-pull-images"
    item["detail"] = (
        f"{st['tier']} 缺 {len(miss)}/{st['n']} 张 sweb.eval "
        f"（约 {gb} GiB；例 {sample}{more}）。"
        "预拉后才有官方 resolve_rate；勿塞进 git"
    )
    return item


def _embedding_item(
    want_model: str, want_dims: int, want_ver: int, *, running: set[str]
) -> dict:
    item = {
        "id": "embedding",
        "kind": "model",
        "lane": "product",
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


def _psql_meta(
    container: str,
    user: str,
    db: str,
    *,
    schema: str = "public",
) -> dict[str, str]:
    # Ops L1 stamps live on bench-postgres in retrieval_ops (not public).
    sch = (schema or "public").strip() or "public"
    if not sch.replace("_", "").isalnum():
        sch = "public"
    # Prefer global stamp keys (written by scope sync). Also accept seed/work
    # scope keys so a schema that only has per-work stamps still reports.
    sql = (
        f"SELECT key, value FROM {sch}.source_index_meta "
        "WHERE key IN ('version','embedding_model','embedding_dimensions','embedding_backend') "
        "OR key LIKE 'scope:seed:%' "
        "OR key LIKE 'scope:work:%' "
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
    schema: str = "public",
    lane: str = "product",
) -> dict:
    item = {
        "id": item_id,
        "kind": "index",
        "lane": lane,
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

    meta = _psql_meta(container, user, db, schema=schema)
    item["schema"] = schema

    def _meta_field(field: str) -> str | None:
        # Global keys first; else seed; else any work scope stamp.
        direct = meta.get(field)
        if direct:
            return direct
        seed = meta.get(f"scope:seed:{field}")
        if seed:
            return seed
        prefix = "scope:work:"
        suffix = f":{field}"
        for k, v in meta.items():
            if k.startswith(prefix) and k.endswith(suffix) and v:
                return v
        return None

    item["stored"] = {
        "version": _meta_field("version"),
        "embedding_model": _meta_field("embedding_model"),
        "embedding_dimensions": _meta_field("embedding_dimensions"),
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


def _is_bge_m3(model: str) -> bool:
    return "bge-m3" in (model or "").lower()


def _cmteb_corpus_ready(env_file: dict[str, str]) -> bool:
    """True when C-MTEB slices exist under the host path compose mounts into the stack."""
    roots: list[Path] = []
    raw = (env_file.get("HOST_BENCH_DATA_DIR") or "").strip()
    # Prefer the compose mount source (not container-only paths like /data/...).
    if raw and not raw.startswith("/data/"):
        roots.append(Path(raw).expanduser().resolve())
    roots.append((ROOT / "eval" / "official" / ".local-data").resolve())

    seen: set[Path] = set()
    for base in roots:
        if base in seen:
            continue
        seen.add(base)
        cmteb = base / "cmteb"
        if not cmteb.is_dir():
            continue
        for child in cmteb.iterdir():
            if not child.is_dir():
                continue
            if (
                (child / "corpus.jsonl").is_file()
                and (child / "queries.jsonl").is_file()
                and (child / "qrels" / "test.tsv").is_file()
            ):
                return True
    return False


def _index_ops_zh_item(
    *,
    want_model: str,
    want_dims: int,
    want_ver: int,
    env_file: dict[str, str],
    auto: dict[str, str],
    running: set[str],
) -> dict:
    """Optional C-MTEB (ZH) Ops index — bge-m3 only; small suite ~50k docs.

    When needed, action is ``bash scripts/release/ensure_ops_cmteb.sh``
    (pull → materialize ops-l1/cmteb-index Works → sync-ops-cmteb).
    Already pulled + stamped → ok (no button).
    """
    schema = (
        env_file.get("OPS_RETRIEVAL_PG_SCHEMA_ZH")
        or auto.get("OPS_RETRIEVAL_PG_SCHEMA_ZH")
        or "retrieval_ops_zh"
    )
    ensure_action = "bash scripts/release/ensure_ops_cmteb.sh"
    item: dict = {
        "id": "index_ops_zh",
        "kind": "index",
        "lane": "ops",
        "title": "C-MTEB 中文索引",
        "status": "ok",
        "action": None,
        "detail": "",
        "optional": True,
        "stored": {},
        "schema": schema,
    }
    if not _is_bge_m3(want_model):
        item["status"] = "skip"
        item["detail"] = f"可选 · 仅 bge-m3；当前 {want_model}，跳过"
        return item

    if not _cmteb_corpus_ready(env_file):
        item["status"] = "action"
        item["action"] = ensure_action
        item["detail"] = (
            "可选 · 小量中文库未就绪（≈5万篇）— 可一键拉取并嵌入 retrieval_ops_zh"
        )
        return item

    checked = _index_item(
        item_id="index_ops_zh",
        title="C-MTEB 中文索引",
        container="agent-bench-postgres",
        user=env_file.get("BENCH_POSTGRES_USER") or "bench",
        db=env_file.get("BENCH_POSTGRES_DB") or "bench",
        want_model=want_model,
        want_dims=want_dims,
        want_ver=want_ver,
        sync_action=ensure_action,
        running=running,
        schema=schema,
        lane="ops",
    )
    checked["optional"] = True
    if checked.get("status") == "ok":
        checked["detail"] = f"{want_model} / INDEX {want_ver} · C-MTEB 小量已嵌入"
        return checked
    if checked.get("status") == "action":
        detail = str(checked.get("detail") or "")
        if "尚无索引戳记" in detail:
            checked["detail"] = (
                "语料已在挂载目录 · 未嵌入 — 一键写入 retrieval_ops_zh（≈5万篇）"
            )
        else:
            checked["detail"] = detail + " — 可一键重嵌"
        checked["action"] = ensure_action
    return checked


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
        dep_entry = (
            (deployed.get(mod) or {}) if isinstance(deployed.get(mod), dict) else {}
        )
        sha = dep_entry.get("git_sha") or ""
        dirty, detail = _module_dirty(
            mod,
            paths.get(mod, []),
            sha,
            running=running,
            worktree_files=worktree_files,
            include_worktree=include_worktree,
            deployed_entry=dep_entry,
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
                "lane": "product",
                "title": mod,
                "status": "action" if dirty else "ok",
                "action": action,
                "detail": detail,
                "deployed_sha": dep_meta["sha"],
                "deployed_subject": dep_meta["subject"],
                "deployed_date": dep_meta["date"],
            }
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        fut_emb = pool.submit(_embedding_item, want_model, want_dims, want_ver, running=running)
        fut_prod = pool.submit(
            _index_item,
            item_id="index_product",
            title="语料索引",
            container="agent-postgres",
            user=env_file.get("POSTGRES_USER") or "agent",
            db=env_file.get("POSTGRES_DB") or "agent",
            want_model=want_model,
            want_dims=want_dims,
            want_ver=want_ver,
            sync_action="make sync-sources",
            running=running,
            lane="product",
        )
        fut_ops = pool.submit(
            _index_item,
            item_id="index_ops",
            title="BEIR 英文索引",
            container="agent-bench-postgres",
            user=env_file.get("BENCH_POSTGRES_USER") or "bench",
            db=env_file.get("BENCH_POSTGRES_DB") or "bench",
            # Ops L1 vectors + stamps are in retrieval_ops (Schema A), not public.
            schema=(
                env_file.get("OPS_RETRIEVAL_PG_SCHEMA")
                or auto.get("OPS_RETRIEVAL_PG_SCHEMA")
                or "retrieval_ops"
            ),
            want_model=want_model,
            want_dims=want_dims,
            want_ver=want_ver,
            sync_action="make sync-ops-indexes",
            running=running,
            lane="ops",
        )
        fut_ops_zh = pool.submit(
            _index_ops_zh_item,
            want_model=want_model,
            want_dims=want_dims,
            want_ver=want_ver,
            env_file=env_file,
            auto=auto,
            running=running,
        )
        fut_swe = pool.submit(_swe_eval_images_item, env_file=env_file)
        fut_bench = pool.submit(_ops_bench_item, running=running)
        emb = fut_emb.result()
        idx_prod = fut_prod.result()
        idx_ops = fut_ops.result()
        idx_ops_zh = fut_ops_zh.result()
        swe_imgs = fut_swe.result()
        ops_bench = fut_bench.result()

    items.extend([emb, idx_prod, idx_ops, idx_ops_zh, ops_bench, swe_imgs])

    # Ops 检索嵌入复用产品 runtime 向量模型——单独挂一条，避免和产品轨混在同一组。
    ops_emb = {
        "id": "ops_embedding_ref",
        "kind": "model",
        "lane": "ops",
        "title": "向量模型（共用 runtime）",
        "want": emb.get("want"),
        "want_dims": emb.get("want_dims"),
        "want_index_version": emb.get("want_index_version"),
        "baked": emb.get("baked"),
        "container_env": emb.get("container_env"),
        "optional": True,
        "status": emb.get("status") or "unknown",
        "action": emb.get("action"),
        "detail": (
            "Ops BEIR/C-MTEB 嵌入走 agent-runtime，与产品同一 EMBEDDING_MODEL；"
            "C-MTEB 另要求 bge-m3"
            + (f"；当前 {emb.get('detail')}" if emb.get("detail") else "")
        ),
    }
    items.append(ops_emb)

    # ops_embedding_ref mirrors product embedding — don't double-count in summary.
    actions = [
        i
        for i in items
        if i.get("status") == "action" and i.get("id") != "ops_embedding_ref"
    ]
    oks = [i for i in items if i.get("status") == "ok"]
    skips = [i for i in items if i.get("status") == "skip"]

    if not actions:
        summary = "healthy"
        headline = "全部已是最新：产品与 Ops 均无待处理变动"
    else:
        summary = "action_needed"
        bits = []
        if dirty_code:
            bits.append("产品代码 " + ",".join(dirty_code))
        if emb.get("status") == "action":
            bits.append("产品向量模型")
        if idx_prod.get("status") == "action":
            bits.append("产品语料索引")
        if any(
            i["id"].startswith("index_ops") and i["status"] == "action" for i in items
        ):
            bits.append("Ops 索引")
        if ops_bench.get("status") == "action":
            bits.append("Ops Bench worker")
        if swe_imgs.get("status") == "action":
            bits.append("SWE eval 镜像")
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
        "counts": {
            "ok": len(oks),
            "action": len(actions),
            "skip": len(skips),
            "total": len(items),
        },
        "items": items,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "product_url": "http://localhost/",
        "console_hint": (
            "发布只动代码模块；换模后 sync-sources / sync-ops-indexes；"
            "C-MTEB 中文小量（≈5万）可选：看板「拉取并嵌入」或 ensure_ops_cmteb.sh（仅 bge-m3）；"
            "SWE 官方 resolve：看板「预拉 SWE eval 镜像」（~1GiB/题，不进 git）"
        ),
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
