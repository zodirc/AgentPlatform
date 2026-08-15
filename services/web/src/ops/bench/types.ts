export type Criterion = {
  id: string;
  official: string;
  title: string;
  metrics: string;
  pass_rule: string;
  notes: string;
};

export type TargetMeta = {
  id: string;
  label: string;
  group?: string;
  description: string;
  needs_model?: boolean;
};

export type ContextTier = "full" | "40" | "20" | "10" | "5";
/** Numeric = qrels/集；scifact_micro = SciFact 中库（gold+干扰）20q，与主图分离。 */
export type RetrievalTier = "full" | "50" | "20" | "10" | "5" | "scifact_micro";

export type Preset = {
  id: string;
  label: string;
  targets: string[];
  coding_tier?: string;
  coding_n_instances?: number | null;
  coding_harness?: boolean;
  coding_checkout_repo?: boolean;
  workspace_index_wait_ready?: boolean;
  retrieval_prod?: boolean;
  eval_path?: "agent" | "component";
  context_tier?: ContextTier;
  retrieval_tier?: RetrievalTier;
  l1_max_parallel?: number;
  retrieval_arm?: "free" | "forced";
  context_arm?: "free" | "oracle";
  hint: string;
};
export type CodingTierMeta = { id: string; n_instances: number | null };

export type Caps = Record<string, boolean>;

export const SUITE_IDS = [
  "retrieval",
  "retrieval_zh",
  "context",
  "coding",
] as const;
export type SuiteId = (typeof SUITE_IDS)[number];

/** Product scenario → which official suites primarily exercise that path. */
export type BenchScenarioId = "writing" | "agent" | "intel" | "collab";
export type ApiStyle = "openai" | "anthropic";

export type ProviderPreset = {
  id: string;
  label: string;
  api_style: ApiStyle;
  model: string;
  base_url: string;
  context_window?: string;
};
export type OfficialRun = {
  id: string;
  status: string;
  suite?: string;
  official_suite?: string;
  title?: string;
  created_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  progress_done?: number;
  progress_total?: number;
  current_phase?: string;
  phase_hint?: string;
  targets?: string[];
  context_dry?: boolean;
  coding_skip_api?: boolean;
  coding_tier?: string;
  coding_n_instances?: number | null;
  coding_harness?: boolean;
  coding_checkout_repo?: boolean;
  workspace_index_wait_ready?: boolean;
  retrieval_prod?: boolean;
  eval_path?: string;
  context_limit?: number;
  retrieval_query_limit?: number;
  l1_max_parallel?: number;
  retrieval_datasets?: string[];
  retrieval_corpus_mode?: string;
  retrieval_arm?: string;
  context_arm?: string;
  cancel_requested?: boolean;
  report_html_available?: boolean;
  child_reports?: Array<{
    case_id?: string;
    bench_run_id?: string;
    report_html?: string;
  }>;
  summary?: {
    total?: number;
    pass?: number;
    fail?: number;
    skipped?: number;
    pending?: number;
    progress_done?: number;
    progress_total?: number;
    metrics?: Record<string, number>;
  };
  metrics?: Record<string, number>;
  model_meta?: {
    title?: string;
    official_suite?: string;
    targets?: string[];
    context_dry?: boolean;
    coding_skip_api?: boolean;
    coding_tier?: string;
    coding_n_instances?: number | null;
    coding_harness?: boolean;
    coding_checkout_repo?: boolean;
    workspace_index_wait_ready?: boolean;
    retrieval_prod?: boolean;
    eval_path?: string;
    context_limit?: number;
    retrieval_query_limit?: number;
    l1_max_parallel?: number;
    retrieval_datasets?: string[];
    retrieval_corpus_mode?: string;
    retrieval_arm?: string;
    context_arm?: string;
    reclaimed?: boolean;
    report_html_available?: boolean;
    child_reports?: Array<{
      case_id?: string;
      bench_run_id?: string;
      report_html?: string;
    }>;
  };
  source?: string;
  cases?: Array<{
    case_id: string;
    status: string;
    metrics?: Record<string, number>;
    error?: string | null;
    /** Sequential L1 suite wall seconds (Ops 总览). */
    suite_wall_s?: number;
  }>;
  logs?: Array<{
    at?: string;
    kind?: string;
    message?: string;
    case_id?: string;
    status?: string;
    phase?: string;
    progress_done?: number;
    progress_total?: number;
  }>;
};

