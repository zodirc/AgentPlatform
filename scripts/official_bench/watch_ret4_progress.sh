#!/usr/bin/env bash
# Live RET-4 overall progress board (3 models × 3 datasets).
set -euo pipefail
CONTAINER="${1:-batch14-ret4-gpu}"
OUT="${2:-eval/reports/official/batch14/ret4_selection.json}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

while true; do
  clear 2>/dev/null || true
  date '+%F %T'
  docker ps -a --filter "name=^/${CONTAINER}$" --format 'container: {{.Status}}' 2>/dev/null || echo "container: missing"
  nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || true
  echo
  python3 - "$CONTAINER" "$OUT" <<'PY'
import re, subprocess, sys
from pathlib import Path
container, out = sys.argv[1], sys.argv[2]
try:
    log = subprocess.check_output(["docker", "logs", container], stderr=subprocess.STDOUT, text=True, errors="replace")
except Exception as e:
    print("docker logs failed:", e)
    raise SystemExit(0)
models = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
    "thenlper/gte-small",
]
short = {
    "sentence-transformers/all-MiniLM-L6-v2": "MiniLM",
    "BAAI/bge-small-en-v1.5": "bge",
    "thenlper/gte-small": "gte",
}
dss = ["scifact", "nfcorpus", "fiqa"]
done = {}
for m in models:
    for ds in dss:
        ms = re.findall(
            rf"\[RET-4\] {re.escape(m)} {ds} nDCG@10=([0-9.]+) absent@100=(\d+)",
            log,
        )
        if ms:
            done[(m, ds)] = ms[-1]
cur_m = cur_ds = None
for line in log.splitlines():
    m1 = re.search(r"\[RET-4\] loading (.+)$", line)
    if m1:
        cur_m, cur_ds = m1.group(1).strip(), None
    m2 = re.search(r"\[RET-4\] (.+) embed (\w+) corpus", line)
    if m2:
        cur_m, cur_ds = m2.group(1), m2.group(2)
total = 9
n = len(done)
bar = "#" * n + "-" * (total - n)
print(f"progress: [{bar}] {n}/{total} ({100*n/total:.0f}%)")
print()
hdr = f"{'model':<8}" + "".join(f"{ds:^22}" for ds in dss)
print(hdr)
print("-" * len(hdr))
for m in models:
    row = f"{short[m]:<8}"
    for ds in dss:
        if (m, ds) in done:
            ndcg, absnt = done[(m, ds)]
            cell = f"OK {float(ndcg):.3f} a={absnt}"
        elif cur_m == m and cur_ds == ds:
            cell = ">> RUNNING <<"
        elif cur_m == m and cur_ds is None and ds == "scifact" and (m, "scifact") not in done:
            cell = ">> loading <<"
        else:
            cell = "· pending"
        row += f"{cell:^22}"
    print(row)
print()
if cur_m:
    print(f"now: {short.get(cur_m, cur_m)} / {cur_ds or 'loading'}")
p = Path(out)
print(f"json: {'READY ' + str(p) if p.is_file() else 'not yet'}")
if "Wrote" in log and p.is_file():
    print("DONE")
PY
  if [[ -f "$OUT" ]]; then
    echo
    echo "=== ret4_selection.json ready ==="
    break
  fi
  sleep 5
done
