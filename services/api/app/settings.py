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
    app_env: str = "production"
    log_level: str = "INFO"
    worker_mode: str = "inline"  # inline | outbox
    worker_poll_interval_seconds: float = 2.0
    worker_batch_size: int = 10
    otel_enabled: bool = False
    otel_service_name: str = "agent-api"


settings = Settings()
