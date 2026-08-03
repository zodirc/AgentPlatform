COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env
COMPOSE_DEV := docker compose -f deploy/docker-compose.yml -f deploy/compose/dev.override.yml --env-file .env
COMPOSE_QUEUE := docker compose -f deploy/docker-compose.yml -f deploy/compose/queue.yml --env-file .env
COMPOSE_RETRIEVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/retrieval.yml --env-file .env
COMPOSE_QUEUE_RETRIEVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/queue.yml -f deploy/compose/retrieval.yml --env-file .env
COMPOSE_HA := docker compose -f deploy/docker-compose.yml -f deploy/compose/ha.yml --env-file .env
COMPOSE_OPS_EVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/ops-eval.yml --env-file .env
DEV_OVERRIDE := deploy/compose/dev.override.yml
EVAL_WORKSPACE := .eval-workspace
EVAL_WORKSPACE_HOST_PATH := ../.eval-workspace
# Daily make up/start enable Ops bench via profile. Not exported — CI/smoke/eval
# must not inherit it (see scripts/proof_compose_env.sh / smoke_test.sh).
COMPOSE_PROFILES ?= bench
# Isolated stub golden uses runtime-lite (hash, thin Dockerfile) so evals do not
# rebuild the default sentence-transformers image. Restore uses main COMPOSE (live + ST).
EVAL_COMPOSE_FILES ?= -f deploy/docker-compose.yml -f deploy/compose/runtime-lite.yml
EVAL_COMPOSE_PROFILES ?=
EVAL_UP_ARGS ?=
# Recreate api+runtime together so both bind the same WORKSPACE_HOST_PATH
# (.eval-workspace). Smoke leaves api on the daily ../workspace mount — if only
# runtime is remounted, fixtures and admin paths can diverge on CI.
EVAL_UP_SERVICES ?= runtime api
EVAL_RUNTIME_ENV ?=
EVAL_RESTORE_SERVICES ?= runtime api
EVAL_BUILD ?=
# After compose --build, prune dangling images (set DOCKER_AUTO_PRUNE=0 to skip).
DOCKER_AUTO_PRUNE ?= 1
# docs/38: set *_REBUILD_DEPS=1 to force --no-cache (rebuild pip/ST deps layers).
API_REBUILD_DEPS ?= 0
RUNTIME_REBUILD_DEPS ?= 0
WEB_REBUILD_DEPS ?= 0

.DEFAULT_GOAL := help

.PHONY: help start up down ps logs smoke build migrate gate ci-proof \
	ensure-ops-secret fix-workspace-sources \
	up-web up-api up-runtime up-bench up-ops-eval restart-web restart-api restart-runtime \
	dev dev-init web-dev docker-prune \
	up-queue up-retrieval up-full up-ha \
	eval eval-p2 eval-all eval-live api-test runtime-test security-audit \
	contracts-test eval-stall eval-ha eval-recorded eval-retrieval eval-queue \
	eval-plan-suggest eval-plan-suggest-tune ux-signals \
	eval-run-isolated load-test codegen alembic-upgrade test-rag retrieval-bench turn-effect-bench eval-writing-rag \
	sync-sources seed-sources intel-corpus-fetch retrieval-bench-prod loc \
	preflight preflight-ci preflight-unit hooks-install ensure-git-hooks backup \
	official-bench-paths official-bench-pull official-bench-retrieval \
	official-bench-context official-bench-coding-pull official-bench-coding-infer \
	official-bench-coding-eval official-bench-all official-bench-publish \
	official-bench-update-baseline official-bench-show-baseline \
	official-bench-compare official-bench-live \
	official-bench-retrieval-agent official-bench-context-agent \
	official-bench-coding-infer-agent c3-retrieval-grid

