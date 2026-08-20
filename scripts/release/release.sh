#!/usr/bin/env bash
# Release change-process for Agent Platform (same repo, updates the serving stack).
#
# Usage:
#   bash scripts/release/release.sh status
#   bash scripts/release/release.sh detect
#   bash scripts/release/release.sh run [--force-all] [--modules=api,runtime]
#   bash scripts/release/release.sh health
#
# Writes reports/release/status.json + reports/release/logs/<id>.log
# Does NOT start a second product stack — make up-* replaces containers on :80.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

STATUS_DIR="${RELEASE_STATUS_DIR:-$ROOT/reports/release}"
STATUS_FILE="$STATUS_DIR/status.json"
LOCK_FILE="$STATUS_DIR/release.lock"
LOG_DIR="$STATUS_DIR/logs"
PATHS_ENV="$ROOT/scripts/release/paths.env"

# shellcheck disable=SC1090
source "$PATHS_ENV"

MODULES=(api runtime ast_indexer web gateway)

mkdir -p "$STATUS_DIR" "$LOG_DIR"

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()[:-1] if False else sys.argv[1]))' "$1"
}

now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

git_sha() {
  git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo "nogit"
}

git_sha_short() {
  git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "nogit"
}

read_status_field() {
  local key="$1"
  python3 - "$STATUS_FILE" "$key" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path))
except Exception:
    print("")
    raise SystemExit(0)
cur = data
for part in key.split("."):
    if not isinstance(cur, dict) or part not in cur:
        print("")
        raise SystemExit(0)
    cur = cur[part]
if isinstance(cur, (dict, list)):
    print(json.dumps(cur))
elif cur is None:
    print("")
else:
    print(cur)
PY
}

