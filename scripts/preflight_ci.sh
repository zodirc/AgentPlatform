#!/usr/bin/env bash
# Local mirror of GitHub Actions ci workflow (both jobs):
#   1. scripts/ci_proof.sh  -> unit.* + make gate (smoke + eval-all)
#   2. web vitest + OpenAPI schema.d.ts drift check
#
# Prefer offline from push: make preflight-ci
#   then: SKIP_PREFLIGHT=1 git push
# Opt-in on push (may break SSH idle timeout): PREFLIGHT_CI=1 git push
# Bypass: SKIP_PREFLIGHT=1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${SKIP_PREFLIGHT:-0}" == "1" ]]; then
  echo "==> preflight skipped (SKIP_PREFLIGHT=1)"
  exit 0
fi

echo "==> preflight CI: scripts/ci_proof.sh (unit + gate)"
# Prefer restoring the daily stack after gate on a developer machine.
# CI sets GATE_SKIP_RESTORE=1; override with GATE_SKIP_RESTORE=1 if needed.
CI="${CI:-true}" GATE_SKIP_RESTORE="${GATE_SKIP_RESTORE:-0}" \
  bash "$ROOT/scripts/ci_proof.sh"

echo "==> preflight CI: web unit tests"
# Prefer pnpm on PATH; else corepack pnpm (no root /usr/bin shim needed).
run_pnpm() {
  if command -v pnpm >/dev/null 2>&1; then
    pnpm "$@"
    return
  fi
  if ! command -v corepack >/dev/null 2>&1; then
    echo "pnpm not found and corepack missing; install Node 22+ or: npm i -g pnpm" >&2
    exit 1
  fi
  local pm
  pm="$(node -e 'const p=require("./services/web/package.json"); process.stdout.write(p.packageManager||"pnpm@9.15.9")' 2>/dev/null || true)"
  if [[ -z "${pm}" ]]; then
    pm="pnpm@9.15.9"
  fi
  echo "==> using corepack ${pm} (no global /usr/bin shim)"
  corepack prepare "${pm}" --activate >/dev/null
  corepack pnpm "$@"
}

echo "==> pnpm: $(run_pnpm -v)"
cd "$ROOT/services/web"
if [[ ! -d node_modules ]]; then
  run_pnpm install --frozen-lockfile
fi
run_pnpm test
cd "$ROOT"

echo "==> preflight CI: OpenAPI -> schema.d.ts drift check"
CI=true bash "$ROOT/scripts/codegen.sh"
git diff --exit-code -- services/web/src/shared/api/schema.d.ts

echo "==> preflight CI OK (matches Actions ci proof + web-and-codegen)"