help: ## 显示常用命令
	@echo "日常开发（推荐）"
	@echo "  make start        启动栈，不重建镜像（改代码后配合下面单服务命令）"
	@echo "  make up-web       只重建 web（WEB_REBUILD_DEPS=1 强制 pnpm 重装）"
	@echo "  make up-api       只重建 api（API_REBUILD_DEPS=1 强制 pip 重装）"
	@echo "  make up-runtime   只重建 runtime（RUNTIME_REBUILD_DEPS=1 含 ST 烘焙）"
	@echo "  make up-bench     只重建 Ops Bench worker（真向量评测，与 agent 解耦）"
	@echo "  make dev          开发模式：挂载 Python 源码 + 热重载（api/runtime）"
	@echo "  make web-dev      前端 Vite 热更新 http://localhost:5173"
	@echo "  make eval-plan-suggest      Plan 建议金标基线（不改权重）"
	@echo "  make eval-plan-suggest-tune 搜索权重提案（只写 reports）"
	@echo "  make ensure-ops-secret  若空则生成 OPS_TEST_SECRET 并打印评测台 URL"
	@echo "  make up-ops-eval     给 api 挂 docker.sock（Ops 完整证明 ≡ CI 必需）"
	@echo "  make fix-workspace-sources  修复 sources/ 权限（资料库可写；seed 只读）"
	@echo "  # docs/38：改 app 代码不必 *_REBUILD_DEPS；改 pyproject/模型才需要"
	@echo ""
	@echo "完整部署"
	@echo "  make up           重建并启动全部服务（默认 live + pgvector + embedding）"
	@echo "  make up-ha        双 runtime HA（多用户同时跑 Turn；docs/27 MT7）"
	@echo "  make up-full      全栈：queue worker + retrieval overlay"
	@echo "  make build        只构建镜像，不启动（结束后自动清理悬空镜像）"
	@echo "  make docker-prune 额外清理：悬空镜像 + 旧 build cache"
	@echo "  make down         停止"
	@echo "  make ps / logs    状态 / 日志"
	@echo ""
	@echo "其他"
	@echo "  make migrate      数据库迁移"
	@echo "  make smoke        冒烟测试"
	@echo "  make gate         Proof 一键门禁（smoke→eval-all→runtime-test；docs/28）"
	@echo "  make ux-signals   体验信号日聚合/告警（docs/28 PX1；环外，不进 Turn）"
	@echo "  make test-rag     RAG 检索效果对比（根目录一条命令）"
	@echo "  make retrieval-bench 离线检索 A/B（docs/15 契约近似；hash）"
	@echo "  make retrieval-bench-prod 真相档难 qrels（ST+pgvector；docs/15 IX4）"
	@echo "  make official-bench-live     live 实测官方小量（禁 dry/skip；需 BENCH_MODEL_*）"
	@echo "  make official-bench-compare  latest vs 仓库 SCORECARD/baseline Δ 表"
	@echo "  make official-bench-update-baseline  认可后写入 baseline+SCORECARD"
	@echo "  make sync-sources    Turn 外索引（进度在本终端；含挂载 seed）"
	@echo "  make seed-sources    同 sync-sources（常驻库不拷贝，只重建索引）"
	@echo "  make intel-corpus-fetch  拉取/转换 intel vendor 语料（gitignore；docs seed/intel）"
	@echo "  make runtime-test 运行时测试"
	@echo "  make preflight       推送前 unit 门禁（pre-push 默认；无长连接风险）"
	@echo "  make preflight-ci    全量本地 CI（ci_proof+web；久；推送前手动跑）"
	@echo "  make hooks-install 启用 .githooks（make up/start 也会自动装）"
	@echo "  make loc          统计源码行数（不含依赖/文档/workspace）"

# If OPS_TEST_SECRET is empty/missing in .env, generate once and print Ops URL (docs/29).
# Never overwrites an existing secret.
ensure-ops-secret: ## 确保 .env 有 OPS_TEST_SECRET，并打印 /ops/<secret>/test
	@bash scripts/ensure_ops_test_secret.sh

ensure-git-hooks: ## 本仓库 core.hooksPath=.githooks（make up/start 默认）
	@bash scripts/install-git-hooks.sh

# Seed RO mount creates sources/ as root; runtime app (uid 1000) must own it to upload.
fix-workspace-sources: ## 修复 /workspace/sources 写权限（不改 seed）
	@bash scripts/ensure_workspace_sources_writable.sh

start: ensure-ops-secret ensure-git-hooks ## 启动栈（不 rebuild，最快）
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE) up -d
	@$(MAKE) --no-print-directory fix-workspace-sources

# Safe: only removes untagged (<none>) images left by retag-after-build.
define docker_auto_prune
	@if [ "$(DOCKER_AUTO_PRUNE)" = "1" ]; then \
	  echo "==> auto-prune dangling images"; \
	  docker image prune -f >/dev/null; \
	fi
endef

up: ensure-ops-secret ensure-git-hooks ## 重建并启动全部服务
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory fix-workspace-sources
	$(docker_auto_prune)

# Secret is consumed by api only. up-web may generate it for the first time — recreate api then.
# --no-deps: do not rebuild/restart depends_on (api→runtime); otherwise up-api pays runtime ST/pip.
up-web: ## 只重建 web（WEB_REBUILD_DEPS=1 → --no-cache）
	@status=$$(mktemp); \
	OPS_SECRET_STATUS_FILE=$$status bash scripts/ensure_ops_test_secret.sh; \
	gen=$$(grep '^generated=' $$status | cut -d= -f2); rm -f $$status; \
	if [ "$$gen" = "1" ]; then \
	  echo "==> new OPS_TEST_SECRET → recreating api to load env"; \
	  $(COMPOSE) up -d --no-deps --force-recreate api; \
	fi
	@if [ "$(WEB_REBUILD_DEPS)" = "1" ]; then \
	  echo "==> WEB_REBUILD_DEPS=1 → docker compose build --no-cache web"; \
	  $(COMPOSE) build --no-cache web; \
	fi
	$(COMPOSE) up -d --no-deps --build web
	$(docker_auto_prune)

up-api: ensure-ops-secret ## 只重建 api（API_REBUILD_DEPS=1 → --no-cache）
	@if [ "$(API_REBUILD_DEPS)" = "1" ]; then \
	  echo "==> API_REBUILD_DEPS=1 → docker compose build --no-cache api"; \
	  $(COMPOSE) build --no-cache api; \
	fi
	$(COMPOSE) up -d --no-deps --build api
	$(docker_auto_prune)

