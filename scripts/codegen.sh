#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENAPI="$ROOT/packages/contracts/openapi/public.yaml"
OUT_DIR="$ROOT/services/web/src/shared/api"

mkdir -p "$OUT_DIR"

if ! command -v npx >/dev/null 2>&1; then
  echo "npx not found; skip TS codegen (Phase 0 web uses minimal TS)"
  exit 0
fi

if [[ ! -f "$OPENAPI" ]]; then
  echo "OpenAPI spec missing: $OPENAPI"
  exit 1
fi

cd "$ROOT/services/web"
if [[ ! -d node_modules ]]; then
  corepack enable
  pnpm install
fi

npx openapi-typescript "$OPENAPI" -o "$OUT_DIR/schema.d.ts"
echo "Generated $OUT_DIR/schema.d.ts"
