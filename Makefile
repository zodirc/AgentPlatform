# embedding.auto.env from `make resolve-embedding` (GPU → bge-m3 + CUDA, else gte-small).
# defaults.env is the committed fallback; auto.env overrides when present.
# gpu.auto.yml is written by the same script (gpus: all when NVIDIA usable).
#
# IMPORTANT: Docker Compose interpolates ${VAR} from the project `.env` file and
# may ignore later --env-file for build args. Export auto.env into the shell so
# it wins over a stale EMBEDDING_MODEL=MiniLM in `.env`.
COMPOSE_ENV := --env-file .env --env-file deploy/embedding.defaults.env --env-file deploy/embedding.auto.env --env-file deploy/base-images.env
# Deferred so resolve-embedding can create gpu.auto.yml before compose runs.
COMPOSE_GPU = $(wildcard deploy/compose/gpu.auto.yml)
COMPOSE_GPU_FLAG = $(if $(COMPOSE_GPU),-f $(COMPOSE_GPU),)
# Sticky docker.sock on api+runtime (SWE harness + solve-side run_tests).
# Written by `make up-ops-eval` / 部署看板「启用 Ops Docker」. Without this,
# `make up-api` / up-runtime / 部署看板会卸掉 sock。Delete the file or set 0 to disable.
-include deploy/ops-eval.auto.env
OPS_EVAL_DOCKER_SOCK ?= 0
COMPOSE_OPS_FLAG = $(if $(filter 1 true TRUE yes YES,$(OPS_EVAL_DOCKER_SOCK)),-f deploy/compose/ops-eval.yml,)
# Source embedding + pinned base images into the shell (overrides .env for ${EMBEDDING_MODEL} etc.).
COMPOSE_EXPORT = set -a && \
	[ -f deploy/embedding.defaults.env ] && . ./deploy/embedding.defaults.env; \
	[ -f deploy/embedding.auto.env ] && . ./deploy/embedding.auto.env; \
	[ -f deploy/base-images.env ] && . ./deploy/base-images.env; \
	[ -f deploy/ops-eval.auto.env ] && . ./deploy/ops-eval.auto.env; \
	set +a
COMPOSE = $(COMPOSE_EXPORT) && docker compose -f deploy/docker-compose.yml $(COMPOSE_GPU_FLAG) $(COMPOSE_OPS_FLAG) $(COMPOSE_ENV)
COMPOSE_DEV = $(COMPOSE_EXPORT) && docker compose -f deploy/docker-compose.yml $(COMPOSE_GPU_FLAG) $(COMPOSE_OPS_FLAG) -f deploy/compose/dev.override.yml $(COMPOSE_ENV)
COMPOSE_QUEUE = $(COMPOSE_EXPORT) && docker compose -f deploy/docker-compose.yml $(COMPOSE_GPU_FLAG) $(COMPOSE_OPS_FLAG) -f deploy/compose/queue.yml $(COMPOSE_ENV)
COMPOSE_RETRIEVAL = $(COMPOSE_EXPORT) && docker compose -f deploy/docker-compose.yml $(COMPOSE_GPU_FLAG) $(COMPOSE_OPS_FLAG) -f deploy/compose/retrieval.yml $(COMPOSE_ENV)
COMPOSE_QUEUE_RETRIEVAL = $(COMPOSE_EXPORT) && docker compose -f deploy/docker-compose.yml $(COMPOSE_GPU_FLAG) $(COMPOSE_OPS_FLAG) -f deploy/compose/queue.yml -f deploy/compose/retrieval.yml $(COMPOSE_ENV)
COMPOSE_HA = $(COMPOSE_EXPORT) && docker compose -f deploy/docker-compose.yml $(COMPOSE_GPU_FLAG) $(COMPOSE_OPS_FLAG) -f deploy/compose/ha.yml $(COMPOSE_ENV)
COMPOSE_OPS_EVAL = $(COMPOSE_EXPORT) && docker compose -f deploy/docker-compose.yml $(COMPOSE_GPU_FLAG) -f deploy/compose/ops-eval.yml $(COMPOSE_ENV)
DEV_OVERRIDE := deploy/compose/dev.override.yml
EVAL_WORKSPACE := .eval-workspace
EVAL_WORKSPACE_HOST_PATH := ../.eval-workspace
# Daily make up/start enable Ops bench via profile. Not exported — CI/smoke/eval
# must not inherit it (see scripts/proof_compose_env.sh / smoke_test.sh).
# Constrained hosts: `COMPOSE_PROFILES= make up` skips bench + bench-postgres.
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
# make docker-prune: default dangling images only; set BUILD_CACHE_PRUNE=1 for builder prune -af.
BUILD_CACHE_PRUNE ?= 0
# WSL/Linux: strip broken Windows credsStore (desktop.exe) before compose build.
# Docker Desktop often rewrites ~/.docker/config.json; make up/build re-fixes.
# Set DOCKER_FIX_WSL_CREDS=0 to skip (docs/core/03-docker-runtime.md).
DOCKER_FIX_WSL_CREDS ?= 1
# docs/38: set *_REBUILD_DEPS=1 to force --no-cache (rebuild pip/ST deps layers).
API_REBUILD_DEPS ?= 0
RUNTIME_REBUILD_DEPS ?= 0
WEB_REBUILD_DEPS ?= 0
BENCH_REBUILD_DEPS ?= 0
# make up/start 后台拉起发布台 :9090；RELEASE_CONSOLE=0 关闭
RELEASE_CONSOLE ?= 1

.DEFAULT_GOAL := help