# Opt-in: mount docker.sock so Ops「完整证明」proof_available=true (docs/29).
# Plain make up / up-api intentionally omit the socket (security default).
up-ops-eval: ensure-ops-secret ## api + docker.sock（启用 Ops suite=ci）
	$(COMPOSE_OPS_EVAL) up -d --no-deps --force-recreate api
	@echo "==> Ops 完整证明已启用；刷新 /ops/<OPS_TEST_SECRET>/test"
	@echo "    注意：之后再 make up / up-api 会去掉 sock，需重跑本目标"

up-runtime: ## 只重建 runtime（RUNTIME_REBUILD_DEPS=1 → --no-cache，含 ST）
	@if [ "$(RUNTIME_REBUILD_DEPS)" = "1" ]; then \
	  echo "==> RUNTIME_REBUILD_DEPS=1 → docker compose build --no-cache runtime"; \
	  $(COMPOSE) build --no-cache runtime; \
	fi
	$(COMPOSE) up -d --no-deps --build runtime
	$(docker_auto_prune)

up-bench: ensure-ops-secret ## 只重建 Ops Bench worker（真向量评测，与 agent 解耦）
	@if [ "$(BENCH_REBUILD_DEPS)" = "1" ]; then \
	  echo "==> BENCH_REBUILD_DEPS=1 → docker compose build --no-cache bench"; \
	  COMPOSE_PROFILES=bench $(COMPOSE) build --no-cache bench; \
	fi
	@echo "==> ensuring dedicated bench-postgres (isolated from agent-postgres)"
	COMPOSE_PROFILES=bench $(COMPOSE) up -d bench-postgres
	COMPOSE_PROFILES=bench $(COMPOSE) up -d --build bench
	$(docker_auto_prune)

restart-web: ## 重启 web（不 rebuild）
	$(COMPOSE) restart web

restart-api: ## 重启 api（不 rebuild）
	$(COMPOSE) restart api

restart-runtime: ## 重启 runtime（不 rebuild）
	$(COMPOSE) restart runtime

dev-init: ## 生成本地 dev.override.yml（首次一次）
	@test -f $(DEV_OVERRIDE) || cp deploy/compose/dev.override.yml.example $(DEV_OVERRIDE)
	@echo "Created $(DEV_OVERRIDE)"

dev: dev-init ## 开发模式：Python 热重载（需先 make start 或 make up）
	$(COMPOSE_DEV) up -d api runtime

web-dev: ## 前端开发服务器（代理 /api → localhost:8000）
	cd services/web && corepack enable && pnpm dev

down:
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE_QUEUE_RETRIEVAL) --profile queue --profile retrieval down

ps:
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE) ps

logs:
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE) logs -f api runtime

build:
	$(COMPOSE) build
	$(docker_auto_prune)

docker-prune: ## 清理悬空镜像 + 全部未用 build cache（可回收那 ~几十 GB）
	@echo "==> dangling images"
	docker image prune -f
	@echo "==> unused build cache (all; ACTIVE=0 is safe)"
	docker builder prune -af
	@echo "==> done; docker system df:"
	@docker system df

backup: ## 备份 Postgres（pg_dump）+ agent_data 卷（保留最近 7 份）
	bash deploy/backup.sh

smoke:
	bash scripts/smoke_test.sh

gate: ## Docker 门禁：smoke → eval-all → runtime-test（完整 CI 请用 make ci-proof）
	bash scripts/gate.sh

ci-proof: ## 完整 CI 证明（≡ GitHub Actions / Ops suite=ci；unit 后 gate 不再重复 pytest）
	bash scripts/ci_proof.sh

ux-signals: ## 体验信号聚合+告警（docs/28 PX1；默认跑夹具自检）
	python3 scripts/ux_signals.py --self-check

test-rag: ## RAG 检索效果：配置 + 查询对比 + tool_result 预览
	bash scripts/test_rag.sh

# Isolated stub golden: no live keys; skip sources watch/sync so StartTurn is not
# racing startup index (docs/15 index plane vs Turn hot path).
EVAL_STUB_ENV := MODEL_MODE=stub SOURCES_STARTUP_SYNC_ENABLED=false SOURCES_WATCH_ENABLED=false

# F8: one isolated stack for both phases — the two-pass version recreated the
# stack twice and (via the old prefix phase match) ran every 1b case twice.
eval:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="$(EVAL_STUB_ENV)" EVAL_ARGS="--phase 1,1b"

eval-p2:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="$(EVAL_STUB_ENV)" EVAL_ARGS="--phase 2"

eval-p3:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="$(EVAL_STUB_ENV)" EVAL_ARGS="--phase 3"

eval-all:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="$(EVAL_STUB_ENV)"

eval-rubric:
	python3 scripts/eval_rubric.py --sample-rate 0.05

eval-plan-suggest: ## Plan 建议金标基线（docs/26 PS4；不改权重）
	PYTHONPATH=services/runtime python3 scripts/plan_suggest_eval.py

