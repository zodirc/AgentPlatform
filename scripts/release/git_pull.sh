#!/usr/bin/env bash
# Safe pull for release console: fetch + ff-only only (no merge commit / rebase).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> git fetch --prune"
git fetch --prune
echo "==> ahead/behind vs @{upstream} (before pull)"
git rev-list --left-right --count HEAD...@{upstream} 2>/dev/null || echo "(no upstream)"
echo "==> git pull --ff-only"
if git pull --ff-only; then
  echo "==> HEAD now: $(git rev-parse --short HEAD) — $(git log -1 --format=%s)"
else
  echo "==> pull failed (可能有本地提交/冲突；请手工处理，不用 --force)" >&2
  exit 1
fi