.PHONY: help start up down ps logs smoke build migrate gate ci-proof \
	pull-dispatch-maturity \
	ensure-ops-secret ensure-docker-creds fix-workspace-sources resolve-embedding \
	up-web up-api up-runtime up-ast-indexer up-bench start-bench up-ops-eval ops-eval-off ops-swe-eval-ready deps-anchor restart-web restart-api restart-runtime \
	dev dev-init web-dev docker-prune docker-prune-safe \
	up-queue up-retrieval up-full up-ha \
	eval eval-p2 eval-all eval-live api-test runtime-test security-audit \
	contracts-test eval-stall eval-ha eval-recorded eval-retrieval eval-queue \
	eval-plan-suggest eval-plan-suggest-tune ux-signals \
	eval-run-isolated load-test codegen alembic-upgrade test-rag retrieval-bench turn-effect-bench eval-writing-rag \
	sync-sources seed-sources sync-ops-indexes sync-ops-cmteb ops-cmteb-prepare sync intel-corpus-fetch retrieval-bench-prod loc \
	micro-p1 \
	micro-l1-prepare \
	preflight preflight-ci preflight-unit hooks-install ensure-git-hooks backup \
	official-bench-paths official-bench-deps official-bench-pull official-bench-pull-cmteb official-bench-retrieval \
	official-bench-context official-bench-coding-pull official-bench-coding-pull-images \
	official-bench-coding-infer \
	official-bench-coding-eval official-bench-all official-bench-publish \
	official-bench-update-baseline official-bench-show-baseline \
	official-bench-compare official-bench-live \
	official-bench-retrieval-agent official-bench-retrieval-zh-agent official-bench-context-agent \
	official-bench-coding-infer-agent c3-retrieval-grid \
	swebench-structural-dual-track swebench-structural-metrics \
	release release-status release-detect release-console release-console-stop release-after-up up-all release-plan

help: ## 显示常用命令
	@echo "日常开发（推荐）"
	@echo "  make start        启动栈，不重建（主机重启 / 容器停了优先用这个）"
	@echo "  make up           只重建脏模块；依赖层应命中 :deps 缓存（只改 app 不重装 pip/pnpm）"
	@echo "  make up-web       只重建 web（WEB_REBUILD_DEPS=1 强制 pnpm 重装）"
	@echo "  make up-api       只重建 api（API_REBUILD_DEPS=1 强制 pip 重装）"
	@echo "  make up-runtime   只重建 runtime（RUNTIME_REBUILD_DEPS=1 含 ST 烘焙）"
	@echo "  make deps-anchor  仅打 api/runtime/web/bench:deps（防 BuildKit GC 掉 pip/pnpm 层）"
	@echo "  make docker-prune-safe  按 deploy/docker-keep.list 清理（保留产品/deps/SWE/构建基座；默认不清 BuildKit）"
	@echo "  make start-bench  仅启动 Ops Bench（不 rebuild；容器被杀后优先用这个）"
	@echo "  make up-bench     重建并启动 Ops Bench worker（真向量评测，与 agent 解耦）"
	@echo "  make dev          开发模式：挂载 Python 源码 + 热重载（api/runtime）"
	@echo "  make web-dev      前端 Vite 热更新 http://localhost:5173"
	@echo "  make eval-plan-suggest      Plan 建议金标基线（不改权重）"
	@echo "  make eval-plan-suggest-tune 搜索权重提案（只写 reports）"
	@echo "  make ensure-ops-secret  若空则生成 OPS_TEST_SECRET 并打印评测台 URL"
	@echo "  make ensure-docker-creds  WSL：去掉坏掉的 desktop.exe credsStore（默认开）"
	@echo "  make up-ops-eval     挂 docker.sock 到 api+runtime（粘性）"
	@echo "  make ops-swe-eval-ready  挂 sock + 预拉/冒烟（部署看板「SWE 评测环境」一键）"
	@echo "  make ops-eval-off    取消粘性挂载（下次 up-api/up-runtime 不再带 sock）"
	@echo "  make fix-workspace-sources  修复 sources/ 权限（资料库可写；seed 只读）"
	@echo "  # 依赖与代码分缓存：改 app/** 不必 *_REBUILD_DEPS；改 pyproject/lock 随模块重建；bump base-images.env 由 paths.env 脏检测触发 make up"
	@echo "  # 基础镜像 digests：deploy/base-images.env（浮动 tag 不会再冲掉 deps）"
	@echo ""
	@echo "完整部署"
	@echo "  make up           先拉起已有镜像，再只重建真正脏的模块 + 发布台 :9090"
	@echo "  make up-all       强制全量 compose --build（不分模块）"
	@echo "  make sync-sources 增量索引 seed/普通 work（本终端 [sync] 进度；不含 ops-l1 BEIR）"
	@echo "  make sync-ops-indexes  换模后重嵌 Ops BEIR（FiQA 等；耗时长，非 make up 默认）"
	@echo "  make ops-cmteb-prepare 从已拉 C-MTEB 建 ops-l1/cmteb-index Works（不嵌）"
	@echo "  make sync-ops-cmteb    换模后重嵌 Ops C-MTEB（同模；仅 retrieval_ops_zh 分图）"
	@echo "  make sync         = sync-sources + sync-ops-indexes（换模后一键；可见进度）"
	@echo "  make resolve-embedding  GPU→bge-m3@1024（中英共用）+CUDA / 否则 gte-small@384（up/start 自动跑）"
	@echo "  make up-ha        双 runtime HA（多用户同时跑 Turn；docs/27 MT7）"
	@echo "  make up-full      全栈：queue worker + retrieval overlay"
	@echo "  make build        只构建镜像，不启动（结束后自动清理悬空镜像）"
	@echo "  make docker-prune 清理悬空镜像（BUILD_CACHE_PRUNE=1 才清 BuildKit 依赖缓存）"
	@echo "  make down         停止"
	@echo "  make ps / logs    状态 / 日志"
	@echo ""
	@echo "其他"
	@echo "  make migrate      数据库迁移"
	@echo "  make smoke        冒烟测试"
	@echo "  make pull-dispatch-maturity  pull 分发成熟度冒烟（指标/表/保留）"
	@echo "  make gate         Proof 一键门禁（smoke→eval-all→runtime-test；docs/28）"
	@echo "  make ux-signals   体验信号日聚合/告警（docs/28 PX1；环外，不进 Turn）"
	@echo "  make test-rag     RAG 检索效果对比（根目录一条命令）"
	@echo "  make retrieval-bench 离线检索 A/B（docs/15 契约近似；hash）"
	@echo "  make retrieval-bench-prod 真相档难 qrels（ST+pgvector；docs/15 IX4）"
	@echo "  make micro-p1     P1 词面微基准（无 sync/无重嵌；SciFact 10q；ts_rank vs Okapi）"
	@echo "  make micro-l1-prepare  SciFact 中库微图 gold+干扰（与主图分离）+ gte；Ops「SciFact 微 L1」"
	@echo "  make official-bench-pull       拉取 BEIR+LongBench+SWE+C-MTEB 小量（需网络）"
	@echo "  make official-bench-pull-cmteb  只拉 C-MTEB 三库中文检索（Covid/Medical/Ecom）"
	@echo "  make official-bench-live     live 实测官方小量（禁 dry/skip；需 BENCH_MODEL_*）"
	@echo "  make official-bench-compare  latest vs 仓库 SCORECARD/baseline Δ 表"
	@echo "  make official-bench-update-baseline  认可后写入 baseline+SCORECARD"
	@echo "  make seed-sources    同 sync-sources（常驻库不拷贝，只重建索引）"
	@echo "  make sync-ops-indexes  Ops BEIR 按 work stamp 重嵌（换模后；本终端 [sync] 进度）"
	@echo "  make sync            sync-sources + sync-ops-indexes（一键；可见进度；默认接管旧 sync）"
	@echo "  make intel-corpus-fetch  拉取/转换 intel vendor 语料（gitignore；docs seed/intel）"
	@echo "  make runtime-test 运行时测试"
	@echo "  make preflight       推送前 unit 门禁（pre-push 默认；无长连接风险）"
	@echo "  make preflight-ci    全量本地 CI（ci_proof+web；久；推送前手动跑）"
	@echo "  make hooks-install 启用 .githooks（make up/start 也会自动装）"
	@echo "  make loc          统计源码行数（不含依赖/文档/workspace）"
	@echo ""
	@echo "发布台（同仓；make up/start 默认拉起 :9090）"
	@echo "  make release-console  前台跑发布台（须在本机 WSL 终端；勿用 Agent 沙箱代起 :9090）"
	@echo "  make release-console-stop  停掉后台发布台"
	@echo "  make release-status / release-detect / release"
	@echo "  RELEASE_CONSOLE=0 make up   起栈但不启发布台"