eval-plan-suggest-tune: ## Plan 建议权重网格搜索（只写 reports 提案）
	PYTHONPATH=services/runtime python3 scripts/plan_suggest_eval.py --tune

eval-live:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="MODEL_MODE=live" EVAL_ARGS="--mode live"

eval-run-isolated:
	@mkdir -p $(EVAL_WORKSPACE)
	@chmod 777 $(EVAL_WORKSPACE)
	@set -eu; \
	restore_runtime() { \
	  rc=$$?; \
	  trap - EXIT; \
	  if [ "$${EVAL_SKIP_RESTORE:-0}" = "1" ]; then \
	    echo "Skipping eval restore (EVAL_SKIP_RESTORE=1; outer gate owns cleanup)"; \
	    exit $$rc; \
	  fi; \
	  echo "Restoring ordinary runtime workspace..."; \
	  restore_once() { \
	    env -u WORKSPACE_HOST_PATH $(COMPOSE) \
	      up -d --force-recreate --remove-orphans \
	      $(EVAL_RESTORE_SERVICES); \
	    env -u WORKSPACE_HOST_PATH $(COMPOSE) \
	      up -d --wait --wait-timeout 180 \
	      $(EVAL_RESTORE_SERVICES) \
	      || echo "WARNING: restore containers up but not healthy yet; run: docker compose ps"; \
	  }; \
	  if ! restore_once; then \
	    echo "Retrying ordinary runtime restore..."; \
	    sleep 3; \
	    restore_once || echo "WARNING: automatic runtime restore failed; run 'make start'"; \
	  fi; \
	  if [ "$${DOCKER_AUTO_PRUNE:-1}" = "1" ]; then \
	    echo "Auto-prune dangling images after eval restore..."; \
	    docker image prune -f >/dev/null || true; \
	  fi; \
	  exit $$rc; \
	}; \
	trap restore_runtime EXIT; \
	if ! env $(EVAL_RUNTIME_ENV) WORKSPACE_HOST_PATH=$(EVAL_WORKSPACE_HOST_PATH) \
	  docker compose $(EVAL_COMPOSE_FILES) --env-file .env $(EVAL_COMPOSE_PROFILES) \
	  up -d $(EVAL_BUILD) --wait --wait-timeout 180 --force-recreate \
	  $(EVAL_UP_ARGS) $(EVAL_UP_SERVICES); then \
	  echo "Eval runtime recreate raced with Docker; retrying once..."; \
	  sleep 2; \
	  env $(EVAL_RUNTIME_ENV) WORKSPACE_HOST_PATH=$(EVAL_WORKSPACE_HOST_PATH) \
	    docker compose $(EVAL_COMPOSE_FILES) --env-file .env $(EVAL_COMPOSE_PROFILES) \
	    up -d --wait --wait-timeout 180 --force-recreate \
	    $(EVAL_UP_ARGS) $(EVAL_UP_SERVICES); \
	fi; \
	if [ "$${DOCKER_AUTO_PRUNE:-1}" = "1" ] && [ -n "$(EVAL_BUILD)" ]; then \
	  echo "Auto-prune dangling images after eval build..."; \
	  docker image prune -f >/dev/null || true; \
	fi; \
	echo "Waiting for api → runtime readiness..."; \
	i=0; \
	while [ $$i -lt 60 ]; do \
	  if docker compose -f deploy/docker-compose.yml --env-file .env exec -T api \
	    python -c 'import os,urllib.request; urllib.request.urlopen(os.environ.get("RUNTIME_URL","http://runtime:8001").rstrip("/")+"/health/live", timeout=3).read()' \
	    >/dev/null 2>&1; then \
	    echo "runtime health/live ok"; \
	    break; \
	  fi; \
	  i=$$((i+1)); \
	  sleep 2; \
	done; \
	if [ $$i -ge 60 ]; then \
	  echo "ERROR: runtime not reachable from api after wait"; \
	  docker compose -f deploy/docker-compose.yml --env-file .env ps; \
	  exit 1; \
	fi; \
	echo "Probing runtime start-turn auth (expect 422/202)..."; \
	j=0; \
	while [ $$j -lt 30 ]; do \
	  set +e; \
	  out=$$(docker compose -f deploy/docker-compose.yml --env-file .env exec -T api \
	    sh -c 'curl -s -o /dev/null -w "%{http_code}" \
	      -X POST "$${RUNTIME_URL%/}/internal/commands/start-turn" \
	      -H "Content-Type: application/json" \
	      -H "X-Internal-Token: $$INTERNAL_SERVICE_TOKEN" \
	      -d "{\"turn_id\":\"00000000-0000-4000-8000-0000000000aa\",\"run_id\":\"00000000-0000-4000-8000-0000000000bb\",\"session_id\":\"00000000-0000-4000-8000-0000000000cc\",\"scenario_id\":\"agent\",\"message\":\"probe\",\"trace_id\":\"00000000-0000-4000-8000-0000000000dd\"}"' \
	    2>/dev/null | tr -d '\r' | tail -1); \
	  rc=$$?; \
	  set -e; \
	  code=$${out:-0}; \
	  if [ "$$code" = "422" ] || [ "$$code" = "400" ] || [ "$$code" = "202" ]; then \
	    echo "runtime start-turn reachable (HTTP $$code)"; \
	    break; \
	  fi; \
	  if [ "$$code" = "401" ]; then \
	    echo "ERROR: INTERNAL_SERVICE_TOKEN mismatch between api and runtime"; \
	    exit 1; \
	  fi; \
	  j=$$((j+1)); \
	  sleep 2; \
	done; \
	if [ $$j -ge 30 ]; then \
	  echo "ERROR: runtime start-turn probe failed (last HTTP $${code:-0})"; \
	  docker compose -f deploy/docker-compose.yml --env-file .env logs --tail=40 runtime api; \
	  exit 1; \
	fi; \
	echo "Reclaim eval workspace perms (world-writable; do not chown — runtime is uid 1000)..."; \
	docker compose -f deploy/docker-compose.yml --env-file .env exec -u 0 -T runtime \
	  sh -c "find /workspace \\( -path /workspace/sources/seed -o -path '/workspace/sources/seed/*' \\) -prune -o \\( -type d -exec chmod 0777 {} + \\) -o \\( -type f -exec chmod 0666 {} + \\); true"; \
	chmod -R a+rwX $(EVAL_WORKSPACE) 2>/dev/null || true; \
	env $(EVAL_RUNTIME_ENV) WORKSPACE_HOST_PATH=$(EVAL_WORKSPACE_HOST_PATH) \
	  PYTHONUNBUFFERED=1 python3 -u scripts/eval_run.py --workspace $(EVAL_WORKSPACE) $(EVAL_ARGS)

