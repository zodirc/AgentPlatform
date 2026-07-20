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
EVAL_UP_SERVICES ?= runtime
EVAL_RUNTIME_ENV ?=
EVAL_RESTORE_SERVICES ?= runtime
EVAL_BUILD ?=

.DEFAULT_GOAL := help

.PHONY: help start up down ps logs smoke build migrate \
	up-web up-api up-runtime restart-web restart-api restart-runtime \
	dev dev-init web-dev \
	up-queue up-retrieval up-full up-ha \
	eval eval-p2 eval-all eval-live api-test runtime-test security-audit \
	contracts-test eval-stall eval-ha eval-recorded eval-retrieval eval-queue \
	eval-run-isolated load-test codegen alembic-upgrade test-rag retrieval-bench turn-effect-bench eval-writing-rag

help: ## 显示常用命令
	@echo "日常开发（推荐）"
	@echo "  make start        启动栈，不重建镜像（改代码后配合下面单服务命令）"
	@echo "  make up-web       只重建并重启 web"
	@echo "  make up-api       只重建并重启 api"
	@echo "  make up-runtime   只重建并重启 runtime"
	@echo "  make dev          开发模式：挂载 Python 源码 + 热重载（api/runtime）"
	@echo "  make web-dev      前端 Vite 热更新 http://localhost:5173"
	@echo ""
	@echo "完整部署"
	@echo "  make up           重建并启动全部服务（默认 live + pgvector + embedding）"
	@echo "  make up-full      全栈：queue worker + retrieval overlay"
	@echo "  make build        只构建镜像，不启动"
	@echo "  make down         停止"
	@echo "  make ps / logs    状态 / 日志"
	@echo ""
	@echo "其他"
	@echo "  make migrate      数据库迁移"
	@echo "  make smoke        冒烟测试"
	@echo "  make test-rag     RAG 检索效果对比（根目录一条命令）"
	@echo "  make retrieval-bench 离线检索 A/B（docs/28 效果闸层 1）"
	@echo "  make runtime-test 运行时测试"

start: ## 启动栈（不 rebuild，最快）
	$(COMPOSE) up -d

up: ## 重建并启动全部服务
	$(COMPOSE) up -d --build

up-web: ## 只重建 web
	$(COMPOSE) up -d --build web

up-api: ## 只重建 api
	$(COMPOSE) up -d --build api

up-runtime: ## 只重建 runtime
	$(COMPOSE) up -d --build runtime

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

smoke:
	bash scripts/smoke_test.sh

test-rag: ## RAG 检索效果：配置 + 查询对比 + tool_result 预览
	bash scripts/test_rag.sh

eval:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="MODEL_MODE=stub" EVAL_ARGS="--phase 1"
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="MODEL_MODE=stub" EVAL_ARGS="--phase 1b"

eval-p2:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="MODEL_MODE=stub" EVAL_ARGS="--phase 2"

eval-p3:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="MODEL_MODE=stub" EVAL_ARGS="--phase 3"

eval-all:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="MODEL_MODE=stub"

eval-rubric:
	python3 scripts/eval_rubric.py --sample-rate 0.05

eval-live:
	$(MAKE) eval-run-isolated EVAL_RUNTIME_ENV="MODEL_MODE=live" EVAL_ARGS="--mode live"

eval-run-isolated:
	@mkdir -p $(EVAL_WORKSPACE)
	@chmod 777 $(EVAL_WORKSPACE)
	@set -eu; \
	restore_runtime() { \
	  rc=$$?; \
	  trap - EXIT; \
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
	env $(EVAL_RUNTIME_ENV) WORKSPACE_HOST_PATH=$(EVAL_WORKSPACE_HOST_PATH) \
	  python3 scripts/eval_run.py --workspace $(EVAL_WORKSPACE) $(EVAL_ARGS)

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

security-audit:
	bash scripts/security_audit.sh

contracts-test:
	pip install -q jsonschema pytest pyyaml && pytest packages/contracts/tests -q
	pip install -q packages/contracts/python && pytest packages/contracts/python/tests -q
	$(MAKE) retrieval-bench
	$(MAKE) api-test
	$(MAKE) runtime-test

up-queue:
	WORKER_MODE=outbox $(COMPOSE_QUEUE) --profile queue up -d --build

up-retrieval: ## 兼容入口（主 compose 已默认 Dockerfile.retrieval + embedding）
	INDEX_VIA_WORKER=true RETRIEVAL_MODE=hybrid $(COMPOSE_RETRIEVAL) --profile retrieval up -d --build

up-full: ## 全栈：redis/worker（embedding 已在默认 up 中）
	WORKER_MODE=outbox INDEX_VIA_WORKER=true RETRIEVAL_MODE=hybrid \
	  $(COMPOSE_QUEUE_RETRIEVAL) --profile queue --profile retrieval up -d --build

up-ha:
	$(COMPOSE_HA) up -d --build --scale runtime=0

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

retrieval-bench: ## 离线检索 A/B（docs/28 RE0/RE3 效果闸层 1）
	@cd services/runtime && \
	  if test -x .venv/bin/python; then PY=.venv/bin/python; else PY=python3; fi && \
	  $$PY ../../scripts/retrieval_bench.py --mode hybrid && \
	  $$PY ../../scripts/retrieval_bench.py --mode keyword

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
