import socket

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://agent:agent@localhost:5432/agent"
    internal_service_token: str = "change-me-internal"
    app_secret_key: str = "change-me-in-production"
    model_provider: str = "anthropic"
    model_name: str = ""
    model_api_key: str = ""
    model_mode: str = "auto"  # auto | stub | recorded | live
    recordings_dir: str = "/app/eval/recordings"
    anthropic_base_url: str = ""
    openai_base_url: str = ""
    workspace_root: str = "/workspace"
    data_dir: str = "/data"
    retrieval_mode: str = "hybrid"  # keyword | vector | hybrid
    index_via_worker: bool = False
    embedding_backend: str = "hash"  # hash | sentence_transformers
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_dir: str = "/data/models"
    embedding_dimensions: int = 256
    app_env: str = "production"
    log_level: str = "INFO"
    model_timeout_seconds: float = 120.0
    tool_default_timeout_seconds: float = 60.0
    step_timeout_seconds: float = 300.0
    stall_threshold_seconds: float = 120.0
    stall_poll_interval_seconds: float = 30.0
    stall_auto_fail: bool = False
    runtime_runner_id: str = socket.gethostname()
    event_payload_validation: bool = True
    run_command_mode: str = "shell"  # shell | simulate
    turn_token_budget: int = 0
    monthly_token_limit: int = 0
    monthly_token_alert_pct: float = 0.8
    context_window_tokens: int = 128_000
    otel_enabled: bool = False
    otel_service_name: str = "agent-runtime"

    @field_validator("runtime_runner_id", mode="before")
    @classmethod
    def _default_runner_id(cls, value: object) -> str:
        if value is None or value == "":
            return socket.gethostname()
        return str(value)


settings = Settings()