# If OPS_TEST_SECRET is empty/missing in .env, generate once and print Ops URL (docs/29).
# Never overwrites an existing secret.
ensure-ops-secret: ## 确保 .env 有 OPS_TEST_SECRET，并打印 /ops/<secret>/test
	@bash scripts/ensure_ops_test_secret.sh

# Release console: scripts/release + services/release-console (port 9090).
# Packaged modules replace the serving stack on :80 — not a second product stack.
release-status: ## 刷新发布状态 JSON
	@bash scripts/release/release.sh status

release-plan: ## 健康看板数据（代码/向量模型/索引要不要动）
	@python3 scripts/release/plan.py

release-detect: ## 检测相对 last_release_sha 的脏模块
	@bash scripts/release/release.sh detect

release: ## 分模块发布（必须 RELEASE_MODULES=api,web 或先 detect）
	@if [ -z "$(RELEASE_MODULES)" ]; then \
	  echo "用法: make release RELEASE_MODULES=api,runtime,web  （必须分模块）"; \
	  echo "先看脏模块: make release-detect"; \
	  exit 2; \
	fi
	@bash scripts/release/release.sh run --modules=$(RELEASE_MODULES)

release-console: ## 发布台 Web 前台跑（需 .env 中 RELEASE_CONSOLE_SECRET）
	@PYTHONUNBUFFERED=1 python3 services/release-console/server.py

release-console-stop: ## 停止 make up 拉起的后台发布台
	@bash scripts/release/stop_console.sh

# After modular release: ensure console only (mark done per-module inside release.sh).
release-after-up: ## 确保发布台在跑（兼容旧目标名）
	@RELEASE_CONSOLE=$(RELEASE_CONSOLE) bash scripts/release/ensure_console.sh

ensure-docker-creds: ## WSL：去掉 ~/.docker 里坏掉的 desktop.exe credsStore（可关 DOCKER_FIX_WSL_CREDS=0）
	@DOCKER_FIX_WSL_CREDS=$(DOCKER_FIX_WSL_CREDS) bash scripts/ensure_docker_creds.sh

ensure-git-hooks: ## 本仓库 core.hooksPath=.githooks（make up/start 默认）
	@bash scripts/install-git-hooks.sh

resolve-embedding: ## 按 GPU 选型 gte-small|gte-large + CUDA torch overlay → deploy/embedding.auto.env
	@bash scripts/resolve_embedding_profile.sh
	@# Ensure compose always has an auto.env (defaults copy if resolve skipped elsewhere)
	@test -f deploy/embedding.auto.env || cp deploy/embedding.defaults.env deploy/embedding.auto.env
	@test -f deploy/compose/gpu.auto.yml || printf '%s\n' '# no gpu' 'services: {}' > deploy/compose/gpu.auto.yml

# Seed RO mount creates sources/ as root; runtime app (uid 1000) must own it to upload.
fix-workspace-sources: ## 修复 /workspace/sources 写权限（不改 seed）
	@bash scripts/ensure_workspace_sources_writable.sh

