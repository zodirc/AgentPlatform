#!/usr/bin/env bash
# Point this clone at versioned hooks under .githooks/ (default for make up/start).
# Bypass push preflight: SKIP_PREFLIGHT=1 git push   OR   git push --no-verify
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_SRC="$ROOT/.githooks"

if [[ ! -d "$ROOT/.git" ]]; then
  echo "Not a git checkout: $ROOT" >&2
  exit 1
fi

if [[ ! -d "$HOOKS_SRC" ]]; then
  echo "missing $HOOKS_SRC" >&2
  exit 1
fi

chmod +x "$ROOT/scripts/preflight_unit.sh" "$ROOT/scripts/install-git-hooks.sh"
# Enable every executable hook in .githooks (pre-push, commit-msg, …).
find "$HOOKS_SRC" -maxdepth 1 -type f ! -name '*.sample' -exec chmod +x {} +

# Local only — does not touch global git config. Relative path is resolved from
# the work tree, so hooks stay versioned in-repo without copying into .git/hooks.
git -C "$ROOT" config --local core.hooksPath .githooks

# Drop legacy symlink install if present (ignored once hooksPath is set).
if [[ -L "$ROOT/.git/hooks/pre-push" ]]; then
  rm -f "$ROOT/.git/hooks/pre-push"
fi

current="$(git -C "$ROOT" config --local --get core.hooksPath)"
echo "OK. core.hooksPath=$current (push → scripts/preflight_unit.sh)"
echo "Bypass once: SKIP_PREFLIGHT=1 git push   or   git push --no-verify"
