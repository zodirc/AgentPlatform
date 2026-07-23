from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://agent:agent@localhost:5432/agent"
    runtime_url: str = "http://runtime:8001"
    runtime_url_map: str = ""
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
    app_env: str = "production"
    log_level: str = "INFO"
    worker_mode: str = "inline"  # inline | outbox
    worker_poll_interval_seconds: float = 2.0
    worker_batch_size: int = 10
    otel_enabled: bool = False
    otel_service_name: str = "agent-api"
    # docs/27 — Work roots (path strings stored in DB; runtime mounts/creates dirs)
    workspace_root: str = "/workspace"
    works_root: str = "/data/works"
    # First default Work may claim legacy single-workspace path once.
    works_claim_legacy_workspace: bool = True
    # docs/29 — Ops Eval Console (empty = routes disabled)
    ops_test_secret: str = ""
    ops_eval_golden_dir: str = "/app/eval/golden"
    ops_eval_compose_file: str = "/app/deploy/docker-compose.yml"
    ops_eval_compose_project_dir: str = "/app"
    ops_eval_docker_socket: str = "/var/run/docker.sock"


settings = Settings()
