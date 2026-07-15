import socket
from typing import Optional

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
    retrieval_rrf_k: int = 60
    # Lexical rerank may stay on (cheap). Cross-encoder stays OFF by default
    # (docs/16 Q8/Q13, docs/17 S2 A12). Experimental CE: pool≤20 + ≤50ms + timeout→lexical.
    retrieval_rerank_enabled: bool = True
    retrieval_rerank_cross_encoder: bool = False
    retrieval_rerank_model: str = "BAAI/bge-reranker-base"
    retrieval_rerank_pool: int = 20
    retrieval_rerank_timeout_seconds: float = 0.05
    search_sources_max_per_turn: int = 3
    search_sources_excerpt_chars: int = 200
    search_sources_low_score_hint: float = 0.15
    # S0 harness guards (docs/17-execution-plan.md).
    tool_schema_validate: bool = True
    citation_verify_enabled: bool = True
    model_egress_enforce: bool = True
    # Comma-separated extra base URLs or hosts allowed for live model calls.
    model_egress_allowlist: str = ""
    # Content privacy (docs/17 S2 A15/A16) — regex only; never LLM desensitization.
    pii_redact_enabled: bool = True
    secret_scan_enabled: bool = True
    secret_scan_timeout_ms: float = 50.0
    # Writing material cards (Agent-outside artifacts; pinned into writing turns).
    writing_cards_dir: str = "sources/cards"
    writing_cards_max_chars: int = 2000
    writing_cards_per_card_chars: int = 800
    index_via_worker: bool = True
    embedding_backend: str = "hash"  # hash | sentence_transformers
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_dir: str = "/data/models"
    embedding_dimensions: int = 256
    app_env: str = "production"
    log_level: str = "INFO"
    model_timeout_seconds: float = 120.0
    # H1 harness: fast-fail first byte / connect so retries start early.
    model_first_byte_timeout_seconds: float = 15.0
    model_connect_timeout_seconds: float = 10.0
    model_max_retries: int = 2
    model_retry_base_delay_seconds: float = 0.5
    model_retry_max_delay_seconds: float = 8.0
    # Generation strategy (aligned with CompactionPolicy.output_reserve_tokens).
    model_max_output_tokens: int = 0  # 0 → use context_output_reserve_tokens
    model_temperature_writing: float = 0.3
    model_temperature_agent: Optional[float] = None
    model_top_p: Optional[float] = None
    model_tool_choice: str = "auto"  # auto | required | none
    model_thinking_enabled: bool = False
    # AH4: autocompact summarizer budget (independent of main turn).
    compact_timeout_seconds: float = 20.0
    compact_max_output_tokens: int = 1024
    # AH3: project context + @path prereread budgets.
    project_context_max_chars: int = 2_000
    path_preread_max_chars: int = 1_200
    path_preread_timeout_seconds: float = 0.4
    path_preread_max_files: int = 3
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
    # Reserved for model output; subtracted from window when computing fill ratio.
    context_output_reserve_tokens: int = 16_384
    # Assembled-window fill thresholds (0–1) for pressure-driven compaction.
    # Below collapse: keep rolling history verbatim (mainstream-like).
    context_fill_collapse: float = 0.80
    context_fill_snip: float = 0.90
    context_fill_autocompact: float = 0.95
    # Fraction of working message budget kept verbatim in collapse tail.
    context_hot_zone_ratio: float = 0.35
    otel_enabled: bool = False
    otel_service_name: str = "agent-runtime"

    @field_validator("runtime_runner_id", mode="before")
    @classmethod
    def _default_runner_id(cls, value: object) -> str:
        if value is None or value == "":
            return socket.gethostname()
        return str(value)


settings = Settings()