write_status() {
  # Args via env: PHASE ERROR LOG_REL CHANGED_CSV CURRENT MESSAGE
  PHASE="${PHASE:-idle}" \
  ERROR="${ERROR:-}" \
  LOG_REL="${LOG_REL:-}" \
  CHANGED_CSV="${CHANGED_CSV:-}" \
  CURRENT="${CURRENT:-}" \
  MESSAGE="${MESSAGE:-}" \
  HEAD_SHA="$(git_sha)" \
  HEAD_SHORT="$(git_sha_short)" \
  DEPLOYED_JSON="${DEPLOYED_JSON:-}" \
  HEALTH_JSON="${HEALTH_JSON:-}" \
  RUN_ID="${RUN_ID:-}" \
  python3 - "$STATUS_FILE" <<'PY'
import json, os, sys, time
from pathlib import Path

path = Path(sys.argv[1])
prev = {}
if path.is_file():
    try:
        prev = json.load(path.open())
    except Exception:
        prev = {}

changed_csv = os.environ.get("CHANGED_CSV", "")
changed = [x for x in changed_csv.split(",") if x]

deployed = prev.get("deployed") or {}
if os.environ.get("DEPLOYED_JSON"):
    try:
        deployed = json.loads(os.environ["DEPLOYED_JSON"])
    except Exception:
        pass

health = prev.get("health") or {}
if os.environ.get("HEALTH_JSON"):
    try:
        health = json.loads(os.environ["HEALTH_JSON"])
    except Exception:
        pass

doc = {
    "phase": os.environ.get("PHASE") or "idle",
    "message": os.environ.get("MESSAGE") or "",
    "error": os.environ.get("ERROR") or None,
    "run_id": os.environ.get("RUN_ID") or prev.get("run_id"),
    "git_sha": os.environ.get("HEAD_SHA"),
    "git_sha_short": os.environ.get("HEAD_SHORT"),
    "changed": changed if changed_csv != "" or os.environ.get("PHASE") in ("detecting", "building", "switching", "done", "failed") else prev.get("changed") or [],
    "current_module": os.environ.get("CURRENT") or None,
    "log_file": os.environ.get("LOG_REL") or prev.get("log_file"),
    "deployed": deployed,
    "health": health,
    "product_url": os.environ.get("PRODUCT_URL", "http://localhost/"),
    "ops_hint": "/ops/<OPS_TEST_SECRET>/test",
    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
# Preserve changed when CHANGED_CSV intentionally empty on idle refresh of health-only
if changed_csv == "" and os.environ.get("PHASE") in ("idle", "verifying"):
    if "changed" in prev and not os.environ.get("FORCE_CHANGED"):
        doc["changed"] = prev.get("changed") or []

path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
tmp.replace(path)
print(json.dumps(doc, indent=2, ensure_ascii=False))
PY
}

acquire_lock() {
  if [[ -f "$LOCK_FILE" ]]; then
    local oldpid
    oldpid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [[ -n "$oldpid" ]] && kill -0 "$oldpid" 2>/dev/null; then
      echo "release already running (pid $oldpid)" >&2
      return 1
    fi
    rm -f "$LOCK_FILE"
  fi
  echo $$ >"$LOCK_FILE"
}

release_lock() {
  rm -f "$LOCK_FILE"
}

prefixes_for() {
  local mod="$1"
  local var="MODULE_${mod}"
  echo "${!var}"
}

module_for_path() {
  local rel="$1"
  local mod prefixes p
  for mod in "${MODULES[@]}"; do
    prefixes="$(prefixes_for "$mod")"
    IFS='|' read -ra parts <<<"$prefixes"
    for p in "${parts[@]}"; do
      [[ -z "$p" ]] && continue
      if [[ "$rel" == "$p"* ]]; then
        echo "$mod"
        break
      fi
    done
  done
}

detect_changed() {
  # Per-module dirty detection (required). Never rely on a single global sha alone.
  # Module is dirty (needs rebuild) if:
  #   - force_all
  #   - no deployed[module].git_sha baseline
  #   - git diff baseline..HEAD / dirty worktree touches module paths
  # Container stopped/missing is NOT rebuild-dirty — cmd_up starts existing images
  # first (compose_ensure_stack). Same class of bug as Hub-vs-local cache.
  local force_all="$1"
  local -A hit=()
  local mod baseline files f

  if [[ "$force_all" == "1" ]]; then
    printf '%s\n' "${MODULES[@]}"
    return 0
  fi

  module_baseline() {
    python3 -c '
import json, sys
from pathlib import Path
path, mod = Path(sys.argv[1]), sys.argv[2]
if not path.is_file():
    print("")
    raise SystemExit(0)
try:
    d = json.load(path.open())
except Exception:
    print("")
    raise SystemExit(0)
dep = (d.get("deployed") or {}).get(mod) or {}
print(dep.get("git_sha") or "")
' "$STATUS_FILE" "$1"
  }

  for mod in "${MODULES[@]}"; do
    baseline="$(module_baseline "$mod")"

    if [[ -z "$baseline" ]] || ! git -C "$ROOT" cat-file -e "${baseline}^{commit}" 2>/dev/null; then
      if [[ "$mod" != "gateway" ]]; then
        hit["$mod"]=1
      fi
      continue
    fi

    files="$(
      git -C "$ROOT" diff --name-only "$baseline" HEAD
      git -C "$ROOT" diff --name-only
      git -C "$ROOT" ls-files --others --exclude-standard
    )"
    while IFS= read -r f; do
      [[ -z "$f" ]] && continue
      while IFS= read -r m; do
        [[ "$m" == "$mod" ]] && hit["$mod"]=1
      done < <(module_for_path "$f")
    done <<<"$files"

    # If the only hits are worktree files already covered by last deploy digest, clear.
    if [[ -n "${hit[$mod]:-}" ]]; then
      if STATUS_FILE="$STATUS_FILE" ROOT="$ROOT" MOD="$mod" BASELINE="$baseline" python3 <<'PY'
import json, os, subprocess, sys
from pathlib import Path

root = Path(os.environ["ROOT"])
sys.path.insert(0, str(root / "scripts" / "release"))
from worktree_sig import (
    baked_content_matches,
    digest_for_module,
    load_module_prefixes,
    match_prefixes,
    worktree_changed_files,
)

mod = os.environ["MOD"]
baseline = os.environ["BASELINE"]
status = Path(os.environ["STATUS_FILE"])
dep = {}
if status.is_file():
    try:
        dep = (json.load(status.open()).get("deployed") or {}).get(mod) or {}
    except Exception:
        dep = {}
prev = str(dep.get("worktree_digest") or "")
cur = digest_for_module(mod)
committed = subprocess.run(
    ["git", "-C", str(root), "diff", "--name-only", f"{baseline}..HEAD"],
    text=True, capture_output=True, check=False,
)
prefixes = load_module_prefixes().get(mod) or []
committed_hit = match_prefixes(
    [ln for ln in (committed.stdout or "").splitlines() if ln.strip()],
    prefixes,
)
# Committed-since-baseline is dirty unless those bytes were already baked
# into the image (deploy-then-commit of the same content).
if committed_hit and not baked_content_matches(prev, committed_hit):
    raise SystemExit(1)  # keep dirty
if prev and cur and prev == cur:
    raise SystemExit(0)  # worktree unchanged since last deploy → clean
# No digest yet: keep dirty so one redeploy seeds the fingerprint.
if not prev and match_prefixes(worktree_changed_files(), prefixes):
    raise SystemExit(1)
raise SystemExit(1 if match_prefixes(worktree_changed_files(), prefixes) else 0)
PY
      then
        unset "hit[$mod]"
      fi
    fi
  done

  local out=()
  for mod in "${MODULES[@]}"; do
    [[ -n "${hit[$mod]:-}" ]] && out+=("$mod")
  done
  if [[ ${#out[@]} -eq 0 ]]; then
    return 0
  fi
  printf '%s\n' "${out[@]}"
}

cmd_health() {
  python3 <<'PY'
import json, urllib.request, socket
out = {}
checks = {
    "gateway": "http://127.0.0.1/health/live",
    "gateway_alt": "http://127.0.0.1/health",
}
# Prefer /health/live then /health
ok = False
err = None
for url in ("http://127.0.0.1/health/live", "http://127.0.0.1/health", "http://127.0.0.1/"):
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            ok = 200 <= r.status < 500
            out["gateway"] = {"ok": ok, "url": url, "status": r.status}
            break
    except Exception as e:
        err = str(e)
        out["gateway"] = {"ok": False, "url": url, "error": err}
print(json.dumps(out))
PY
}

cmd_status() {
  if [[ ! -f "$STATUS_FILE" ]]; then
    PHASE=idle MESSAGE="no release yet" CHANGED_CSV="" write_status >/dev/null
  fi
  # refresh health
  HEALTH_JSON="$(cmd_health)"
  PHASE="$(read_status_field phase || echo idle)"
  PHASE="${PHASE:-idle}"
  MESSAGE="$(read_status_field message)"
  HEALTH_JSON="$HEALTH_JSON" PHASE="$PHASE" MESSAGE="${MESSAGE:-}" CHANGED_CSV="" write_status
}

cmd_detect() {
  local force="${1:-0}"
  PHASE=detecting MESSAGE="detecting changed modules" CHANGED_CSV="" write_status >/dev/null
  local list
  list="$(detect_changed "$force" | paste -sd, - || true)"
  PHASE=idle MESSAGE="detect complete" CHANGED_CSV="$list" FORCE_CHANGED=1 write_status
}

deploy_module() {
  local mod="$1"
  echo "==> deploying module: $mod"
  case "$mod" in
    api)
      SKIP_RELEASE_HOOK=1 make -C "$ROOT" up-api
      ;;
    runtime)
      SKIP_RELEASE_HOOK=1 make -C "$ROOT" up-runtime
      ;;
    ast_indexer)
      SKIP_RELEASE_HOOK=1 make -C "$ROOT" up-ast-indexer
      ;;
    web)
      SKIP_RELEASE_HOOK=1 make -C "$ROOT" up-web
      ;;
    gateway)
      # Caddy image is upstream; remount config by recreate.
      # shellcheck disable=SC1091
      set -a
      [[ -f deploy/embedding.defaults.env ]] && . ./deploy/embedding.defaults.env || true
      [[ -f deploy/embedding.auto.env ]] && . ./deploy/embedding.auto.env || true
      [[ -f deploy/ops-eval.auto.env ]] && . ./deploy/ops-eval.auto.env || true
      set +a
      local gpu_flag=()
      [[ -f deploy/compose/gpu.auto.yml ]] && gpu_flag=(-f deploy/compose/gpu.auto.yml)
      local ops_flag=()
      case "${OPS_EVAL_DOCKER_SOCK:-0}" in
        1|true|TRUE|yes|YES) ops_flag=(-f deploy/compose/ops-eval.yml) ;;
      esac
      docker compose -f deploy/docker-compose.yml "${gpu_flag[@]}" "${ops_flag[@]}" \
        --env-file .env --env-file deploy/embedding.defaults.env --env-file deploy/embedding.auto.env \
        up -d --no-deps --force-recreate gateway
      ;;
    *)
      echo "unknown module: $mod" >&2
      return 1
      ;;
  esac
}

