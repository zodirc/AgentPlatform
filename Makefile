COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env
COMPOSE_DEV := docker compose -f deploy/docker-compose.yml -f deploy/compose/dev.override.yml --env-file .env
COMPOSE_QUEUE := docker compose -f deploy/docker-compose.yml -f deploy/compose/queue.yml --env-file .env
COMPOSE_RETRIEVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/retrieval.yml --env-file .env
COMPOSE_QUEUE_RETRIEVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/queue.yml -f deploy/compose/retrieval.yml --env-file .env
COMPOSE_HA := docker compose -f deploy/docker-compose.yml -f deploy/compose/ha.yml --env-file .env
DEV_OVERRIDE := deploy/compose/dev.override.yml
EVAL_WORKSPACE := .eval-workspace
EVAL_WORKSPACE_HOST_PATH := ../.eval-workspace
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

.DEFAULT_GOAL := help

.PHONY: help start up down ps logs smoke build migrate gate ci-proof \
	ensure-ops-secret fix-workspace-sources \
	up-web up-api up-runtime restart-web restart-api restart-runtime \
	dev dev-init web-dev docker-prune \
	up-queue up-retrieval up-full up-ha \
	eval eval-p2 eval-all eval-live api-test runtime-test security-audit \
	contracts-test eval-stall eval-ha eval-recorded eval-retrieval eval-queue \
	eval-plan-suggest eval-plan-suggest-tune ux-signals \
	eval-run-isolated load-test codegen alembic-upgrade test-rag retrieval-bench turn-effect-bench eval-writing-rag \
	sync-sources seed-sources retrieval-bench-prod loc

help: ## 显示常用命令
	@echo "日常开发（推荐）"
	@echo "  make start        启动栈，不重建镜像（改代码后配合下面单服务命令）"
	@echo "  make up-web       只重建并重启 web"
	@echo "  make up-api       只重建并重启 api"
	@echo "  make up-runtime   只重建并重启 runtime"
	@echo "  make dev          开发模式：挂载 Python 源码 + 热重载（api/runtime）"
	@echo "  make web-dev      前端 Vite 热更新 http://localhost:5173"
	@echo "  make eval-plan-suggest      Plan 建议金标基线（不改权重）"
	@echo "  make eval-plan-suggest-tune 搜索权重提案（只写 reports）"
	@echo "  make ensure-ops-secret  若空则生成 OPS_TEST_SECRET 并打印评测台 URL"
	@echo "  make fix-workspace-sources  修复 sources/ 权限（资料库可写；seed 只读）"
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
	@echo "  make sync-sources    Turn 外索引 workspace/sources（含挂载 seed）"
	@echo "  make seed-sources    同 sync-sources（常驻库不拷贝，只重建索引）"
	@echo "  make runtime-test 运行时测试"
	@echo "  make loc          统计源码行数（不含依赖/文档/workspace）"

# If OPS_TEST_SECRET is empty/missing in .env, generate once and print Ops URL (docs/29).
# Never overwrites an existing secret.
ensure-ops-secret: ## 确保 .env 有 OPS_TEST_SECRET，并打印 /ops/<secret>/test
	@bash scripts/ensure_ops_test_secret.sh

# Seed RO mount creates sources/ as root; runtime app (uid 1000) must own it to upload.
fix-workspace-sources: ## 修复 /workspace/sources 写权限（不改 seed）
	@bash scripts/ensure_workspace_sources_writable.sh

start: ensure-ops-secret ## 启动栈（不 rebuild，最快）
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory fix-workspace-sources

# Safe: only removes untagged (<none>) images left by retag-after-build.
define docker_auto_prune
	@if [ "$(DOCKER_AUTO_PRUNE)" = "1" ]; then \
	  echo "==> auto-prune dangling images"; \
	  docker image prune -f >/dev/null; \
	fi
endef

up: ensure-ops-secret ## 重建并启动全部服务
	$(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory fix-workspace-sources
	$(docker_auto_prune)

# Secret is consumed by api only. up-web may generate it for the first time — recreate api then.
up-web: ## 只重建 web（若刚生成 OPS 密钥则顺带 recreate api）
	@status=$$(mktemp); \
	OPS_SECRET_STATUS_FILE=$$status bash scripts/ensure_ops_test_secret.sh; \
	gen=$$(grep '^generated=' $$status | cut -d= -f2); rm -f $$status; \
	if [ "$$gen" = "1" ]; then \
	  echo "==> new OPS_TEST_SECRET → recreating api to load env"; \
	  $(COMPOSE) up -d --no-deps --force-recreate api; \
	fi
	$(COMPOSE) up -d --build web
	$(docker_auto_prune)

up-api: ensure-ops-secret ## 只重建 api
	$(COMPOSE) up -d --build api
	$(docker_auto_prune)

up-runtime: ## 只重建 runtime
	$(COMPOSE) up -d --build runtime
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
	$(COMPOSE_QUEUE_RETRIEVAL) --profile queue --profile retrieval down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f api runtime

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

eval:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="$(EVAL_STUB_ENV)" EVAL_ARGS="--phase 1"
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="$(EVAL_STUB_ENV)" EVAL_ARGS="--phase 1b"

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
	cd services/api && pip install -q -e ".[dev]" 2>/dev/null || pip install -q pytest pydantic-settings httpx
	PYTHONPATH=services/api pytest services/api/tests -q

runtime-test:
	@if python3 -c 'import sys; exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; then \
		  cd services/runtime && pip install -q -e ".[dev]" && pytest tests -q \
		    --cov=app --cov-report=term-missing --cov-fail-under=80; \
	else \
	  docker compose -f deploy/docker-compose.yml --env-file .env exec -T -u root runtime rm -rf /tmp/runtime-tests && \
	  docker cp services/runtime/tests/. agent-runtime:/tmp/runtime-tests/ && \
	  docker compose -f deploy/docker-compose.yml --env-file .env exec -T runtime bash -c \
	    'pip install -q pytest pytest-asyncio pytest-cov 2>/dev/null; PYTHONPATH=/app python -m pytest /tmp/runtime-tests -q --asyncio-mode=auto'; \
	fi

sync-sources: ## Turn 外增量索引 workspace/sources（含 RO 挂载的 seed；docs/15）
	$(COMPOSE) exec -T runtime python -c 'import asyncio; from app.retrieval.index_scheduler import run_sources_index_sync; print(asyncio.run(run_sources_index_sync(reason="make")))'

seed-sources: ## 同 sync-sources：对挂载的常驻 seed 重新建索引（不拷贝文件）
	@$(MAKE) sync-sources

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
