#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

pip install -q pip-audit

for svc in api runtime; do
  echo "== pip-audit services/$svc =="
  (cd "services/$svc" && pip install -q -e . && pip-audit)
done

if command -v gitleaks >/dev/null 2>&1; then
  echo "== gitleaks =="
  gitleaks detect --source . --config .gitleaks.toml --no-banner
else
  echo "gitleaks not installed locally; skip (CI runs gitleaks-action)"
fi