start: resolve-embedding ensure-ops-secret ensure-docker-creds ensure-git-hooks ## 启动栈（不 rebuild，最快）
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE) up -d
	@$(MAKE) --no-print-directory fix-workspace-sources
	@RELEASE_CONSOLE=$(RELEASE_CONSOLE) bash scripts/release/ensure_console.sh

# Safe: only removes untagged (<none>) images left by retag-after-build.
define docker_auto_prune
	@if [ "$(DOCKER_AUTO_PRUNE)" = "1" ]; then \
	  echo "==> auto-prune dangling images"; \
	  docker image prune -f >/dev/null; \
	fi
endef

up: resolve-embedding ensure-ops-secret ensure-docker-creds ensure-git-hooks ## 分模块重建脏服务 + 发布台 :9090
	@bash scripts/release/release.sh up

up-all: resolve-embedding ensure-ops-secret ensure-docker-creds ensure-git-hooks ## 强制全量 compose --build（不分模块）
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory fix-workspace-sources
	$(docker_auto_prune)
	@bash scripts/release/release.sh mark --modules=api,runtime,web,gateway >/dev/null
	@RELEASE_CONSOLE=$(RELEASE_CONSOLE) bash scripts/release/ensure_console.sh

# Secret is consumed by api only. up-web may generate it for the first time — recreate api then.
# --no-deps: do not rebuild/restart depends_on (api→runtime); otherwise up-api pays runtime ST/pip.
# SKIP_RELEASE_HOOK=1：被 release.sh 调用时跳过 mark/console（由上层统一做）。
# Build order: warm :deps first (cache_from), then thin app — code changes must not re-pip/pnpm.
up-web: ensure-docker-creds ## 只重建 web（WEB_REBUILD_DEPS=1 → --no-cache）
	@status=$$(mktemp); \
	OPS_SECRET_STATUS_FILE=$$status bash scripts/ensure_ops_test_secret.sh; \
	gen=$$(grep '^generated=' $$status | cut -d= -f2); rm -f $$status; \
	if [ "$$gen" = "1" ]; then \
	  echo "==> new OPS_TEST_SECRET → recreating api to load env"; \
	  $(COMPOSE) up -d --no-deps --force-recreate api; \
	fi
	@set -e; \
	if [ "$(WEB_REBUILD_DEPS)" = "1" ]; then \
	  echo "==> WEB_REBUILD_DEPS=1 → docker compose build --no-cache web (+deps anchor)"; \
	  $(COMPOSE) build --no-cache web; \
	  COMPOSE_PROFILES=deps-anchor $(COMPOSE) build --no-cache web-deps \
	    || echo "==> warn: web-deps anchor failed (mirror?); web image still built"; \
	else \
	  echo "==> web: warm deps anchor then app (pnpm only if lock/deps inputs changed)"; \
	  COMPOSE_PROFILES=deps-anchor $(COMPOSE) build web-deps \
	    || echo "==> warn: web-deps anchor failed (mirror?); continuing with app build"; \
	  $(COMPOSE) build web; \
	fi; \
	$(COMPOSE) up -d --no-deps web
	$(docker_auto_prune)
	@if [ "$(SKIP_RELEASE_HOOK)" != "1" ]; then \
	  bash scripts/release/release.sh mark --modules=web >/dev/null; \
	  RELEASE_CONSOLE=$(RELEASE_CONSOLE) bash scripts/release/ensure_console.sh; \
	fi

up-api: ensure-ops-secret ensure-docker-creds ## 只重建 api（API_REBUILD_DEPS=1 → --no-cache）
	@set -e; \
	if [ "$(API_REBUILD_DEPS)" = "1" ]; then \
	  echo "==> API_REBUILD_DEPS=1 → docker compose build --no-cache api (+deps anchor)"; \
	  $(COMPOSE) build --no-cache api; \
	  COMPOSE_PROFILES=deps-anchor $(COMPOSE) build --no-cache api-deps; \
	else \
	  echo "==> api: warm deps anchor then app (pip only if pyproject/contracts changed)"; \
	  COMPOSE_PROFILES=deps-anchor $(COMPOSE) build api-deps; \
	  $(COMPOSE) build api; \
	fi; \
	$(COMPOSE) up -d --no-deps api
	$(docker_auto_prune)
	@if [ "$(SKIP_RELEASE_HOOK)" != "1" ]; then \
	  bash scripts/release/release.sh mark --modules=api >/dev/null; \
	  RELEASE_CONSOLE=$(RELEASE_CONSOLE) bash scripts/release/ensure_console.sh; \
	fi

# Opt-in: mount docker.sock so Ops SWE harness (api) + solve run_tests (runtime) work.
# Persists via deploy/ops-eval.auto.env so 部署看板 / make up-api|up-runtime keep the mount.
up-ops-eval: ensure-ops-secret ensure-docker-creds ## api+runtime 挂 docker.sock（粘性；部署看板一键）
	@printf '%s\n' \
	  '# Auto-generated by make up-ops-eval — keep docker.sock on api+runtime across up-* / 部署看板.' \
	  '# Run `make ops-eval-off` or set OPS_EVAL_DOCKER_SOCK=0 to disable.' \
	  'OPS_EVAL_DOCKER_SOCK=1' \
	  > deploy/ops-eval.auto.env
	$(COMPOSE_OPS_EVAL) up -d --no-deps --force-recreate api runtime
	@echo "==> Ops docker.sock 已挂到 api+runtime，并写入 deploy/ops-eval.auto.env（粘性）"
	@echo "    部署看板 / make up-api / make up-runtime / make up 会继续带上 sock；取消：make ops-eval-off"

ops-eval-off: ## 取消 api+runtime docker.sock 粘性（下次 up-* 不再挂载）
	@rm -f deploy/ops-eval.auto.env
	@echo "==> 已删除 deploy/ops-eval.auto.env"
	@echo "    下次 make up-api / up-runtime / 部署看板 将不再挂 docker.sock"
	@$(COMPOSE) up -d --no-deps --force-recreate api runtime
	@echo "==> api+runtime 已按无 sock 配置 recreate"

