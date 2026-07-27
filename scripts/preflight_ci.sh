#!/usr/bin/env bash
# Local mirror of GitHub Actions ``ci`` workflow (both jobs):
#   1. scripts/ci_proof.sh  → unit.* + make gate (smoke + eval-all)
#   2. web vitest + OpenAPI schema.d.ts drift check
#
# Wired from .githooks/pre-push. Bypass:
#   SKIP_PREFLIGHT=1 git push
#   git push --no-verify
# Fast unit-only (old behavior):
#   PREFLIGHT_UNIT_ONLY=1 git push
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${SKIP_PREFLIGHT:-0}" == "1" ]]; then
  echo "==> preflight skipped (SKIP_PREFLIGHT=1)"
  exit 0
fi

if [[ "${PREFLIGHT_UNIT_ONLY:-0}" == "1" ]]; then
  echo "==> preflight: PREFLIGHT_UNIT_ONLY=1 → scripts/preflight_unit.sh"
  exec bash "$ROOT/scripts/preflight_unit.sh"
fi

echo "==> preflight CI: scripts/ci_proof.sh (unit + gate)"
# Prefer restoring the daily stack after gate on a developer machine.
# CI sets GATE_SKIP_RESTORE=1; override with GATE_SKIP_RESTORE=1 if needed.
CI="${CI:-true}" GATE_SKIP_RESTORE="${GATE_SKIP_RESTORE:-0}" \
  bash "$ROOT/scripts/ci_proof.sh"

echo "==> preflight CI: web unit tests"
if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm not found; enable via: corepack enable" >&2
  exit 1
fi
(
  cd "$ROOT/services/web"
  if [[ ! -d node_modules ]]; then
    pnpm install --frozen-lockfile
  fi
  pnpm test
)

echo "==> preflight CI: OpenAPI → schema.d.ts drift check"
CI=true bash "$ROOT/scripts/codegen.sh"
git diff --exit-code -- services/web/src/shared/api/schema.d.ts

echo "==> preflight CI OK (matches Actions ci proof + web-and-codegen)"
