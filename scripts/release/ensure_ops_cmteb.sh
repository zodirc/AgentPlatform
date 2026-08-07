#!/usr/bin/env bash
# Ensure Ops C-MTEB small corpus (~50k docs) is on the compose-mounted host
# path, materialize ops-l1/cmteb-index Works, then embed into retrieval_ops_zh
# (bge-m3 only).
#
# Used by release-console action ensure-ops-cmteb.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

ENV_FILE="${ENV_FILE:-$ROOT/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

# Compose mounts HOST_BENCH_DATA_DIR → /data/ops-official/data. Pull must land here,
# not ~/.cache/agentplatform-bench (default when BENCH_DATA_DIR unset).
DATA_DIR="${HOST_BENCH_DATA_DIR:-$ROOT/eval/official/.local-data}"
case "$DATA_DIR" in
  /data/*) DATA_DIR="$ROOT/eval/official/.local-data" ;;
esac
mkdir -p "$DATA_DIR"
export BENCH_DATA_DIR="$DATA_DIR"
export HOST_BENCH_DATA_DIR="$DATA_DIR"

echo "==> C-MTEB data dir: $BENCH_DATA_DIR (small suite · ~50k docs total)"

need_pull=1
if python3 - "$BENCH_DATA_DIR" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1]) / "cmteb"
if not root.is_dir():
    raise SystemExit(1)
for child in root.iterdir():
    if not child.is_dir():
        continue
    if (
        (child / "corpus.jsonl").is_file()
        and (child / "queries.jsonl").is_file()
        and (child / "qrels" / "test.tsv").is_file()
    ):
        raise SystemExit(0)
raise SystemExit(1)
PY
then
  need_pull=0
  echo "==> C-MTEB corpus already present — skip pull"
fi

if [[ "$need_pull" == "1" ]]; then
  echo "==> pulling C-MTEB small (Covid/Medical/Ecom · ≤50k docs)…"
  HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
    make -C "$ROOT" official-bench-pull-cmteb
fi

echo "==> materialize ops-l1/cmteb-index Works (make ops-cmteb-prepare)…"
make -C "$ROOT" ops-cmteb-prepare

echo "==> embedding into retrieval_ops_zh (make sync-ops-cmteb)…"
make -C "$ROOT" sync-ops-cmteb
echo "==> ensure-ops-cmteb done"
