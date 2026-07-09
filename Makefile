COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env
COMPOSE_DEV := docker compose -f deploy/docker-compose.yml -f deploy/compose/dev.override.yml --env-file .env
COMPOSE_QUEUE := docker compose -f deploy/docker-compose.yml -f deploy/compose/queue.yml --env-file .env
COMPOSE_RETRIEVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/retrieval.yml --env-file .env
COMPOSE_QUEUE_RETRIEVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/queue.yml -f deploy/compose/retrieval.yml --env-file .env
COMPOSE_HA := docker compose -f deploy/docker-compose.yml -f deploy/compose/ha.yml --env-file .env
DEV_OVERRIDE := deploy/compose/dev.override.yml

.DEFAULT_GOAL := help

.PHONY: help start up down ps logs smoke build migrate \
	up-web up-api up-runtime restart-web restart-api restart-runtime \
	dev dev-init web-dev \
	up-queue up-retrieval up-ha \
	eval eval-p2 eval-all eval-live api-test runtime-test security-audit \
	contracts-test eval-stall eval-ha eval-recorded eval-retrieval eval-queue \
	load-test codegen alembic-upgrade test-rag

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
	@echo "  make up           重建并启动全部服务（首次 / Dockerfile 变更）"
	@echo "  make build        只构建镜像，不启动"
	@echo "  make down         停止"
	@echo "  make ps / logs    状态 / 日志"
	@echo ""
	@echo "其他"
	@echo "  make migrate      数据库迁移"
	@echo "  make smoke        冒烟测试"
	@echo "  make test-rag     RAG 检索效果对比（根目录一条命令）"
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
	$(COMPOSE) down

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
	python3 scripts/eval_run.py --phase 1
	python3 scripts/eval_run.py --phase 1b

eval-p2:
	python3 scripts/eval_run.py --phase 2

eval-all:
	python3 scripts/eval_run.py

eval-live:
	python3 scripts/eval_run.py --mode live

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
	pip install -q jsonschema pytest && pytest packages/contracts/tests -q
	pip install -q packages/contracts/python && pytest packages/contracts/python/tests -q
	$(MAKE) api-test
	$(MAKE) runtime-test

up-queue:
	WORKER_MODE=outbox $(COMPOSE_QUEUE) --profile queue up -d --build

up-retrieval:
	INDEX_VIA_WORKER=true RETRIEVAL_MODE=hybrid $(COMPOSE_RETRIEVAL) --profile retrieval up -d --build

up-ha:
	$(COMPOSE_HA) up -d --build --scale runtime=0

eval-stall:
	STALL_THRESHOLD_SECONDS=8 STALL_POLL_INTERVAL_SECONDS=2 STALL_AUTO_FAIL=true MODEL_TIMEOUT_SECONDS=120 \
	  $(COMPOSE) up -d --build --force-recreate runtime
	@sleep 5
	python3 scripts/eval_run.py --filter stall_watchdog --include-stall
	STALL_THRESHOLD_SECONDS=120 STALL_POLL_INTERVAL_SECONDS=30 STALL_AUTO_FAIL=false MODEL_TIMEOUT_SECONDS=3 \
	  $(COMPOSE) up -d --build --force-recreate runtime

eval-ha:
	$(COMPOSE_HA) up -d --build --scale runtime=0
	@sleep 10
	@python3 scripts/eval_run.py --filter ha_runner --include-ha; \
	rc=$$?; \
	$(COMPOSE) up -d --build --remove-orphans; \
	exit $$rc

eval-recorded:
	MODEL_MODE=recorded $(COMPOSE) up -d --build --force-recreate runtime
	@sleep 8
	python3 scripts/eval_run.py --filter recorded --include-recorded --mode recorded
	MODEL_MODE=stub $(COMPOSE) up -d --build --force-recreate runtime

eval-retrieval:
	$(COMPOSE_RETRIEVAL) --profile retrieval up -d --build
	@sleep 30
	pip install -q websockets 2>/dev/null || true
	python3 scripts/eval_run.py --filter writing.07
	$(COMPOSE) up -d --build --remove-orphans

eval-queue:
	WORKER_MODE=outbox INDEX_VIA_WORKER=true \
	  $(COMPOSE_QUEUE_RETRIEVAL) --profile queue --profile retrieval up -d --build
	@sleep 30
	python3 scripts/eval_run.py --filter outbox_worker --include-queue
	$(COMPOSE) up -d --build --remove-orphans

load-test:
	python3 scripts/load_test.py

codegen:
	bash scripts/codegen.sh

migrate:
	$(COMPOSE) exec api python -m app.db.migrate

alembic-upgrade:
	cd services/api && alembic -c alembic.ini upgrade head
