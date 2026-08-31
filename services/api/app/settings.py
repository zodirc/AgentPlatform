"""Agent API 运行时配置（Pydantic Settings，环境变量 + 可选 ``.env``）。

English: Agent API configuration — DB, runtime routing, auth, dispatch, projection knobs.

配置域概览：
- **数据库**：``database_url``、双池 statement timeout（hot/bypass）、连接池大小
- **Runtime**：``runtime_url`` / ``runtime_url_map``、内部服务令牌
- **认证**：``auth_enabled``、终端用户登录、admin 旁路、Cookie secure
- **调度**：``turn_dispatch``（pull/push）、claim 超时、pull 模式准入队列上限
- **Runner 租约**：与 runtime ``RUNNER_LEASE_*`` 配对的 api 侧回收间隔
- **命令通道**：``run_commands_channel_enabled``（DB+NOTIFY vs 直连 HTTP）
- **事件保留**：流式/结构化 turn_events 保留天数与批处理预算
- **Work 根路径**：``workspace_root`` / ``works_root``、legacy 迁移开关
- **Ops Eval**：``ops_test_secret`` 非空时挂载评测路由；Docker/compose 路径
- **可观测性**：日志级别、OpenTelemetry 开关与服务名
- **Worker**：``worker_mode``（inline/outbox）与轮询参数

生产环境启动时调用 ``Settings.validate_production_security()`` 拒绝弱密钥与危险旁路。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


_WEAK_PRODUCTION_VALUES = frozenset(
    {"change-me", "change-me-internal", "change-me-in-production", "admin"}
)


class Settings(BaseSettings):
    """从环境变量加载的全部 API 服务配置项。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://agent:agent@localhost:5432/agent"
    # B10 legacy single timeout (kept for env compat; hot pool prefers db_hot_*).
    db_statement_timeout_seconds: float = 30.0
    # O10 / WP4: dual-pool timeouts (hot Turn/SSE/projection · bypass RAG/AST/Ops).
    db_hot_statement_timeout_seconds: float = 5.0
    db_bypass_statement_timeout_seconds: float = 120.0
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5
    runtime_url: str = "http://runtime:8001"
    runtime_url_map: str = ""
    # ADR-020: sources index / remote embed plane (not the Turn orchestrator).
    sources_retrieval_url: str = "http://sources-retrieval:8001"
    model_gateway_url: str = "http://model-gateway:8003"
    sandbox_plane_url: str = "http://sandbox:8004"
    redis_url: str = "redis://redis:6379/0"
    internal_service_token: str = "change-me-internal"
    app_secret_key: str = "change-me"
    auth_enabled: bool = False
    admin_password: str = "admin"
    # End-user login for session ownership (docs/16). Default on.
    end_user_auth_enabled: bool = True
    # Allow admin Basic to act as system owner (eval / scripts).
    admin_session_bypass: bool = True
    # Set true behind HTTPS only; false for local HTTP gateway.
    end_user_cookie_secure: bool = False
    # Development remains the safe default for local `make up`; production must
    # be selected explicitly and passes the guard below during startup.
    app_env: str = "development"
    log_level: str = "INFO"
    worker_mode: str = "inline"  # inline | outbox
    worker_poll_interval_seconds: float = 2.0
    worker_batch_size: int = 10
    otel_enabled: bool = False
    otel_service_name: str = "agent-api"
    # O3 / WP1: api-side lease reclaim (pair with runtime RUNNER_LEASE_*).
    runner_lease_enabled: bool = True
    runner_lease_reconcile_interval_seconds: float = 30.0
    # O1 / WP5→WP9: default pull (set TURN_DISPATCH=push to roll back).
    turn_dispatch: str = "pull"
    # Wake channel for pull claim: redis | postgres | both.
    # Truth/CAS stay in Postgres; Redis Pub/Sub is doorbell-only.
    turn_dispatch_wake: str = "redis"
    # Live SSE: also consume turn.live.* Pub/Sub (durable catch-up still PG).
    turn_live_fanout_enabled: bool = True
    turn_claim_timeout_seconds: float = 15.0
    # O2 / WP6: approve/deny/patch/cancel via run_commands table (false → legacy HTTP).
    run_commands_channel_enabled: bool = True
    # O4 / WP7: pull-mode admission caps (0 global → default 32).
    dispatch_queue_max: int = 0
    per_tenant_queue_max: int = 2
    # O7 / WP3: turn_events retention.
    events_stream_retention_days: int = 7
    events_structural_retention_days: int = 90
    events_retention_interval_seconds: float = 3600.0
    events_retention_stream_batch: int = 50_000
    events_retention_structural_batch: int = 10_000
    events_retention_budget_seconds: float = 25.0
    # Optional Fernet secret for model API keys. Empty → APP_SECRET_KEY.
    config_encryption_key: str = ""
    # docs/27 — Work roots (path strings stored in DB; runtime mounts/creates dirs)
    workspace_root: str = "/workspace"
    works_root: str = "/data/works"
    # First default Work may claim legacy single-workspace path once.
    works_claim_legacy_workspace: bool = True
    # docs/29 — Ops Eval Console (empty = routes disabled)
    ops_test_secret: str = ""
    # Backend-private scratch for golden cases (not under user WORKSPACE_ROOT).
    ops_eval_workspace_root: str = "/data/ops-eval"
    ops_eval_golden_dir: str = "/app/eval/golden"
    ops_eval_compose_file: str = "/app/deploy/docker-compose.yml"
    ops_eval_compose_project_dir: str = "/app"
    ops_eval_docker_socket: str = "/var/run/docker.sock"
    # Repo mount inside api (compose: ..:/repo) — used to discover host path for suite=ci.
    ops_eval_repo_mount: str = "/repo"
    ops_eval_repo_host_path: str = ""  # optional override; else docker inspect

    def validate_production_security(self) -> None:
        """生产环境启动门禁：拒绝弱密钥与特权旁路。

        参数:
            无（读取 ``self`` 各字段）。

        返回:
            None；``app_env`` 非 production/prod 时直接返回。

        抛出:
            RuntimeError：密钥仍为占位值、admin 旁路开启、或认证被关闭时。
        """
        if self.app_env.strip().lower() not in {"production", "prod"}:
            return

        weak_fields = {
            name
            for name, value in {
                "APP_SECRET_KEY": self.app_secret_key,
                "INTERNAL_SERVICE_TOKEN": self.internal_service_token,
                "ADMIN_PASSWORD": self.admin_password,
            }.items()
            if not value.strip() or value.strip().lower() in _WEAK_PRODUCTION_VALUES
        }
        if weak_fields:
            raise RuntimeError(
                "production requires non-default values for "
                + ", ".join(sorted(weak_fields))
            )
        if self.admin_session_bypass:
            raise RuntimeError(
                "ADMIN_SESSION_BYPASS must be false when APP_ENV=production"
            )
        # auth_enabled=False lets require_admin_or_end_user pass anonymous
        # requests straight through to /admin/workspace/* (read/write/delete).
        if not self.auth_enabled:
            raise RuntimeError("AUTH_ENABLED must be true when APP_ENV=production")
        if not self.end_user_auth_enabled:
            raise RuntimeError(
                "END_USER_AUTH_ENABLED must be true when APP_ENV=production"
            )


settings = Settings()
