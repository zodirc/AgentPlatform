#!/usr/bin/env bash
# Cursor beforeShellExecution: gate `git push` behind local preflight unit suites.
# Fail closed only when we detect a push and preflight fails.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

input="$(cat || true)"
# Prefer python (always present in this env) over jq.
cmd="$(
  printf '%s' "$input" | python3 -c 'import json,sys
try:
  d=json.load(sys.stdin)
except Exception:
  d={}
print(d.get("command") or "")' 2>/dev/null || true
)"

allow() {
  printf '%s\n' '{"permission":"allow"}'
  exit 0
}

deny() {
  local msg="$1"
  python3 -c 'import json,sys; print(json.dumps({
    "permission":"deny",
    "user_message": sys.argv[1],
    "agent_message": sys.argv[1],
  }))' "$msg"
  exit 0
}

# Only gate push; ignore status/diff/commit/etc.
if [[ ! "$cmd" =~ (^|[[:space:];|&])git([[:space:]]+([^;|&]+[[:space:]]+)*)?push([[:space:]]|$) ]]; then
  allow
fi

if [[ "$cmd" == *"--no-verify"* ]] || [[ "${SKIP_PREFLIGHT:-0}" == "1" ]]; then
  allow
fi

if ! bash "$ROOT/scripts/preflight_unit.sh"; then
  deny "preflight unit failed — fix tests before git push (or SKIP_PREFLIGHT=1 / --no-verify)."
fi

allow