# Plain make up / up-api omit the socket unless OPS_EVAL_DOCKER_SOCK=1 (from up-ops-eval).

up-runtime: resolve-embedding ensure-docker-creds ## 只重建 runtime（RUNTIME_REBUILD_DEPS=1 → --no-cache，含 ST）
	@set -e; \
	if [ "$(RUNTIME_REBUILD_DEPS)" = "1" ]; then \
	  echo "==> RUNTIME_REBUILD_DEPS=1 → docker compose build --no-cache runtime (+deps anchor)"; \
	  $(COMPOSE) build --no-cache runtime; \
	  COMPOSE_PROFILES=deps-anchor $(COMPOSE) build --no-cache runtime-deps; \
	else \
	  echo "==> runtime: warm deps anchor then app (torch/ST only if deps inputs changed)"; \
	  COMPOSE_PROFILES=deps-anchor $(COMPOSE) build runtime-deps; \
	  $(COMPOSE) build runtime; \
	fi; \
	$(COMPOSE) up -d --no-deps runtime
	@$(COMPOSE) up -d --no-deps --force-recreate ast-indexer || true
	$(docker_auto_prune)
	@if [ "$(SKIP_RELEASE_HOOK)" != "1" ]; then \
	  bash scripts/release/release.sh mark --modules=runtime >/dev/null; \
	  RELEASE_CONSOLE=$(RELEASE_CONSOLE) bash scripts/release/ensure_console.sh; \
	fi

up-ast-indexer: ensure-docker-creds ## 只重建/拉起 agent-ast-indexer（A6）
	@set -e; \
	$(COMPOSE) build runtime; \
	$(COMPOSE) up -d --no-deps --force-recreate ast-indexer
	$(docker_auto_prune)

start-bench: resolve-embedding ensure-ops-secret ## 仅启动 Ops Bench（不 rebuild）
	@set -e; \
	echo "==> start-bench（不 build；镜像已存在时秒级拉起）"; \
	COMPOSE_PROFILES=bench $(COMPOSE) up -d bench-postgres; \
	COMPOSE_PROFILES=bench $(COMPOSE) up -d --no-deps bench

up-bench: resolve-embedding ensure-ops-secret ensure-docker-creds ## 重建并启动 Ops Bench worker（真向量评测，与 agent 解耦）
	@set -e; \
	if [ "$(BENCH_REBUILD_DEPS)" = "1" ]; then \
	  echo "==> BENCH_REBUILD_DEPS=1 → docker compose build --no-cache bench (+deps anchor)"; \
	  COMPOSE_PROFILES=bench $(COMPOSE) build --no-cache bench; \
	  COMPOSE_PROFILES=deps-anchor $(COMPOSE) build --no-cache bench-deps; \
	else \
	  echo "==> bench: warm deps anchor then app"; \
	  COMPOSE_PROFILES=deps-anchor $(COMPOSE) build bench-deps; \
	  COMPOSE_PROFILES=bench $(COMPOSE) build bench; \
	fi; \
	echo "==> ensuring dedicated bench-postgres (isolated from agent-postgres)"; \
	COMPOSE_PROFILES=bench $(COMPOSE) up -d bench-postgres; \
	COMPOSE_PROFILES=bench $(COMPOSE) up -d --no-deps bench
	$(docker_auto_prune)

# Tag all deps stages so BuildKit GC is less likely to drop pip/pnpm layers.
deps-anchor: resolve-embedding ensure-docker-creds ## 仅打 api/runtime/web/bench:deps 锚点镜像
	@echo "==> building deps-anchor images (api/runtime/web/bench)"
	COMPOSE_PROFILES=deps-anchor $(COMPOSE) build api-deps runtime-deps web-deps bench-deps
	@docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' \
	  | grep -E 'agent-platform-(api|runtime|web|bench):(deps|latest|default)' || true

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
	@bash scripts/release/stop_console.sh || true

ps:
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE) ps

logs:
	COMPOSE_PROFILES=$(COMPOSE_PROFILES) $(COMPOSE) logs -f api runtime

build: ensure-docker-creds
	$(COMPOSE) build
	$(docker_auto_prune)

docker-prune-safe: ## 按 deploy/docker-keep.list 清理（默认保留 BuildKit；BUILD_CACHE_PRUNE=1 才清）
	@DRY_RUN=$(DRY_RUN) BUILD_CACHE_PRUNE=$(BUILD_CACHE_PRUNE) bash scripts/docker_prune_safe.sh

docker-prune: docker-prune-safe ## 同 docker-prune-safe（旧名兼容）

backup: ## 备份 Postgres（pg_dump）+ agent_data 卷（保留最近 7 份）
	bash deploy/backup.sh

smoke:
	bash scripts/smoke_test.sh

pull-dispatch-maturity: ## pull 分发成熟度冒烟（schema/LISTEN/retention/metrics；无 kill）
	bash scripts/ops/pull_dispatch_maturity.sh

constitution-check: ## 三大短板门禁：LOC 棘轮 + scenario 泄漏扫描（S0/C0）
	python3 scripts/check_file_size.py
	python3 scripts/check_scenario_leak.py

gate: ## Docker 门禁：constitution → smoke → eval-all → runtime-test（完整 CI 请用 make ci-proof）
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