api-test:
	@if python3 -c 'import sys; exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; then \
		  cd services/api && python3 -m pip install -q -e ".[dev]" && \
		  PYTHONPATH=. python3 -m pytest tests -q; \
	else \
	  docker compose -f deploy/docker-compose.yml --env-file .env exec -T -u root api rm -rf /tmp/api-tests && \
	  docker cp services/api/tests/. agent-api:/tmp/api-tests/ && \
	  docker compose -f deploy/docker-compose.yml --env-file .env exec -T api bash -c \
	    'python -m pip install -q pytest pytest-asyncio httpx 2>/dev/null; \
	     if [ -d /repo/services/api/app ]; then export PYTHONPATH=/repo/services/api; else export PYTHONPATH=/app; fi; \
	     python -m pytest /tmp/api-tests -q --asyncio-mode=auto'; \
	fi

runtime-test:
	@if python3 -c 'import sys; exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; then \
		  cd services/runtime && python3 -m pip install -q -e ".[dev]" && \
		  python3 -m pytest tests -q --cov=app --cov-report=term-missing --cov-fail-under=80; \
	else \
	  docker compose -f deploy/docker-compose.yml --env-file .env exec -T -u root runtime rm -rf /tmp/runtime-tests /tmp/eval && \
	  docker compose -f deploy/docker-compose.yml --env-file .env exec -T -u root runtime mkdir -p /tmp/eval/plan_suggest && \
	  docker cp services/runtime/tests/. agent-runtime:/tmp/runtime-tests/ && \
	  docker cp eval/plan_suggest/cases.json agent-runtime:/tmp/eval/plan_suggest/cases.json && \
	  docker compose -f deploy/docker-compose.yml --env-file .env exec -T runtime bash -c \
	    'python -m pip install -q pytest pytest-asyncio pytest-cov 2>/dev/null; PYTHONPATH=/app python -m pytest /tmp/runtime-tests -q --asyncio-mode=auto'; \
	fi

# Prefer local venv/system pip; else Docker (make up). Force: PREFLIGHT_DOCKER=1
preflight: ## 推送前 unit 门禁（≡ pre-push 默认）
	@bash scripts/preflight_unit.sh

preflight-unit: preflight ## 同 make preflight（兼容旧目标名）

preflight-ci: ## 全量本地 CI（≡ Actions；久。建议: make preflight-ci && SKIP_PREFLIGHT=1 git push）
	@bash scripts/preflight_ci.sh

hooks-install: ensure-git-hooks ## 同 ensure-git-hooks（兼容旧目标名）

sync-sources: ## Turn 外增量索引（进度打到本终端 stderr；docs/15）
	@echo "==> sync-sources: cold Python process (loads embedder first; can be silent 1–3 min)"
	$(COMPOSE) exec -T -e PYTHONUNBUFFERED=1 runtime python -c "$$SYNC_SOURCES_PY"

# Inline so progress works even before image rebuild copies sync_cli.py.
define SYNC_SOURCES_PY
import asyncio, json, logging, sys
sys.stderr.reconfigure(line_buffering=True) if hasattr(sys.stderr, "reconfigure") else None
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)
logging.getLogger("app.retrieval").setLevel(logging.INFO)
from app.retrieval.index_scheduler import run_sources_index_sync
r = asyncio.run(run_sources_index_sync(reason="make"))
print(json.dumps(r, ensure_ascii=False, default=str), flush=True)
raise SystemExit(0 if str(r.get("status") or "ok") == "ok" else 1)
endef
export SYNC_SOURCES_PY