# Merge module sha(s) into status.json deployed map. Prints JSON for DEPLOYED_JSON.
# Usage: build_deployed_json <head_sha> <csv_modules> [via]
# Also records worktree_digest so local uncommitted files baked by up-* stop looking dirty.
build_deployed_json() {
  local head="$1"
  local mods="$2"
  local via="${3:-}"
  STATUS_FILE="$STATUS_FILE" HEAD="$head" MODS="$mods" VIA="$via" ROOT="$ROOT" python3 <<'PY'
import json, os, sys, time
from pathlib import Path

root = Path(os.environ["ROOT"])
sys.path.insert(0, str(root / "scripts" / "release"))
from worktree_sig import digest_for_module  # noqa: E402

prev = {}
p = Path(os.environ["STATUS_FILE"])
if p.is_file():
    try:
        prev = json.load(p.open()).get("deployed") or {}
    except Exception:
        prev = {}
head = os.environ["HEAD"]
via = os.environ.get("VIA") or ""
at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
for m in [x for x in os.environ.get("MODS", "").split(",") if x]:
    entry = {
        "git_sha": head,
        "at": at,
        "worktree_digest": digest_for_module(m),
    }
    if via:
        entry["via"] = via
    prev[m] = entry
print(json.dumps(prev))
PY
}

