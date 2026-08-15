import socket
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_WEAK_PRODUCTION_VALUES = frozenset(
    {"change-me", "change-me-internal", "change-me-in-production", "admin"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://agent:agent@localhost:5432/agent"
    # Ops L1 vector plane (Schema A): source_* for ops-l1 works. Empty → fall back to
    # bench_database_url, then (if both empty) product database_url (compat).
    ops_database_url: str = ""
    # L0 / legacy alias; runtime Ops plane prefers ops_database_url then this.
    bench_database_url: str = ""
    # B10 legacy single timeout (kept for env compat; hot pool prefers db_hot_*).
    db_statement_timeout_seconds: float = 30.0
    # O10 / WP4: dual-pool timeouts.
    db_hot_statement_timeout_seconds: float = 5.0
    db_bypass_statement_timeout_seconds: float = 120.0
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5
    # B2: max seconds to wait for in-flight turns on SIGTERM before teardown.
    shutdown_drain_seconds: float = 25.0
    # B9: evict abandoned approval state after this long (checkpoint fallback).
    pending_store_ttl_seconds: float = 1800.0
    internal_service_token: str = "change-me-internal"
    app_secret_key: str = "change-me-in-production"
    model_provider: str = "anthropic"
    model_name: str = ""
    model_api_key: str = ""
    model_mode: str = "auto"  # auto | stub | recorded | live
    # Fail test fixtures that silently fall through an unimplemented stub route.
    stub_fail_on_unrouted: bool = False
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
    # P1②: FTS recall + in-memory Okapi BM25Scorer rescore (rollback → ts_rank_cd).
    retrieval_bm25_rescore_enabled: bool = True
    # Backend: pgvector (default ANN via HNSW; needs pgvector image) | json (file fallback).
    retrieval_backend: str = "pgvector"
    # Postgres schema for source_* tables (IX4 prod-bench uses retrieval_bench to avoid
    # wiping the user index when syncing an isolated temp workspace).
    retrieval_pg_schema: str = "public"
    # Ops L1 source_* schema on OPS_DATABASE_URL (keep apart from L0 retrieval_bench).
    ops_retrieval_pg_schema: str = "retrieval_ops"
    # C-MTEB corpus HNSW only (same embedder as BEIR/product; not a second model).
    ops_retrieval_pg_schema_zh: str = "retrieval_ops_zh"
    # Two-level doc→chunk recall (docs/13 S3 A11): parallel lanes; timeout → chunk-only.
    retrieval_two_level_enabled: bool = True
    retrieval_two_level_timeout_seconds: float = 0.3
    retrieval_two_level_doc_limit: int = 8
    # P3: true source_docs ANN; false / empty table → wide chunk ANN distinct-path approx.
    retrieval_two_level_doc_table: bool = True
    # Lexical rerank may stay on (cheap). Cross-encoder stays OFF by default
    # (docs/21 Q8/Q13, docs/13 S2 A12). Experimental CE: pool≤20 + ≤50ms + timeout→lexical.
    retrieval_rerank_enabled: bool = True
    retrieval_rerank_cross_encoder: bool = False
    retrieval_rerank_model: str = "BAAI/bge-reranker-base"
    retrieval_rerank_pool: int = 20
    retrieval_rerank_timeout_seconds: float = 0.05
    # R-5: enable CE only after GPU P95 < this (ms). Unused until measured; default stays off.
    retrieval_rerank_cross_encoder_max_p95_ms: float = 150.0
    # Token-aligned budget (R-1). Kept ≤ embedding_max_seq≈512 with headroom.
    retrieval_chunk_max_tokens: int = 450
    retrieval_chunk_overlap_tokens: int = 64
    # Char fallback when tokenizer is unavailable (latin ≈4 char/token → ~1800).
    retrieval_chunk_max_chars: int = 1800
    retrieval_chunk_overlap_chars: int = 200
    # Wide markdown tables → pointer in indexed body (full table stays on disk for read_file).
    retrieval_table_detach_min_rows: int = 6
    retrieval_table_detach_min_chars: int = 800
    search_sources_max_per_turn: int = 3
    # docs/34 RC5 — hard cap on read_file executions per Turn (0 = disabled).
    read_file_max_per_turn: int = 16
    search_sources_excerpt_chars: int = 400
    # RET-12: top-N hits keep full excerpt; remainder path/title/score only (fit 4k tool_result).
    search_sources_detail_hits: int = 5
    # RET-15-2: calibrated on free smoke top1 distribution (p10≈1.06); old 0.15 never fired.
    search_sources_low_score_hint: float = 1.0
    # RET-15-2: model-facing scores are 0–100 relative to top-1; raw kept as score_raw for IR.
    search_sources_score_rel: bool = True
    # RET-7: excerpt-cover promote (silent reorder). Default off after free N≥2
    # ablation showed no stable IR benefit (docs/topics/retrieval-free-l1-tuning-brief §12.9).
    search_sources_excerpt_promote: bool = False
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
    # C2: when false (default), tools JSON stays static; late-stage drops are runtime gates.
    # Set true to restore legacy schema mutation (breaks prompt-cache prefix).
    stage_tool_scope_mutate_schema: bool = False
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
    # Intel standing corpus (RO bind of repo seed/sources/intel; _demo + vendor).
    seed_intel_root: str = "/workspace/sources/seed/intel"
    # Optional default owner for future multi-tenant rows (empty → NULL / shared).
    sources_index_owner_user_id: str = ""
    embedding_backend: str = "hash"  # hash | sentence_transformers
    # Production default via compose / resolve_embedding_profile:
    # GPU → bge-m3@1024 (shared EN+ZH embedder for product/BEIR/C-MTEB);
    # CPU → gte-small@384. MiniLM / gte-large retired as auto defaults.
    embedding_model: str = "thenlper/gte-small"
    embedding_model_dir: str = "/data/models"
    # Hash default 256; gte-small=384; bge-m3|gte-large=1024 — compose/auto.env sets dims.
    embedding_dimensions: int = 256
    # Index-plane batch encode size (docs/15). Hot-path search still embeds one query.
    embedding_batch_size: int = 64
    # O5 / WP2: query embed preempts index batch encode (set false to A/B).
    embedding_query_priority: bool = True
    # CPU torch thread cap when embedding on CPU (event-loop friendliness).
    embedding_torch_num_threads: int = 2
    # ST truncate length. 0 → model default, except bge-m3 auto 512 (8k default thrashs VRAM).
    embedding_max_seq_length: int = 0
    # Embed-space index stamp. 0 → derive from model/max_seq (see effective_index_version).
    # resolve_embedding_profile writes EMBEDDING_INDEX_VERSION (bge-m3@512 → 13).
    embedding_index_version: int = 0
    # 0 → auto: force reindex ≥1024 (batch×16), incremental batch×2. Override flush size.
    embedding_flush_chunks: int = 0
    # 0 → auto: force reindex commit every 4 flushes, else every flush (resume checkpoints).
    embedding_commit_every_flushes: int = 0
    # auto → CUDA when torch.cuda.is_available(); else cpu|cuda force.
    embedding_device: str = "auto"
    # Progress log every N files during sync (0 = only batch/flush logs).
    embedding_progress_every_files: int = 25
    # P2: when false, embed body only (no path:/tags: prefix noise). Re-embed to take effect.
    embedding_text_include_metadata: bool = False
    # Development remains the safe default for local `make up`; production must
    # be selected explicitly and passes the guard below during startup.
    app_env: str = "development"
    log_level: str = "INFO"
    model_timeout_seconds: float = 600.0
    # H1 harness: fast-fail first byte / connect so retries start early.
    model_first_byte_timeout_seconds: float = 15.0
    model_connect_timeout_seconds: float = 10.0
    model_max_retries: int = 2
    model_retry_base_delay_seconds: float = 0.5
    model_retry_max_delay_seconds: float = 8.0
    # Generation strategy (aligned with CompactionPolicy.output_reserve_tokens).
    # 0 → scale reserve with context window (see context_output_* below).
    model_max_output_tokens: int = 0
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
    # Coding structural lane (agent Profile): timeouts / prewarm / budgets only.
    # Capability lives in Profile.tool_names — not a feature flag; no strip/disable.
    structural_nav_timeout_s: float = 15.0
    structural_diag_timeout_s: float = 60.0
    structural_max_files_per_call: int = 20
    structural_max_refs: int = 80
    # Wave 2 W1: edit_file.checks incremental diagnostics (single-file; not full-repo).
    structural_checks_max_issues: int = 20
    structural_checks_timeout_s: float = 30.0
    # Wave 2 W3: span miss / non-unique candidate echo budget.
    structural_span_candidates: int = 5
    # Soft prewarm when an agent Work starts (does not block TTFB / R1).
    structural_prewarm: bool = True
    # Wave 4 W9: omit verify_receipt when remaining steps < this reserve.
    verify_receipt_reserve_steps: int = 10
    # Agent workspace AST index (docs/plan/agent-workspace-ast-index.md). Off-loop only.
    workspace_ast_enabled: bool = True
    # Ops/SWE temp works: default off (§7). Set true only for explicit dual-track experiments.
    workspace_ast_ops_enabled: bool = False
    # A6: False = enqueue to work_ast_index_jobs (remote indexer). True = legacy
    # same-process cold start (unit tests / emergency fallback only — not product终态).
    workspace_ast_inline: bool = False
    workspace_ast_max_files: int = 20_000
    workspace_ast_max_file_bytes: int = 1_048_576
    workspace_ast_parse_concurrency: int = 3
    workspace_ast_dirty_debounce_seconds: float = 0.5
    workspace_ast_dirty_backpressure: int = 500
    workspace_ast_locate_top_k: int = 5
    workspace_ast_idle_ttl_seconds: float = 600.0
    workspace_ast_max_cached_works: int = 8
    workspace_ast_poll_seconds: float = 45.0
    # Eval-ephemeral cold-start budget (§7.2): dynamic clamp(f(n_files), min, max).
    # Fixed seconds are only an explicit override / walk reserve — not the mature path.
    workspace_ast_eval_budget_seconds: float = 0.0  # 0 = use dynamic; >0 overrides whole job
    workspace_ast_eval_budget_min_seconds: float = 60.0
    workspace_ast_eval_budget_max_seconds: float = 900.0
    workspace_ast_eval_budget_seconds_per_file: float = 0.75
    workspace_ast_eval_budget_overhead_seconds: float = 45.0
    workspace_ast_eval_walk_budget_seconds: float = 90.0
    # Cap files/parse threads for eval so indexing cannot starve StartTurn.
    workspace_ast_eval_max_files: int = 4_000
    workspace_ast_eval_parse_concurrency: int = 2
    # Ops / SWE-bench Lite: when True, ops_eval Turns run shell/LSP children with
    # no egress (bwrap --unshare-net). Daily non-ops Turns keep host network.
    # Map OFFICIAL_SWE_NETWORK=deny → OPS_EVAL_DENY_NETWORK=true in compose.
    ops_eval_deny_network: bool = False
    # Must exceed model_timeout so a long think cannot lose to step wall-clock first.
    step_timeout_seconds: float = 720.0
    stall_threshold_seconds: float = 180.0
    stall_poll_interval_seconds: float = 30.0
    # Default on: silent hangs (no new events) must not leave UI spinning forever.
    stall_auto_fail: bool = True
    runtime_runner_id: str = socket.gethostname()
    # O3 / WP1: DB heartbeat + run lease (set false to roll back to stall-only reclaim).
    # 180s TTL: coding steps often run 60–160s under parallel load; 60s was reclaiming
    # live turns when heartbeat contended with thinking.delta floods.
    runner_lease_enabled: bool = True
    runner_lease_seconds: int = 180
    runner_heartbeat_interval_seconds: float = 10.0
    # Min gap between opportunistic lease touches (event flush / step checkpoint).
    runner_lease_touch_min_interval_seconds: float = 5.0
    # O1 / WP5→WP9: default pull (set TURN_DISPATCH=push to roll back).
    turn_dispatch: str = "pull"
    turn_dispatch_poll_seconds: float = 2.0
    # O2 / WP6: consume run_commands for owned runs.
    run_commands_channel_enabled: bool = True
    # docs/27 MT5b: soft cap on concurrent Turns in this process (0 = unlimited).
    runtime_max_inflight_turns: int = 16
    event_payload_validation: bool = True
    # Ops eval: do not INSERT turn.thinking.delta (write amplification). Product
    # Turns always persist. Set true to restore eval thinking in turn_events.
    ops_eval_persist_thinking: bool = False
    # When thinking is diverted, append JSONL under work_root/.agent/thinking/.
    ops_eval_thinking_sidecar: bool = True
    # Cheap DB liveness while thinking is off the event table (stall/lease).
    ops_eval_thinking_heartbeat_seconds: float = 15.0
    # Review I2: coalesce stream delta events into one multi-row insert per
    # window. 0 disables batching (per-event writes, instant rollback knob).
    event_batch_window_seconds: float = 0.04
    # When False (default), high-freq streaming events use a light shape check
    # instead of full jsonschema (R3). Set True in CI for strict delta schemas.
    event_payload_validation_strict_deltas: bool = False
    run_command_mode: str = "shell"  # shell | simulate
    turn_token_budget: int = 0
    monthly_token_limit: int = 0
    monthly_token_alert_pct: float = 0.8
    context_window_tokens: int = 128_000
    # Proportional max-output / fill reserve: at ref_window → reserve tokens.
    # Example: 128K → 30K; Web profile window 256K → 60K. Absolute override:
    # set MODEL_MAX_OUTPUT_TOKENS > 0.
    context_output_scale_ref_window_tokens: int = 128_000
    context_output_reserve_tokens: int = 30_000
    # Assembled-window fill thresholds (0–1) for pressure-driven compaction.
    # Below collapse: keep rolling history verbatim (mainstream-like).
    context_fill_collapse: float = 0.80
    context_fill_snip: float = 0.90
    context_fill_autocompact: float = 0.95
    # HM1: soft fill triggers async precompact between turns (0 disables).
    context_fill_soft_precompact: float = 0.78
    precompact_cache_ttl_seconds: float = 3600.0
    # HM1: hard-path sync compact LLM is opt-in; default = deterministic summary.
    context_hard_autocompact_allow_llm: bool = False
    # HM8: fold long narratives into layers (default off).
    context_layered_summary_enabled: bool = False
    # HM2 / HM4 observability (async; never blocks TTFB).
    raw_snapshot_enabled: bool = True
    model_envelope_enabled: bool = True
    model_envelope_sample_rate: float = 1.0
    model_envelope_on_high_fill: bool = True
    model_envelope_debug: bool = False
    # HM7: export citation verify gate — off | warn | block
    writing_export_verify_mode: str = "warn"
    # Fraction of working message budget kept verbatim in collapse tail.
    context_hot_zone_ratio: float = 0.35
    # C-1 / round1: per-tool_result char budgets (Settings, not module constants).
    # Default 4k for ordinary tool_result; latest read_file body may use the higher
    # budget so long reads are not snipped to ~3% before the model sees them.
    tool_result_char_budget: int = 4_000
    tool_result_latest_read_char_budget: int = 32_000
    # When True, snip/collapse must not drop the current user instruction group
    # or the latest read_file cycle (snip floor).
    context_snip_protect_latest_read: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "agent-runtime"

    @field_validator("runtime_runner_id", mode="before")
    @classmethod
    def _default_runner_id(cls, value: object) -> str:
        if value is None or value == "":
            return socket.gethostname()
        return str(value)

    def validate_production_security(self) -> None:
        """Reject bootstrap credentials when the runtime serves production."""
        if self.app_env.strip().lower() not in {"production", "prod"}:
            return

        weak_fields = {
            name
            for name, value in {
                "APP_SECRET_KEY": self.app_secret_key,
                "INTERNAL_SERVICE_TOKEN": self.internal_service_token,
            }.items()
            if not value.strip() or value.strip().lower() in _WEAK_PRODUCTION_VALUES
        }
        if weak_fields:
            raise RuntimeError(
                "production requires non-default values for "
                + ", ".join(sorted(weak_fields))
            )


settings = Settings()