# RET-11(b): offline doc2query → source_files/chunks.bm25_extra (BM25/FTS only).
# Needs BENCH_MODEL_* (or MODEL_*) live key. Default: FiQA under any work.
# Example: make retrieval-doc2query LIMIT=20 WORKERS=4
# Prune only: make retrieval-doc2query PRUNE_ONLY=1  (no LLM key needed)
# Full FiQA (~57k): make retrieval-doc2query WORKERS=512
retrieval-doc2query: ## RET-11(b) 离线伪查询扩 BM25（默认 FiQA；不重嵌）
	@if [ "$(PRUNE_ONLY)" = "1" ]; then \
	  echo "==> retrieval-doc2query --prune-only path_like=$${PATH_LIKE:-%/sources/beir/fiqa/%}"; \
	  $(COMPOSE) exec -T -e PYTHONUNBUFFERED=1 runtime python -m app.retrieval.doc2query \
	    --path-like "$${PATH_LIKE:-%/sources/beir/fiqa/%}" --prune-only; \
	else \
	  test -n "$${BENCH_MODEL_API_KEY:-$${MODEL_API_KEY:-}}" || (echo "ERROR: set BENCH_MODEL_API_KEY"; exit 1); \
	  echo "==> retrieval-doc2query path_like=$${PATH_LIKE:-%/sources/beir/fiqa/%} limit=$${LIMIT:-0} workers=$${WORKERS:-8}"; \
	  $(COMPOSE) exec -T \
	    -e PYTHONUNBUFFERED=1 \
	    -e BENCH_MODEL_API_KEY \
	    -e BENCH_MODEL_BASE_URL \
	    -e BENCH_MODEL_NAME \
	    -e MODEL_API_KEY \
	    -e OPENAI_BASE_URL \
	    -e MODEL_NAME \
	    runtime python -m app.retrieval.doc2query \
	      --path-like "$${PATH_LIKE:-%/sources/beir/fiqa/%}" \
	      $(if $(LIMIT),--limit $(LIMIT),) \
	      --workers $${WORKERS:-8} \
	      $(if $(FORCE),--force,) \
	      $(if $(DRY_RUN),--dry-run,); \
	fi

sync-sources: ## Turn 外增量索引（本终端逐行进度条；docs/15）
	@echo "==> sync-sources: live progress (embedder cold-start may take 1–3 min)"
	@$(COMPOSE) cp services/runtime/app/retrieval/sync_progress.py runtime:/app/app/retrieval/sync_progress.py >/dev/null 2>&1 || true
	@$(COMPOSE) cp services/runtime/app/retrieval/sync_cli.py runtime:/app/app/retrieval/sync_cli.py >/dev/null 2>&1 || true
	$(COMPOSE) exec -T -e PYTHONUNBUFFERED=1 runtime python -m app.retrieval.sync_cli --mode sources --reason make

seed-sources: ## 同 sync-sources：对挂载的常驻 seed 重新建索引（不拷贝文件）
	@$(MAKE) sync-sources

sync-ops-indexes: ## Ops BEIR work 按 scope stamp 重嵌（FiQA 等；跳过 seed；耗时长）
	@echo "==> sync-ops-indexes: work-scoped BEIR reindex (FiQA-scale can take 15–30+ min)"
	@echo "    Live progress on this terminal. Not part of make up."
	@$(COMPOSE) cp services/runtime/app/retrieval/sync_progress.py runtime:/app/app/retrieval/sync_progress.py >/dev/null 2>&1 || true
	@$(COMPOSE) cp services/runtime/app/retrieval/sync_cli.py runtime:/app/app/retrieval/sync_cli.py >/dev/null 2>&1 || true
	@$(COMPOSE) cp services/runtime/app/retrieval/index_scheduler.py runtime:/app/app/retrieval/index_scheduler.py >/dev/null 2>&1 || true
	$(COMPOSE) exec -T -e PYTHONUNBUFFERED=1 runtime python -m app.retrieval.sync_cli --mode ops-beir --reason make-ops-beir

ops-cmteb-prepare: ## 从挂载 C-MTEB 建 cmteb-index Works+语料 txt（不嵌；需 api）
	@test -f .env || (echo "missing .env"; exit 1)
	@test -f eval/official/.local-data/cmteb/CovidRetrieval/corpus.jsonl || \
	  (echo "missing C-MTEB slice; run: make official-bench-pull-cmteb"; exit 1)
	@echo "==> ops-cmteb-prepare: materialize ops-l1/cmteb-index (Covid/Medical/Ecom)"
	@$(COMPOSE) cp services/api/app/services/ops/official_agent_path.py \
	  api:/app/app/services/ops/official_agent_path.py >/dev/null 2>&1 || true
	@$(COMPOSE) cp services/api/app/services/ops/l1 \
	  api:/app/app/services/ops/l1 >/dev/null 2>&1 || true
	$(COMPOSE) exec -T -e PYTHONUNBUFFERED=1 api bash -c '\
	  export PYTHONPATH=/app:/repo/scripts; \
	  python /repo/scripts/official_bench/cmteb_index_prepare.py'

sync-ops-cmteb: ## Ops C-MTEB 重嵌（同模 bge-m3；仅 cmteb-index → retrieval_ops_zh 分图）
	@echo "==> sync-ops-cmteb: C-MTEB reindex (same embedder; schema retrieval_ops_zh)"
	@echo "    Live progress on this terminal. Requires GPU bge-m3 after resolve-embedding."
	@echo "    If no works yet: make ops-cmteb-prepare first (or ensure_ops_cmteb.sh)."
	@$(COMPOSE) cp services/runtime/app/retrieval/sync_progress.py runtime:/app/app/retrieval/sync_progress.py >/dev/null 2>&1 || true
	@$(COMPOSE) cp services/runtime/app/retrieval/sync_cli.py runtime:/app/app/retrieval/sync_cli.py >/dev/null 2>&1 || true
	@$(COMPOSE) cp services/runtime/app/retrieval/index_scheduler.py runtime:/app/app/retrieval/index_scheduler.py >/dev/null 2>&1 || true
	@$(COMPOSE) cp services/runtime/app/retrieval/ops_plane.py runtime:/app/app/retrieval/ops_plane.py >/dev/null 2>&1 || true
	$(COMPOSE) exec -T -e PYTHONUNBUFFERED=1 runtime python -m app.retrieval.sync_cli --mode ops-cmteb --reason make-ops-cmteb

