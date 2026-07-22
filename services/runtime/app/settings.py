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
    # RQ1e: hybrid lane weights / doc boost (profile may override; see retrieval/profile.py).
    retrieval_profile: str = "default"  # default | vector_heavy
    retrieval_rrf_vector_weight: float = 1.0
    retrieval_rrf_bm25_weight: float = 1.0
    retrieval_doc_boost: float = 0.35
    # Backend: pgvector (default ANN via HNSW; needs pgvector image) | json (file fallback).
    retrieval_backend: str = "pgvector"
    # Postgres schema for source_* tables (IX4 prod-bench uses retrieval_bench to avoid
    # wiping the user index when syncing an isolated temp workspace).
    retrieval_pg_schema: str = "public"
    # Two-level doc→chunk recall (docs/13 S3 A11): parallel lanes; timeout → chunk-only.
    retrieval_two_level_enabled: bool = True
    retrieval_two_level_timeout_seconds: float = 0.3
    retrieval_two_level_doc_limit: int = 8
    # Lexical rerank may stay on (cheap). Cross-encoder stays OFF by default
    # (docs/21 Q8/Q13, docs/13 S2 A12). Experimental CE: pool≤20 + ≤50ms + timeout→lexical.
    retrieval_rerank_enabled: bool = True
    retrieval_rerank_cross_encoder: bool = False
    retrieval_rerank_model: str = "BAAI/bge-reranker-base"
    retrieval_rerank_pool: int = 20
    retrieval_rerank_timeout_seconds: float = 0.05
    # RQ1b: title-tree leaf soft budget (~2000 token char approx) then sliding window.
    retrieval_chunk_max_chars: int = 4000
    retrieval_chunk_overlap_chars: int = 400
    # Wide markdown tables → pointer in indexed body (full table stays on disk for read_file).
    retrieval_table_detach_min_rows: int = 6
    retrieval_table_detach_min_chars: int = 800
    search_sources_max_per_turn: int = 3
    search_sources_excerpt_chars: int = 200
    search_sources_low_score_hint: float = 0.15
    # RE1: keyword fallback section alignment (docs/15); oversize / timeout → file excerpt only.
    search_sources_keyword_max_file_bytes: int = 262_144
    search_sources_keyword_parse_budget_ms: float = 50.0
    # S0 harness guards (docs/13-rate-redlines.md).
    tool_schema_validate: bool = True
    citation_verify_enabled: bool = True
    model_egress_enforce: bool = True
    # Comma-separated extra base URLs or hosts allowed for live model calls.
    model_egress_allowlist: str = ""
    # Content privacy (docs/13 S2 A15/A16) — regex only; never LLM desensitization.
    pii_redact_enabled: bool = True
    secret_scan_enabled: bool = True
    secret_scan_timeout_ms: float = 50.0
    # Writing material cards (Agent-outside artifacts; pinned into writing turns).
    # Inventory-deterministic pin (docs/14 C1/C3): kind → path sort; per-kind + global caps.
    writing_cards_dir: str = "sources/cards"
    writing_cards_max_chars: int = 2000
    writing_cards_per_card_chars: int = 800
    writing_cards_style_max_chars: int = 800
    writing_cards_character_max_chars: int = 1000
    writing_cards_plot_max_chars: int = 600
    writing_cards_general_max_chars: int = 400
    writing_export_profile: str = "novel-zh"  # novel-zh | essay | none
    # Writing: propose_patch auto-writes to disk (natural UX); UI still shows diff as applied.
    writing_patch_auto_apply: bool = True
    # WW1/WW2: work-scoped drafts (docs/23); history snapshots per section (0 disables).
    writing_draft_history_keep: int = 5
    writing_work_index_max_chars: int = 1200
    # monofile (default): chapters append into manuscript.md; sections = one file per chapter.
    writing_manuscript_mode: str = "monofile"
    writing_manuscript_path: str = "manuscript.md"
    # docs/24 token economy: work surface + read_file chapter extract (no LLM).
    writing_work_surface_max_chars: int = 6000
    writing_focus_max_chars: int = 12000
    writing_prev_tail_chars: int = 2000
    writing_token_economy_enabled: bool = True

    index_via_worker: bool = True
    # IX0: Turn-external incremental projection of workspace/sources (docs/15).
    sources_startup_sync_enabled: bool = True
    sources_startup_sync_delay_seconds: float = 3.0
    # IX2: poll workspace/sources and debounce-incremental sync (Turn-external).
    sources_watch_enabled: bool = True
    sources_watch_poll_seconds: float = 2.0
    sources_watch_debounce_seconds: float = 1.5
    # Standing seed corpus root inside the container (RO bind of repo seed/sources/writing).
    # Empty disables seed-specific guards only; indexing still follows workspace/sources tree.
    seed_sources_root: str = "/workspace/sources/seed/writing"
    # Optional default owner for future multi-tenant rows (empty → NULL / shared).
    sources_index_owner_user_id: str = ""
    embedding_backend: str = "hash"  # hash | sentence_transformers
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_dir: str = "/data/models"
    # Hash default 256; all-MiniLM-L6-v2 is 384 — compose sets 384 with ST.
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
    # Optional smaller / cheaper model for compact only (docs/13 S3 A17).
    # Empty → reuse the main turn model; failures still fall back to deterministic summary.
    compact_model_name: str = ""
    compact_model_provider: str = ""
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
    # docs/27 MT5b: soft cap on concurrent Turns in this process (0 = unlimited).
    runtime_max_inflight_turns: int = 16
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