seed-sources: ## 同 sync-sources：对挂载的常驻 seed 重新建索引（不拷贝文件）
	@$(MAKE) sync-sources

# ONLY=id1,id2 optional. Requires network + git. Does not touch Turn hot path.
intel-corpus-fetch: ## 按 SOURCES.yaml 拉取并转换 intel vendor（≤150MiB；gitignore）
	@python3 -c 'import yaml' 2>/dev/null || pip install -q pyyaml
	@python3 scripts/intel_corpus_fetch.py $(if $(ONLY),--only $(ONLY),)

security-audit:
	bash scripts/security_audit.sh

loc: ## 统计源码行数（不含依赖/文档/workspace）
	python3 scripts/loc.py

contracts-test:
	pip install -q jsonschema pytest pyyaml && pytest packages/contracts/tests -q
	pip install -q packages/contracts/python && pytest packages/contracts/python/tests -q
	$(MAKE) retrieval-bench
	$(MAKE) api-test
	$(MAKE) runtime-test

up-queue:
	WORKER_MODE=outbox $(COMPOSE_QUEUE) --profile queue up -d --build
	$(docker_auto_prune)

up-retrieval: ## 兼容入口（主 compose 已默认 Dockerfile.retrieval + embedding）
	INDEX_VIA_WORKER=true RETRIEVAL_MODE=hybrid $(COMPOSE_RETRIEVAL) --profile retrieval up -d --build
	$(docker_auto_prune)

up-full: ## 全栈：redis/worker（embedding 已在默认 up 中）
	WORKER_MODE=outbox INDEX_VIA_WORKER=true RETRIEVAL_MODE=hybrid \
	  $(COMPOSE_QUEUE_RETRIEVAL) --profile queue --profile retrieval up -d --build
	$(docker_auto_prune)

up-ha:
	$(COMPOSE_HA) up -d --build --scale runtime=0
	$(docker_auto_prune)

eval-stall:
	$(MAKE) eval-run-isolated \
	  EVAL_BUILD=--build \
	  EVAL_RUNTIME_ENV="MODEL_MODE=stub STALL_THRESHOLD_SECONDS=8 STALL_POLL_INTERVAL_SECONDS=2 STALL_AUTO_FAIL=true MODEL_TIMEOUT_SECONDS=120" \
	  EVAL_ARGS="--filter stall_watchdog --include-stall"

eval-ha:
	$(MAKE) eval-run-isolated \
	  EVAL_BUILD=--build \
	  EVAL_COMPOSE_FILES="-f deploy/docker-compose.yml -f deploy/compose/ha.yml" \
	  EVAL_UP_ARGS="--scale runtime=0" EVAL_UP_SERVICES= \
	  EVAL_RESTORE_SERVICES="api runtime" \
	  EVAL_RUNTIME_ENV="MODEL_MODE=stub" \
	  EVAL_ARGS="--filter ha_runner --include-ha"

eval-recorded:
	$(MAKE) eval-run-isolated EVAL_BUILD=--build EVAL_RUNTIME_ENV="MODEL_MODE=recorded" \
	  EVAL_ARGS="--filter recorded --include-recorded --mode recorded"

eval-retrieval:
	pip install -q websockets 2>/dev/null || true
	$(MAKE) eval-run-isolated \
	  EVAL_BUILD=--build \
	  EVAL_COMPOSE_FILES="-f deploy/docker-compose.yml" \
	  EVAL_RUNTIME_ENV="MODEL_MODE=stub INDEX_VIA_WORKER=true RETRIEVAL_MODE=hybrid EMBEDDING_BACKEND=sentence_transformers" \
	  EVAL_ARGS="--filter writing.07"

eval-path-prefix: ## writing.14 path_prefix golden（isolated stub + runtime-lite）
	pip install -q websockets 2>/dev/null || true
	$(MAKE) eval-run-isolated \
	  EVAL_BUILD=--build \
	  EVAL_RUNTIME_ENV="MODEL_MODE=stub RETRIEVAL_MODE=keyword INDEX_VIA_WORKER=false" \
	  EVAL_ARGS="--filter writing.14"

# Official small benches (pull-to-BENCH_DATA_DIR; eval/official/README.md)
OFFICIAL_BENCH_PY ?= python3
CONTEXT_DRY ?= 0
OFFICIAL_SWE_SKIP_API ?= 0
OFFICIAL_CONTEXT_LIMIT ?= 0
OFFICIAL_SWE_TIER ?= n25
OFFICIAL_SWE_N ?=
OFFICIAL_SWE_HARNESS ?= 0
QUERY_LIMIT ?= 0

official-bench-paths: ## 打印官方评测数据/报告目录
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py paths

official-bench-pull: ## 拉取 BEIR + LongBench 小切片 + SWE-bench Lite（需网络）
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py pull --suite all

official-bench-retrieval: ## 官方 BEIR 小量（hybrid 主分 + BM25 对照）
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py retrieval