export type OfficialLogItem = NonNullable<OfficialRun["logs"]>[number];
export type DetailProgress = {
  kind: "pull" | "eval" | "idle";
  label: string;
  pct: number | null;
  /** Suite key when line is attributable (context / coding / retrieval). */
  suite?: string;
  /** Within-suite counters when known (queries / cases / instances). */
  done?: number | null;
  total?: number | null;
  unit?: string;
  /** Sub-buckets (e.g. BEIR dataset → query counts) so multi-part suites accumulate. */
  parts?: Record<string, { done: number; total: number }>;
  partKey?: string;
  /**
   * True while a BEIR dataset is materializing/indexing before its
   * `queries plan` lands — avoids a false "剩 0 查询" between datasets.
   */
  pipelineGap?: boolean;
};
export type AstIndexLive = {
  iid: string;
  status: string;
  filesDone: number | null;
  filesTotal: number | null;
  ephemeral: boolean;
};

/** Transient watcher/log-noise statuses that must not clobber a real index snapshot. */
export const AST_INDEX_WEAK_STATUSES = new Set([
  "poll_error",
  "watch_paused",
  "watch_timeout",
]);

/** Per-instance coding infer + harness outcome for the live progress card. */
export type CodingCaseLive = {
  iid: string;
  /** Infer phase: pending | running | pass | fail */
  status: "pending" | "running" | "pass" | "fail";
  bucket?: string;
  patchSource?: string;
  /** Official harness outcome when available. */
  harness?: "resolved" | "unresolved" | "error";
  /** Agent step.started count (from done log / l2). */
  steps?: number | null;
  /** Wall seconds for this instance (server elapsed_s). */
  elapsedSec?: number | null;
  /** Client clock when case start was seen (live tick for running). */
  startedAtMs?: number | null;
};

export type CodingHarnessLive = {
  phase: "idle" | "running" | "done" | "failed";
  n: number | null;
  /** Completed instances inside harness (mid-run). */
  done: number | null;
  pct: number | null;
  stage: string | null;
  resolved: number | null;
  total: number | null;
  unresolved: number | null;
  error: number | null;
  rate: string | null;
  detail?: string;
};

export type CodingLiveEvent =
  | { kind: "plan"; n: number }
  | { kind: "case"; case: CodingCaseLive }
  | {
      kind: "harness";
      harness: Partial<CodingHarnessLive> & {
        phase: CodingHarnessLive["phase"];
      };
    };
export type MetricAgg = {
  key: string;
  n: number;
  min: number;
  median: number;
  mean: number;
  max: number;
  latest: number;
};
export type ArtifactCase = {
  case_id?: string;
  status?: string;
  bucket?: string | null;
  metrics?: Record<string, number>;
  error?: string | null;
  turn_id?: string | null;
  l2?: Record<string, unknown>;
  patch_source?: string | null;
  patch_applies?: boolean | null;
  resolved?: boolean | null;
  has_repo?: boolean | null;
  ran_tests?: boolean | null;
  patch_preview?: string | null;
  patch_chars?: number | null;
  patch_href?: string | null;
  resolve_verdict?: string | null;
  resolve_label?: string | null;
};

export type SuiteArtifact = {
  suite?: string;
  bench_run_id?: string;
  status?: string;
  title?: string;
  metrics?: Record<string, number>;
  bucket_counts?: Record<string, number>;
  arm?: string;
  sample_tier?: string;
  context_limit?: number | null;
  cases?: ArtifactCase[];
  result?: Record<string, unknown>;
  depth_audit?: Record<string, unknown> | null;
  suite_ndcg_median?: number | null;
  report_html_available?: boolean;
  predictions_available?: boolean;
  csi_probes_available?: boolean;
  thinking_available?: boolean;
  report_href?: string;
  predictions_href?: string;
  csi_probes_href?: string;
  thinking_href?: string;
  coding_scorecard?: Record<string, unknown>;
};

export type RunArtifacts = {
  run_id?: string;
  suites?: SuiteArtifact[];
  n_suites?: number;
};