# Persist deployed[mod] immediately so a mid-batch interrupt does not force full rebuild.
persist_module_deployed() {
  local mod="$1"
  local head="$2"
  local run_id="${3:-}"
  local log_rel="${4:-}"
  local csv="${5:-}"
  local deployed_json
  deployed_json="$(build_deployed_json "$head" "$mod")"
  PHASE=switching MESSAGE="marked $mod deployed" CHANGED_CSV="$csv" CURRENT="$mod" \
    RUN_ID="$run_id" LOG_REL="$log_rel" DEPLOYED_JSON="$deployed_json" \
    write_status >/dev/null
}

cmd_run() {
  local force_all=0
  local only=""
  for arg in "$@"; do
    case "$arg" in
      --force-all) force_all=1 ;;
      --modules=*) only="${arg#--modules=}" ;;
      *) echo "unknown arg: $arg" >&2; return 2 ;;
    esac
  done

  acquire_lock || return 1
  trap release_lock EXIT

  local run_id
  run_id="$(date -u +%Y%m%dT%H%M%SZ)-$(git_sha_short)"
  local log_rel="logs/${run_id}.log"
  local log_abs="$STATUS_DIR/$log_rel"
  : >"$log_abs"

  exec > >(tee -a "$log_abs") 2>&1

  RUN_ID="$run_id" LOG_REL="$log_rel" PHASE=detecting MESSAGE="release $run_id starting" CHANGED_CSV="" write_status >/dev/null

  local -a targets=()
  if [[ -n "$only" ]]; then
    IFS=',' read -ra targets <<<"$only"
  else
    mapfile -t targets < <(detect_changed "$force_all")
  fi

  if [[ ${#targets[@]} -eq 0 ]]; then
    PHASE=done MESSAGE="nothing to deploy (working tree matches last release)" \
      CHANGED_CSV="" RUN_ID="$run_id" LOG_REL="$log_rel" write_status >/dev/null
    echo "nothing to deploy"
    return 0
  fi

  local csv
  csv="$(IFS=,; echo "${targets[*]}")"
  PHASE=building MESSAGE="building/replacing: $csv" CHANGED_CSV="$csv" \
    CURRENT="" RUN_ID="$run_id" LOG_REL="$log_rel" write_status >/dev/null

  local mod
  local head
  head="$(git_sha)"

  for mod in "${targets[@]}"; do
    PHASE=switching MESSAGE="deploying $mod" CHANGED_CSV="$csv" CURRENT="$mod" \
      RUN_ID="$run_id" LOG_REL="$log_rel" write_status >/dev/null
    if ! deploy_module "$mod"; then
      PHASE=failed ERROR="deploy failed: $mod" MESSAGE="failed on $mod" \
        CHANGED_CSV="$csv" CURRENT="$mod" RUN_ID="$run_id" LOG_REL="$log_rel" write_status >/dev/null
      return 1
    fi
    # Mark each success immediately — interrupt/fail later must not re-dirty this module.
    persist_module_deployed "$mod" "$head" "$run_id" "$log_rel" "$csv"
    # up-runtime also recreates agent-ast-indexer — keep board digests aligned.
    if [[ "$mod" == "runtime" ]]; then
      persist_module_deployed "ast_indexer" "$head" "$run_id" "$log_rel" "$csv"
    fi
  done

  PHASE=verifying MESSAGE="health check" CHANGED_CSV="$csv" CURRENT="" \
    RUN_ID="$run_id" LOG_REL="$log_rel" write_status >/dev/null
  local health
  health="$(cmd_health)"

  # Consistency fallback: re-merge full batch into deployed (already written per-module).
  local deployed_json
  deployed_json="$(build_deployed_json "$head" "$csv")"

  PHASE=done MESSAGE="deployed $csv @ $(git_sha_short)" CHANGED_CSV="$csv" \
    CURRENT="" RUN_ID="$run_id" LOG_REL="$log_rel" \
    DEPLOYED_JSON="$deployed_json" HEALTH_JSON="$health" \
    write_status >/dev/null

  python3 - "$STATUS_FILE" "$(git_sha)" <<'PY'
import json, sys
from pathlib import Path
path, sha = Path(sys.argv[1]), sys.argv[2]
doc = json.load(path.open())
doc["last_release_sha"] = sha
path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

  echo "release done: $csv @ $(git_sha_short)"
}

usage() {
  cat <<EOF
Usage: bash scripts/release/release.sh <command>

  status              Show/refresh status.json (+ gateway health)
  detect [--force-all]
  run [--force-all] [--modules=api,runtime,ast_indexer,web,gateway]
  mark [--modules=api,runtime,ast_indexer,web,gateway]   Record HEAD as deployed (after make up)
  up [--force-all] [--modules=...]           Modular make up: infra + dirty modules only
  plan                                       Health board JSON (code · model · index)
  health              Probe product gateway on :80

Status file: $STATUS_FILE
EOF
}

compose_profiles_value() {
  # Unset → default bench. Empty-but-set COMPOSE_PROFILES must stay empty
  # (do not use :-) so constrained hosts can skip bench + bench-postgres.
  if [[ -n "${COMPOSE_PROFILES+x}" ]]; then
    printf '%s' "$COMPOSE_PROFILES"
  else
    printf '%s' "bench"
  fi
}

compose_infra_up() {
  # Bring dependency containers without rebuilding product images.
  set -a
  [[ -f deploy/embedding.defaults.env ]] && . ./deploy/embedding.defaults.env || true
  [[ -f deploy/embedding.auto.env ]] && . ./deploy/embedding.auto.env || true
  [[ -f deploy/ops-eval.auto.env ]] && . ./deploy/ops-eval.auto.env || true
  set +a
  local gpu_flag=()
  [[ -f deploy/compose/gpu.auto.yml ]] && gpu_flag=(-f deploy/compose/gpu.auto.yml)
  local ops_flag=()
  case "${OPS_EVAL_DOCKER_SOCK:-0}" in
    1|true|TRUE|yes|YES) ops_flag=(-f deploy/compose/ops-eval.yml) ;;
  esac
  local profiles
  profiles="$(compose_profiles_value)"
  local infra_services=(postgres)
  case ",${profiles}," in
    *,bench,*) infra_services+=(bench-postgres) ;;
  esac
  echo "==> infra: ${infra_services[*]} (COMPOSE_PROFILES='${profiles}')"
  COMPOSE_PROFILES="$profiles" docker compose -f deploy/docker-compose.yml "${gpu_flag[@]}" \
    "${ops_flag[@]}" \
    --env-file .env --env-file deploy/embedding.defaults.env --env-file deploy/embedding.auto.env \
    up -d "${infra_services[@]}"
  COMPOSE_PROFILES="$profiles" bash "$ROOT/scripts/ensure_bench_postgres.sh" || true
}