# L1 agent-path（产品 Turn；需 make up + OPS_TEST_SECRET + BENCH_MODEL_*）
# 冒烟可加 QUERY_LIMIT=5 / OFFICIAL_CONTEXT_LIMIT=3 / OFFICIAL_SWE_TIER=n3
official-bench-retrieval-agent: ## L1 BEIR：search_sources via Turn（Ops API）
	set -a && [ -f .env ] && . ./.env; set +a; \
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py retrieval --eval-path agent \
	  --query-limit $(QUERY_LIMIT)

official-bench-context: ## 官方 LongBench 小量双臂（CONTEXT_DRY=1 仅流水线）
	@if [ "$(CONTEXT_DRY)" = "1" ]; then \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py context --dry-metrics --limit $(OFFICIAL_CONTEXT_LIMIT); \
	else \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py context --limit $(OFFICIAL_CONTEXT_LIMIT); \
	fi

official-bench-context-agent: ## L1 LongBench：落盘 + Turn 终答（Ops API）
	set -a && [ -f .env ] && . ./.env; set +a; \
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py context --eval-path agent \
	  --limit $(OFFICIAL_CONTEXT_LIMIT)

official-bench-coding-pull: ## 拉取 SWE-bench Lite 题集
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py coding --phase pull

official-bench-coding-infer: ## SWE tier 推理写 predictions（OFFICIAL_SWE_SKIP_API=1 空补丁）
	@if [ "$(OFFICIAL_SWE_SKIP_API)" = "1" ]; then \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py coding --phase infer --tier $(OFFICIAL_SWE_TIER) $(if $(OFFICIAL_SWE_N),--n-instances $(OFFICIAL_SWE_N),) $(if $(filter 1,$(OFFICIAL_SWE_HARNESS)),--harness,) --skip-api; \
	else \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py coding --phase infer --tier $(OFFICIAL_SWE_TIER) $(if $(OFFICIAL_SWE_N),--n-instances $(OFFICIAL_SWE_N),) $(if $(filter 1,$(OFFICIAL_SWE_HARNESS)),--harness,); \
	fi

official-bench-coding-infer-agent: ## L1 SWE infer：platform Turn（Ops API）
	set -a && [ -f .env ] && . ./.env; set +a; \
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py coding --phase infer --eval-path agent \
	  --tier $(OFFICIAL_SWE_TIER) $(if $(OFFICIAL_SWE_N),--n-instances $(OFFICIAL_SWE_N),)

official-bench-coding-eval: ## 官方 swebench.harness 评分（需 Docker + pip install swebench）
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py coding --phase eval

official-bench-all: ## pull + BEIR；可选 WITH_CONTEXT=1 / WITH_CODING_INFER=1
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py all \
	  $(if $(filter 1,$(WITH_CONTEXT)),--with-context,) \
	  $(if $(filter 1,$(WITH_CODING_INFER)),--with-coding-infer,) \
	  $(if $(filter 1,$(CONTEXT_DRY)),--context-dry-metrics,) \
	  --context-limit $(OFFICIAL_CONTEXT_LIMIT)

official-bench-publish: ## 将 latest（或 RUN_ID=）run 导入 Ops（需 OPS_TEST_SECRET + 栈）
	@set -a; [ -f .env ] && . ./.env; set +a; \
	  test -n "$${OPS_TEST_SECRET:-}" || (echo "OPS_TEST_SECRET missing in env/.env"; exit 1); \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py publish \
	    $(if $(RUN_ID),--run-id $(RUN_ID),) --force

official-bench-update-baseline: ## 将 latest_* 效果分写入仓库 baseline JSON + SCORECARD.md
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py baseline --update \
	  $(if $(SUITES),--suites $(SUITES),)

official-bench-show-baseline: ## 查看已提交的官方 baseline
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py baseline --show

official-bench-compare: ## latest_* vs 仓库 baseline 主指标 Δ（调优看这张表）
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py baseline --compare \
	  $(if $(SUITES),--suites $(SUITES),)

# Live measured official small: ST retrieval + real LLM context/coding (no dry/skip).
# Requires bench stack + BENCH_MODEL_API_KEY (or MODEL_API_KEY) for context/coding.
# LIVE_SWE_TIER defaults to n10 (affordable loops); override LIVE_SWE_TIER=n25 etc.
LIVE_SWE_TIER ?= n10
official-bench-live: ## live 实测官方小量 → compare（不自动改 baseline）
	@set -a; [ -f .env ] && . ./.env; set +a; \
	  key="$${BENCH_MODEL_API_KEY:-$${MODEL_API_KEY:-$${OPENAI_API_KEY:-}}}"; \
	  if [ -z "$$key" ]; then \
	    echo "ERROR: live context/coding need BENCH_MODEL_API_KEY (or MODEL_API_KEY)"; \
	    exit 1; \
	  fi; \
	  echo "==> official-bench-live protocol=$$(grep -E '^protocol_version:' eval/official/suites.small.yaml | head -1)"; \
	  echo "==> SWE tier=$(LIVE_SWE_TIER) harness=$(OFFICIAL_SWE_HARNESS) (SKIP_API forced off)"; \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py pull --suite all; \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py retrieval; \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py context --limit $(OFFICIAL_CONTEXT_LIMIT); \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py coding --phase infer \
	    --tier $(LIVE_SWE_TIER) $(if $(OFFICIAL_SWE_N),--n-instances $(OFFICIAL_SWE_N),) \
	    $(if $(filter 1,$(OFFICIAL_SWE_HARNESS)),--harness,); \
	  echo ""; echo "==> compare vs committed baseline"; \
	  $(OFFICIAL_BENCH_PY) scripts/official_bench_run.py baseline --compare; \
	  echo ""; echo "认可本次则: make official-bench-update-baseline && git add eval/official/baseline/"