sync: ## 一键：seed/普通 work + Ops BEIR（≡ sync-sources && sync-ops-indexes）
	@echo "==> make sync: (1/2) sync-sources"
	@$(MAKE) sync-sources
	@echo "==> make sync: (2/2) sync-ops-indexes"
	@$(MAKE) sync-ops-indexes
	@echo "==> make sync: done (C-MTEB: make ops-cmteb-prepare && make sync-ops-cmteb)"

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
# Dedicated uv/venv at eval/official/.venv — root .venv is a symlink to runtime (uv-locked).
OFFICIAL_BENCH_VENV ?= $(CURDIR)/eval/official/.venv
OFFICIAL_BENCH_PY ?= $(OFFICIAL_BENCH_VENV)/bin/python
CONTEXT_DRY ?= 0
OFFICIAL_SWE_SKIP_API ?= 0
OFFICIAL_CONTEXT_LIMIT ?= 0
OFFICIAL_SWE_TIER ?= n25
OFFICIAL_SWE_N ?=
OFFICIAL_SWE_HARNESS ?= 0
QUERY_LIMIT ?= 0

official-bench-deps: ## 安装官方评测本地依赖（datasets 等 → eval/official/.venv）
	@echo "==> official-bench-deps → $(OFFICIAL_BENCH_VENV)"
	@PIP_INDEX_URL="$${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"; \
	export PIP_INDEX_URL; \
	if command -v uv >/dev/null 2>&1; then \
	  test -x "$(OFFICIAL_BENCH_VENV)/bin/python" || uv venv "$(OFFICIAL_BENCH_VENV)"; \
	  "$(OFFICIAL_BENCH_VENV)/bin/python" -c 'import datasets, huggingface_hub, yaml' 2>/dev/null || \
	    uv pip install -p "$(OFFICIAL_BENCH_VENV)/bin/python" \
	      --index-url "$$PIP_INDEX_URL" \
	      -r eval/official/requirements.txt; \
	else \
	  test -x "$(OFFICIAL_BENCH_VENV)/bin/python" || python3 -m venv "$(OFFICIAL_BENCH_VENV)"; \
	  "$(OFFICIAL_BENCH_VENV)/bin/python" -c 'import datasets, huggingface_hub, yaml' 2>/dev/null || \
	    "$(OFFICIAL_BENCH_VENV)/bin/python" -m pip install -q \
	      -i "$$PIP_INDEX_URL" -r eval/official/requirements.txt; \
	fi
	@"$(OFFICIAL_BENCH_VENV)/bin/python" -c 'import datasets; print("    datasets", datasets.__version__)'

official-bench-paths: ## 打印官方评测数据/报告目录
	@$(MAKE) -s official-bench-deps
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py paths

