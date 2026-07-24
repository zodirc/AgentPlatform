#!/usr/bin/env bash
# Install versioned hooks from .githooks/ into this clone's .git/hooks/
# (symlink; no git config required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_SRC="$ROOT/.githooks"
HOOKS_DST="$ROOT/.git/hooks"

if [[ ! -d "$ROOT/.git" ]]; then
  echo "Not a git checkout: $ROOT" >&2
  exit 1
fi

mkdir -p "$HOOKS_DST"
for name in pre-push; do
  src="$HOOKS_SRC/$name"
  dst="$HOOKS_DST/$name"
  if [[ ! -f "$src" ]]; then
    echo "missing $src" >&2
    exit 1
  fi
  chmod +x "$src" "$ROOT/scripts/preflight_unit.sh" "$ROOT/scripts/install-git-hooks.sh"
  ln -sfn "$src" "$dst"
  echo "installed $dst -> $src"
done

echo "OK. Push will run: bash scripts/preflight_unit.sh"
echo "Bypass once: SKIP_PREFLIGHT=1 git push   or   git push --no-verify"