compose_ensure_stack() {
  # Start any already-built services without --build (gateway/api/runtime/web).
  set -a
  [[ -f deploy/embedding.defaults.env ]] && . ./deploy/embedding.defaults.env || true
  [[ -f deploy/embedding.auto.env ]] && . ./deploy/embedding.auto.env || true
  [[ -f deploy/ops-eval.auto.env ]] && . ./deploy/ops-eval.auto.env || true
  set +a
  local gpu_flag=()
  [[ -f deploy/compose/gpu.auto.yml ]] && gpu_flag=(-f deploy/compose/gpu.auto.yml)
  local ops_flag=()
  case "${OPS_EVAL_DOCKER_SOCK:-0}" in
    1|true|TRUE|yes|YES) ops_flag=(-f deploy/compose/ops-eval.yml) ;;
  esac
  local profiles
  profiles="$(compose_profiles_value)"
  COMPOSE_PROFILES="$profiles" docker compose -f deploy/docker-compose.yml "${gpu_flag[@]}" \
    "${ops_flag[@]}" \
    --env-file .env --env-file deploy/embedding.defaults.env --env-file deploy/embedding.auto.env \
    up -d
  COMPOSE_PROFILES="$profiles" bash "$ROOT/scripts/ensure_bench_postgres.sh" || true
}