official-bench-pull: official-bench-deps ## 拉取 BEIR + LongBench + SWE + C-MTEB 小量（需网络 / HF_ENDPOINT）
	set -a && [ -f .env ] && . ./.env; set +a; \
	HF_ENDPOINT=$${HF_ENDPOINT:-https://hf-mirror.com} \
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py pull --suite all

official-bench-pull-cmteb: official-bench-deps ## 只拉 C-MTEB 三库（合计≈5万篇；FORCE=1 强制重拉）
	@set -a && [ -f .env ] && . ./.env; set +a; \
	DATA_DIR="$${HOST_BENCH_DATA_DIR:-$(CURDIR)/eval/official/.local-data}"; \
	case "$$DATA_DIR" in /data/*) DATA_DIR="$(CURDIR)/eval/official/.local-data" ;; esac; \
	mkdir -p "$$DATA_DIR"; \
	echo "==> C-MTEB pull → $$DATA_DIR (small · ~50k)"; \
	BENCH_DATA_DIR="$$DATA_DIR" HOST_BENCH_DATA_DIR="$$DATA_DIR" \
	HF_ENDPOINT=$${HF_ENDPOINT:-https://hf-mirror.com} \
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py pull --suite cmteb \
	  $(if $(filter 1,$(FORCE)),--force,)

official-bench-retrieval: ## 官方 BEIR 小量（hybrid 主分 + BM25 对照）
	@$(MAKE) -s official-bench-deps
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py retrieval

# L1 agent-path（产品 Turn；需 make up + OPS_TEST_SECRET + BENCH_MODEL_*）
# 冒烟可加 QUERY_LIMIT=5 / OFFICIAL_CONTEXT_LIMIT=3 / OFFICIAL_SWE_TIER=n3
official-bench-retrieval-agent: ## L1 BEIR：search_sources via Turn（Ops API）
	set -a && [ -f .env ] && . ./.env; set +a; \
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py retrieval --eval-path agent \
	  --query-limit $(QUERY_LIMIT)

official-bench-retrieval-zh-agent: ## L1 C-MTEB：search_sources via Turn（Ops API · retrieval_ops_zh）
	set -a && [ -f .env ] && . ./.env; set +a; \
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py retrieval --suite retrieval_zh \
	  --eval-path agent --query-limit $(QUERY_LIMIT)

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

official-bench-coding-pull-images: ## 预拉 sweb.eval 并环境冒烟（默认 board_tier=n5）
	@$(MAKE) -s official-bench-deps
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py coding --phase pull-images \
	  $(if $(OFFICIAL_SWE_IMAGE_TIER),--tier $(OFFICIAL_SWE_IMAGE_TIER),) \
	  $(if $(OFFICIAL_SWE_N),--n-instances $(OFFICIAL_SWE_N),) \
	  $(if $(filter 1,$(FORCE)),--force-pull,)

ops-swe-eval-ready: up-ops-eval official-bench-coding-pull-images ## 看板：挂 sock + 预拉/冒烟（必要一步）
	@echo "==> SWE 评测环境就绪（docker.sock + sweb.eval + 环境冒烟）"

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

swebench-structural-dual-track: ## CSI：打印/执行 agent coding L1 配方（结构已融合；默认 dry-run）
	python3 eval/swebench/run_dual_track.py --n $(or $(OFFICIAL_SWE_N),50) $(if $(EXECUTE),--execute,)

swebench-structural-metrics: ## CSI §8.3：过程指标（需 PRED= GOLD=）
	@test -n "$(PRED)" || (echo "PRED=predictions.jsonl required"; exit 1); \
	test -n "$(GOLD)" || (echo "GOLD=gold.jsonl required"; exit 1); \
	python3 -m eval.swebench.metrics --pred $(PRED) --gold $(GOLD) \
	  $(if $(OUT),--out $(OUT),)

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

official-bench-promote-run: ## 按 run_id 升锚点档（须 sample_tier=anchor；不依赖 latest 时序）
	@test -n "$(RUN_ID)" || (echo "Usage: make official-bench-promote-run RUN_ID=<uuid>"; exit 1)
	$(OFFICIAL_BENCH_PY) scripts/official_bench_run.py baseline --promote-run $(RUN_ID)

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

# P1 lexical micro (no sync): SciFact default 10q × ts_rank vs Okapi on existing PG text.
# MICRO_P1_DATASET=scifact|nfcorpus|fiqa  MICRO_P1_LIMIT=10  MICRO_P1_WORK_ID=<uuid>
MICRO_P1_DATASET ?= scifact
MICRO_P1_LIMIT ?= 10
micro-p1: ## P1 词面微基准（无 sync/无重嵌；默认 SciFact 10q；写 eval/reports/official/p1_lexical_micro.json）
	@test -f .env || (echo "missing .env"; exit 1)
	@test -f eval/official/.local-data/beir/$(MICRO_P1_DATASET)/queries.jsonl || \
	  (echo "missing BEIR slice; run: make official-bench-pull"; exit 1)
	@mkdir -p eval/reports/official
	@echo "==> micro-p1 dataset=$(MICRO_P1_DATASET) limit=$(MICRO_P1_LIMIT) (no sync; overlay host P1 FTS)"
	$(COMPOSE) exec -T -u root runtime bash -c '\
	  rm -rf /tmp/p1-micro && \
	  mkdir -p /tmp/p1-micro/overlay && \
	  cp -a /app/app /tmp/p1-micro/overlay/app && \
	  touch /tmp/p1-micro/overlay/app/retrieval/__init__.py && \
	  chmod -R a+rwX /tmp/p1-micro'
	docker cp scripts/official_bench agent-runtime:/tmp/p1-micro/official_bench
	docker cp eval/official/.local-data/beir agent-runtime:/tmp/p1-micro/beir
	docker cp services/runtime/app/retrieval/bm25_document.py agent-runtime:/tmp/p1-micro/overlay/app/retrieval/bm25_document.py
	docker cp services/runtime/app/retrieval/bm25.py agent-runtime:/tmp/p1-micro/overlay/app/retrieval/bm25.py
	docker cp services/runtime/app/retrieval/pgvector_store.py agent-runtime:/tmp/p1-micro/overlay/app/retrieval/pgvector_store.py
	$(COMPOSE) exec -T runtime bash -c '\
	  export PYTHONPATH=/tmp/p1-micro/overlay:/tmp/p1-micro:/app; \
	  export P1_BEIR_ROOT=/tmp/p1-micro/beir; \
	  cd /tmp && \
	  python -c "from app.retrieval.bm25_document import BM25_EXTRA_FTS_VERSION as v; print(f\"[p1-micro] overlay FTS version={v}\")"; \
	  python /tmp/p1-micro/official_bench/p1_lexical_micro.py \
	    --dataset "$(MICRO_P1_DATASET)" \
	    --limit-queries "$(MICRO_P1_LIMIT)" \
	    $(if $(MICRO_P1_WORK_ID),--work-id "$(MICRO_P1_WORK_ID)",) \
	    --out /tmp/p1_lexical_micro.json'
	@docker cp agent-runtime:/tmp/p1_lexical_micro.json eval/reports/official/p1_lexical_micro.json
	@echo "==> wrote eval/reports/official/p1_lexical_micro.json"

# SciFact mid-corpus micro-index: isolated work scifact-micro (≠ full beir-index/scifact).
# MICRO_L1_LIMIT=20 — judged query head-slice; corpus = gold + seeded distractors.
MICRO_L1_LIMIT ?= 20
MICRO_L1_DISTRACTORS ?= 300
MICRO_L1_SEED ?= 42
micro-l1-prepare: ## SciFact 中库微图准备+嵌入（不跑 Turn；不影响多库主图；Ops「SciFact 微 L1」再评）
	@test -f .env || (echo "missing .env"; exit 1)
	@test -f eval/official/.local-data/beir/scifact/queries.jsonl || \
	  (echo "missing BEIR slice; run: make official-bench-pull"; exit 1)
	@echo "==> micro-l1-prepare limit=$(MICRO_L1_LIMIT) distractors=$(MICRO_L1_DISTRACTORS) → scifact-micro"
	docker cp scripts/official_bench/scifact_micro_prepare.py agent-api:/tmp/scifact_micro_prepare.py
	docker cp services/api/app/services/ops/official_agent_path.py agent-api:/app/app/services/ops/official_agent_path.py
	docker cp services/api/app/services/ops/l1 agent-api:/app/app/services/ops/l1
	$(COMPOSE) exec -T api bash -c '\
	  export PYTHONPATH=/app:/repo/scripts; \
	  python /tmp/scifact_micro_prepare.py \
	    --limit-queries "$(MICRO_L1_LIMIT)" \
	    --distractors "$(MICRO_L1_DISTRACTORS)" \
	    --seed "$(MICRO_L1_SEED)"'

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