retrieval-bench: ## 离线检索 A/B（docs/15 契约近似；json+hash）
	@cd services/runtime && \
	  if test -x .venv/bin/python; then PY=.venv/bin/python; else PY=python3; fi && \
	  $$PY ../../scripts/retrieval_bench.py --mode hybrid && \
	  $$PY ../../scripts/retrieval_bench.py --mode keyword

retrieval-bench-prod: ## IX4 真相档难 qrels（容器内 ST+pgvector；隔离 schema retrieval_bench）
	@test -f .env || (echo "missing .env"; exit 1)
	$(COMPOSE) exec -T -u root runtime mkdir -p /tmp/ix4-bench
	docker cp scripts/retrieval_bench.py agent-runtime:/tmp/ix4-bench/retrieval_bench.py
	docker cp eval/retrieval/. agent-runtime:/tmp/ix4-bench/retrieval/
	$(COMPOSE) exec -T runtime bash -c '\
	  pip install -q pyyaml 2>/dev/null; \
	  PYTHONPATH=/app python /tmp/ix4-bench/retrieval_bench.py --prod \
	    --qrels /tmp/ix4-bench/retrieval/qrels_hard.yaml \
	    --corpus /tmp/ix4-bench/retrieval/corpus \
	    --mode hybrid'

# C-3 Index-plane fusion grid (round1): BEIR L0 ST+pgvector × profiles + prod-bench.
# QUERY_LIMIT=20 smoke (default); QUERY_LIMIT=0 full qrels. Needs profile bench + bench-postgres.
# Runs a one-shot runtime container on the compose network (bench has no runtime retrieval pkg).
C3_QUERY_LIMIT ?= 20
c3-retrieval-grid: ## C-3 RQ1e 网格标定（forced/Index 诊断 ≡ L0 hybrid；不改 SCORECARD）
	@test -f .env || (echo "missing .env"; exit 1)
	COMPOSE_PROFILES=bench $(COMPOSE) up -d bench-postgres
	@echo "==> C-3 grid query_limit=$(C3_QUERY_LIMIT) (Index-plane; no SCORECARD write)"
	docker run --rm --network deploy_default \
	  -v "$(CURDIR):/repo:ro" \
	  -v "$(CURDIR)/eval/official/.local-data:/data/ops-official/data:rw" \
	  -v "$(CURDIR)/eval/reports/official:/data/ops-official/reports:rw" \
	  -e BENCH_DATA_DIR=/data/ops-official/data \
	  -e BENCH_REPORTS_DIR=/data/ops-official/reports \
	  -e BENCH_RETRIEVAL_PROD=1 \
	  -e BENCH_RETRIEVAL_BACKEND=pgvector \
	  -e BENCH_DATABASE_URL=postgresql://bench:bench@bench-postgres:5432/bench \
	  -e DATABASE_URL=postgresql://bench:bench@bench-postgres:5432/bench \
	  -e PYTHONPATH=/repo/services/runtime:/repo/scripts \
	  -e EMBEDDING_MODEL_DIR=/app/models-baked \
	  -e TRANSFORMERS_OFFLINE=1 \
	  -e HF_HUB_OFFLINE=1 \
	  -w /tmp \
	  -u 0 \
	  --entrypoint python \
	  agent-platform-runtime:default \
	  -m official_bench.c3_grid --query-limit $(C3_QUERY_LIMIT)

turn-effect-bench: ## RE2 效果闸（先 MODEL_MODE=stub make up-runtime && migrate）
	python3 scripts/turn_effect_bench.py

eval-writing-rag: ## writing RAG golden 子集（需栈在跑）
	python3 scripts/eval_run.py --filter writing. --base-url http://localhost --workspace workspace

eval-queue:
	$(MAKE) eval-run-isolated \
	  EVAL_BUILD=--build \
	  EVAL_COMPOSE_FILES="-f deploy/docker-compose.yml -f deploy/compose/queue.yml -f deploy/compose/retrieval.yml" \
	  EVAL_COMPOSE_PROFILES="--profile queue --profile retrieval" EVAL_UP_SERVICES= \
	  EVAL_RESTORE_SERVICES="api runtime" \
	  EVAL_RUNTIME_ENV="MODEL_MODE=stub WORKER_MODE=outbox INDEX_VIA_WORKER=true RETRIEVAL_MODE=hybrid" \
	  EVAL_ARGS="--filter outbox_worker --include-queue"

load-test:
	python3 scripts/load_test.py

codegen:
	bash scripts/codegen.sh

migrate:
	$(COMPOSE) exec api python -m app.db.migrate

alembic-upgrade:
	cd services/api && alembic -c alembic.ini upgrade head
