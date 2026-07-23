#!/usr/bin/env bash
# Quick RAG smoke: config → search → show what agent loop receives → optional e2e turn.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTAINER="${RAG_TEST_CONTAINER:-agent-runtime}"
QUERY="${1:-phase2-unique-term}"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: container '$CONTAINER' not running. Start stack first: make start"
  exit 1
fi

echo "══════════════════════════════════════════════════════════════"
echo " RAG 效果测试  (query: $QUERY)"
echo "══════════════════════════════════════════════════════════════"
echo

echo "── 1. 当前配置 ──"
docker exec "$CONTAINER" python3 -c "
from app.settings import settings
print('  retrieval_mode     =', settings.retrieval_mode)
print('  embedding_backend  =', settings.embedding_backend)
print('  index_via_worker   =', settings.index_via_worker)
print('  data_dir           =', settings.data_dir)
"

echo
echo "── 2. 检索执行（search_sources 工具）──"
docker exec "$CONTAINER" python3 -c "
import asyncio, json, time
from app.tools.core.tools import sync_sources_index, search_sources
from app.settings import settings

QUERIES = [
    '$QUERY',
    '向量召回的新材料',
    'writing platform citations',
]

async def main():
    t0 = time.perf_counter()
    sync = await sync_sources_index()
    sync_ms = (time.perf_counter() - t0) * 1000
    print(f'  索引同步: {sync_ms:.0f}ms  files={sync.get(\"indexed_files\",0)} chunks={sync.get(\"chunks\",0)}')
    print()
    settings.retrieval_mode = 'hybrid'
    for q in QUERIES:
        t1 = time.perf_counter()
        r = await search_sources(q, limit=3)
        ms = (time.perf_counter() - t1) * 1000
        hits = r.get('hits', [])
        print(f'  Q: {q!r}')
        print(f'     mode={r.get(\"retrieval\")}  hits={len(hits)}  latency={ms:.0f}ms')
        if not hits:
            print('     → 无命中，模型下一轮拿不到证据')
        for h in hits[:2]:
            print(f'     → {h.get(\"path\")}  score={h.get(\"score\",\"-\")}')
            print(f'       excerpt: {str(h.get(\"excerpt\",\"\"))[:72]}')
            print(f'       citation_id: {h.get(\"citation_id\",\"-\")}')
        print()

asyncio.run(main())
"

echo "── 3. 命中后 agent 拿到什么？（tool_result 原文）──"
docker exec "$CONTAINER" python3 -c "
import asyncio, json
from app.tools.core.tools import search_sources
from app.settings import settings

async def main():
    settings.retrieval_mode = 'hybrid'
    r = await search_sources('$QUERY', limit=2)
    print('  下一轮 LLM 收到的 tool_result JSON（节选）:')
    preview = {
        'query': r.get('query'),
        'retrieval': r.get('retrieval'),
        'summary': r.get('summary'),
        'hits': r.get('hits', [])[:2],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    print()
    if r.get('hits'):
        print('  模型可据此: draft_section / propose_patch 写入 [cite:xxx]')
        print('            check_citation 校验引用')
        print('            read_file 读全文')
        print('  ⚠ 命中不会自动改文件，必须模型再调写作工具')
    else:
        print('  ⚠ 无命中 → 模型只能凭已有上下文回答，无法引用资料库')

asyncio.run(main())
"

if [[ "${RAG_TEST_E2E:-}" == "1" ]]; then
  echo
  echo "── 4. 端到端 turn（stub 模型，写作场景）──"
  BASE_URL="${RAG_TEST_BASE_URL:-http://localhost}"
  AUTH_HEADER=$(python3 - <<'PY'
import base64
from pathlib import Path

def _env_val(raw: str) -> str:
    v = raw.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if "#" in v:
        v = v.split("#", 1)[0].rstrip()
    return v.strip()

env = {}
for line in Path(".env").read_text().splitlines():
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = _env_val(v)
if env.get("AUTH_ENABLED", "false").lower() != "true":
    print("")
else:
    pw = env.get("ADMIN_PASSWORD", "admin")
    print("Authorization: Basic " + base64.b64encode(f"admin:{pw}".encode()).decode())
PY
)
  CURL_AUTH=()
  [[ -n "$AUTH_HEADER" ]] && CURL_AUTH+=(-H "$AUTH_HEADER")

  SESSION=$(curl -fsS -X POST "${BASE_URL}/api/v1/sessions" \
    -H 'Content-Type: application/json' "${CURL_AUTH[@]}" -d '{}')
  SESSION_ID=$(echo "$SESSION" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  TURN=$(curl -fsS -X POST "${BASE_URL}/api/v1/sessions/${SESSION_ID}/turns" \
    -H 'Content-Type: application/json' "${CURL_AUTH[@]}" \
    -d "{\"message\":\"引用资料写作 writing.05\",\"scenario_id\":\"writing\",\"client_request_id\":\"00000000-0000-4000-8000-00000005\"}")
  TURN_ID=$(echo "$TURN" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

  SMOKE_AUTH_HEADER="${AUTH_HEADER:-}" python3 - "$BASE_URL" "$TURN_ID" <<'PY'
import json, os, sys, urllib.request
base, turn_id = sys.argv[1], sys.argv[2]
url = f"{base}/api/v1/turns/{turn_id}/stream"
headers = {"Accept": "text/event-stream"}
auth = os.environ.get("SMOKE_AUTH_HEADER", "").strip()
if auth:
    k, v = auth.split(":", 1)
    headers[k.strip()] = v.strip()
req = urllib.request.Request(url, headers=headers)
tool_events, retrieval, output = [], None, []
with urllib.request.urlopen(req, timeout=90) as resp:
    for raw in resp:
        line = raw.decode().strip()
        if not line.startswith("data:"):
            continue
        ev = json.loads(line[5:].strip())
        t = ev.get("type", "")
        if t == "tool.started":
            tool_events.append(ev.get("payload", {}).get("tool_name"))
        if t == "retrieval.completed":
            retrieval = ev.get("payload", {})
        if t == "assistant.delta":
            output.append(ev.get("payload", {}).get("text", ""))
        if t in ("turn.completed", "turn.failed"):
            break
print("  tools called:", " → ".join(tool_events) or "(none)")
if retrieval:
    print(f"  retrieval.completed: mode={retrieval.get('mode')} hits={retrieval.get('hit_count')}")
text = "".join(output)
print(f"  model output: {text[:200] or '(empty)'}")
if "cite:" in text:
    print("  ✓ 成稿含引用标记")
PY
fi

echo
echo "── 对比说明 ──"
echo "  本项目: hybrid（BM25 + 向量 RRF + lexical rerank），结构感知切块 INDEX v3"
echo "  完整栈: make up-retrieval  (sentence-transformers / MiniLM；可选 cross-encoder rerank)"
echo "  端到端: RAG_TEST_E2E=1 ./scripts/test_rag.sh"
echo "══════════════════════════════════════════════════════════════"