cmd_up() {
  # Modular make up entry: only rebuild dirty modules.
  local force_all=0
  local only=""
  for arg in "$@"; do
    case "$arg" in
      --force-all) force_all=1 ;;
      --modules=*) only="${arg#--modules=}" ;;
      *) echo "unknown arg: $arg" >&2; return 2 ;;
    esac
  done

  compose_infra_up
  # After host reboot, containers are stopped but images remain. Start the stack
  # before dirty detect so we do not treat "not running" as rebuild-needed, and
  # so worktree/image byte checks can exec into running containers.
  echo "==> ensuring existing images are up (no --build)"
  compose_ensure_stack

  local -a targets=()
  if [[ -n "$only" ]]; then
    IFS=',' read -ra targets <<<"$only"
  else
    mapfile -t targets < <(detect_changed "$force_all")
  fi

  if [[ ${#targets[@]} -eq 0 ]]; then
    echo "==> no dirty modules — stack already up (no rebuild)"
    make -C "$ROOT" --no-print-directory fix-workspace-sources || true
    PHASE=done MESSAGE="no module rebuild needed" CHANGED_CSV="" FORCE_CHANGED=1 \
      write_status >/dev/null
    RELEASE_CONSOLE="${RELEASE_CONSOLE:-1}" bash "$ROOT/scripts/release/ensure_console.sh"
    return 0
  fi

  echo "==> dirty modules (rebuild): $(IFS=,; echo "${targets[*]}")"
  # Rebuild only those modules (cmd_run takes flags, not the word "run")
  local args=()
  [[ "$force_all" == "1" ]] && args+=(--force-all)
  args+=(--modules="$(IFS=,; echo "${targets[*]}")")
  cmd_run "${args[@]}"
  compose_ensure_stack
  make -C "$ROOT" --no-print-directory fix-workspace-sources || true
  if [[ "${DOCKER_AUTO_PRUNE:-1}" == "1" ]]; then
    docker image prune -f >/dev/null 2>&1 || true
    docker builder prune -f >/dev/null 2>&1 || true
  fi
  RELEASE_CONSOLE="${RELEASE_CONSOLE:-1}" bash "$ROOT/scripts/release/ensure_console.sh"
}

cmd_mark() {
  local only=""
  for arg in "$@"; do
    case "$arg" in
      --modules=*) only="${arg#--modules=}" ;;
      *) echo "unknown arg: $arg" >&2; return 2 ;;
    esac
  done
  if [[ -z "$only" ]]; then
    echo "mark requires --modules=api,runtime,... (modular only)" >&2
    return 2
  fi
  local -a targets=()
  IFS=',' read -ra targets <<<"$only"
  local csv head health deployed_json
  csv="$(IFS=,; echo "${targets[*]}")"
  head="$(git_sha)"
  health="$(cmd_health)"
  deployed_json="$(build_deployed_json "$head" "$csv" "mark")"
  PHASE=done MESSAGE="marked $csv @ $(git_sha_short)" \
    CHANGED_CSV="" FORCE_CHANGED=1 CURRENT="" \
    DEPLOYED_JSON="$deployed_json" HEALTH_JSON="$health" \
    write_status >/dev/null
  python3 -c '
import json, sys
from pathlib import Path
path, sha = Path(sys.argv[1]), sys.argv[2]
doc = json.load(path.open())
doc["last_release_sha"] = sha
path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(doc, indent=2, ensure_ascii=False))
' "$STATUS_FILE" "$head"
}

main() {
  local cmd="${1:-status}"
  shift || true
  case "$cmd" in
    status) cmd_status "$@" ;;
    detect)
      local force=0
      [[ "${1:-}" == "--force-all" ]] && force=1
      cmd_detect "$force"
      ;;
    run) cmd_run "$@" ;;
    mark) cmd_mark "$@" ;;
    up) cmd_up "$@" ;;
    plan) python3 "$ROOT/scripts/release/plan.py" ;;
    health) cmd_health; echo ;;
    -h|--help|help) usage ;;
    *) usage; return 2 ;;
  esac
}

main "$@"
