COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env
COMPOSE_QUEUE := docker compose -f deploy/docker-compose.yml -f deploy/compose/queue.yml --env-file .env
COMPOSE_RETRIEVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/retrieval.yml --env-file .env
COMPOSE_QUEUE_RETRIEVAL := docker compose -f deploy/docker-compose.yml -f deploy/compose/queue.yml -f deploy/compose/retrieval.yml --env-file .env
COMPOSE_HA := docker compose -f deploy/docker-compose.yml -f deploy/compose/ha.yml --env-file .env

.PHONY: up down ps logs smoke build migrate up-queue up-retrieval eval-live eval-queue contracts-test up-ha eval-stall eval-ha eval-recorded eval-retrieval codegen load-test runtime-test security-audit

up:
	$(COMPOSE) up -d --build

up-queue:
	WORKER_MODE=outbox $(COMPOSE_QUEUE) --profile queue up -d --build

up-retrieval:
	INDEX_VIA_WORKER=true RETRIEVAL_MODE=hybrid $(COMPOSE_RETRIEVAL) --profile retrieval up -d --build

up-ha:
	$(COMPOSE_HA) up -d --build --scale runtime=0

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
