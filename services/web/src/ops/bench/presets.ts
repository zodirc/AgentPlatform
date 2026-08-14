import type {
  BenchScenarioId,
  ContextTier,
  Preset,
  RetrievalTier,
  SuiteId,
} from "./types";
import { SUITE_IDS } from "./types";

export const CUSTOM_PROFILE_ID = "custom";

/** Human labels for the profile parameter form. */
export function retrievalTierLabel(t: RetrievalTier): string {
  if (t === "full") return "全量 qrels (~1.3k)";
  if (t === "scifact_micro") return "SciFact 微 L1（中库 · 20q）";
  return `${t} q/集`;
}

export function contextTierLabel(t: ContextTier): string {
  const perTask = t === "full" ? 40 : Number(t);
  const approxTotal = perTask * 3;
  if (t === "full") return `全量 · ${perTask}/task（≈${approxTotal}）`;
  return `${perTask}/task（≈${approxTotal}）`;
}

/** Client fallback if meta.presets is old / empty — 一键配置档. */
export const L1_RUN_PROFILES: Preset[] = [
  {
    id: "l1_balanced",
    label: "适中（推荐）",
    targets: ["retrieval", "coding"],
    eval_path: "agent",
    coding_tier: "n5",
    coding_harness: true,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "20",
    retrieval_tier: "20",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "L1 m3 · 自由臂 · 检索 20q/集 + 编码 n5 + 官方 harness · 冒烟档",
  },
  {
    id: "l1_smoke",
    label: "快速冒烟",
    targets: ["retrieval", "coding"],
    eval_path: "agent",
    coding_tier: "n3",
    coding_harness: true,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "10",
    retrieval_tier: "10",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "L1 m3 · n3+harness 冒烟 · 约 0.5–2h",
  },
  {
    id: "l1_three",
    label: "三项适中",
    targets: ["retrieval", "context", "coding"],
    eval_path: "agent",
    coding_tier: "n5",
    coding_harness: true,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "20",
    retrieval_tier: "20",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "L1 三套自由臂 · 每 task 20 · 编码必跑 harness · 冒烟档",
  },
  {
    id: "l1_full",
    label: "小切片全量（锚点）",
    targets: ["retrieval", "context", "coding"],
    eval_path: "agent",
    coding_tier: "n25",
    coding_harness: true,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "full",
    retrieval_tier: "full",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "锚点档 · 全量 qrels + LongBench 全量 + n25+harness · 过夜级",
  },
  {
    id: "retrieval_only",
    label: "仅检索适中",
    targets: ["retrieval"],
    eval_path: "agent",
    coding_tier: "n5",
    coding_harness: true,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "20",
    retrieval_tier: "20",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "只要检索 L1 自由臂 · 20q/集",
  },
  {
    id: "retrieval_zh_only",
    label: "仅中文检索",
    targets: ["retrieval_zh"],
    eval_path: "agent",
    coding_tier: "n5",
    coding_harness: true,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "20",
    retrieval_tier: "20",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "C-MTEB L1 · 同模 bge-m3 · 仅 retrieval_ops_zh 分图 · 20q/集 · 勿与 BEIR 混宏分",
  },
];

/** Infer which profile chip matches saved run params (legacy prefs without active_profile_id). */
export function inferProfileIdFromSaved(saved: {
  suites?: string[];
  coding_tier?: string;
  coding_harness?: boolean;
  coding_checkout_repo?: boolean;
  retrieval_prod?: boolean;
  eval_path?: string;
  context_tier?: string;
  retrieval_tier?: string;
  l1_max_parallel?: number;
  retrieval_arm?: string;
  context_arm?: string;
}): string {
  const suites = new Set(saved.suites || []);
  for (const p of L1_RUN_PROFILES) {
    const want = new Set(
      (p.targets || [])
        .map((t) => (t === "coding_infer" || t === "coding" ? "coding" : t))
        .filter((t): t is SuiteId =>
          (SUITE_IDS as readonly string[]).includes(t),
        ),
    );
    if (want.size !== suites.size || [...want].some((s) => !suites.has(s)))
      continue;
    if ((p.coding_tier || "n5") !== (saved.coding_tier || "n5")) continue;
    // coding_harness is always on for coding; do not use it for profile identity.
    if (
      (p.coding_checkout_repo !== false) !==
      (saved.coding_checkout_repo !== false)
    ) {
      continue;
    }
    if ((p.retrieval_prod !== false) !== (saved.retrieval_prod !== false))
      continue;
    if ((p.eval_path || "agent") !== (saved.eval_path || "agent")) continue;
    if ((p.context_tier || "20") !== (saved.context_tier || "20")) continue;
    if ((p.retrieval_tier || "20") !== (saved.retrieval_tier || "20")) continue;
    if ((p.l1_max_parallel ?? 1) !== (saved.l1_max_parallel ?? 1)) continue;
    if ((p.retrieval_arm || "free") !== (saved.retrieval_arm || "free"))
      continue;
    if ((p.context_arm || "free") !== (saved.context_arm || "free")) continue;
    return p.id;
  }
  return CUSTOM_PROFILE_ID;
}
export const BENCH_SCENARIO_GROUPS: {
  id: BenchScenarioId;
  label: string;
  hint: string;
  suiteIds: readonly SuiteId[];
}[] = [
  {
    id: "writing",
    label: "写作 writing",
    hint: "资料 RAG / 长文上下文（search_sources 主路径）",
    suiteIds: ["retrieval", "retrieval_zh", "context"],
  },
  {
    id: "agent",
    label: "Agent 编码",
    hint: "SWE-bench · 补丁 / harness resolve",
    suiteIds: ["coding"],
  },
  {
    id: "intel",
    label: "威胁情报 intel",
    hint: "闭环效果臂尚未挂接 · 见 docs/plan/intel-closed-loop-verification.md",
    suiteIds: [],
  },
];

export const SUITE_TO_SCENARIO: Record<SuiteId, BenchScenarioId> = {
  retrieval: "writing",
  retrieval_zh: "writing",
  context: "writing",
  coding: "agent",
};

export const FALLBACK_SUITE_META: Record<
  SuiteId,
  { id: SuiteId; label: string; description: string }
> = {
  retrieval: {
    id: "retrieval",
    label: "检索",
    description: "BEIR · hybrid + BM25",
  },
  retrieval_zh: {
    id: "retrieval_zh",
    label: "中文检索",
    description: "C-MTEB · 同模分图 retrieval_ops_zh",
  },
  context: {
    id: "context",
    label: "上下文",
    description: "LongBench · 三臂",
  },
  coding: {
    id: "coding",
    label: "编码",
    description: "SWE-bench Lite",
  },
};

export function scenarioLabelForSuite(id: string): string {
  const sid = id as SuiteId;
  if ((SUITE_IDS as readonly string[]).includes(sid)) {
    const scen = SUITE_TO_SCENARIO[sid];
    const g = BENCH_SCENARIO_GROUPS.find((x) => x.id === scen);
    return g?.label ?? scen;
  }
  return "其他";
}

export type ApiStyle = "openai" | "anthropic";

export type ProviderPreset = {
  id: string;
  label: string;
  api_style: ApiStyle;
  model: string;
  base_url: string;
  context_window?: string;
};

/** Mainstream chat endpoints for Bench context/coding (not product user profiles). */
export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "anthropic",
    label: "Anthropic",
    api_style: "anthropic",
    model: "claude-sonnet-4-20250514",
    base_url: "https://api.anthropic.com",
    context_window: "200000",
  },
  {
    id: "openai",
    label: "OpenAI",
    api_style: "openai",
    model: "gpt-4o-mini",
    base_url: "https://api.openai.com/v1",
    context_window: "128000",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    api_style: "openai",
    model: "deepseek-v4-flash",
    base_url: "https://api.deepseek.com",
    context_window: "128000",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    api_style: "openai",
    model: "openai/gpt-4o-mini",
    base_url: "https://openrouter.ai/api/v1",
    context_window: "128000",
  },
  {
    id: "moonshot",
    label: "Moonshot",
    api_style: "openai",
    model: "moonshot-v1-128k",
    base_url: "https://api.moonshot.cn/v1",
    context_window: "128000",
  },
  {
    id: "zhipu",
    label: "智谱",
    api_style: "openai",
    model: "glm-4-flash",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    context_window: "128000",
  },
  {
    id: "groq",
    label: "Groq",
    api_style: "openai",
    model: "llama-3.3-70b-versatile",
    base_url: "https://api.groq.com/openai/v1",
    context_window: "128000",
  },
  {
    id: "together",
    label: "Together",
    api_style: "openai",
    model: "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
    base_url: "https://api.together.xyz/v1",
    context_window: "128000",
  },
  {
    id: "ollama",
    label: "Ollama",
    api_style: "openai",
    model: "llama3.2",
    base_url: "http://host.docker.internal:11434/v1",
    context_window: "32768",
  },
];

export function presetById(id: string): ProviderPreset | undefined {
  return PROVIDER_PRESETS.find((p) => p.id === id);
}

export function inferApiStyle(
  provider: string,
  explicit?: string | null,
): ApiStyle {
  if (explicit === "openai" || explicit === "anthropic") return explicit;
  if (provider === "anthropic" || provider === "claude") return "anthropic";
  return "openai";
}

/** Map Ops suite cards → bench worker targets. */
export function suitesToTargets(suites: Iterable<string>): string[] {
  const out: string[] = [];
  for (const s of suites) {
    if (s === "coding") {
      if (!out.includes("coding_infer")) out.push("coding_infer");
    } else if (s === "retrieval" || s === "retrieval_zh" || s === "context") {
      if (!out.includes(s)) out.push(s);
    } else if (s === "cmteb") {
      if (!out.includes("retrieval_zh")) out.push("retrieval_zh");
    } else if (s === "coding_infer" || s === "coding_pull" || s === "pull") {
      // Legacy history rows
      if (s === "coding_pull" || s === "coding_infer") {
        if (!out.includes("coding_infer")) out.push("coding_infer");
      } else if (!out.includes(s)) out.push(s);
    }
  }
  return out;
}

export function suitesFromTargets(targets: Iterable<string>): Set<SuiteId> {
  const suites = new Set<SuiteId>();
  for (const t of targets) {
    if (t === "retrieval") suites.add("retrieval");
    else if (t === "retrieval_zh" || t === "cmteb") suites.add("retrieval_zh");
    else if (t === "context") suites.add("context");
    else if (t === "coding" || t === "coding_infer" || t === "coding_pull") {
      suites.add("coding");
    }
  }
  return suites;
}

export function suitesFromRun(r: {
  targets?: string[];
  official_suite?: string;
  model_meta?: { official_suite?: string; targets?: string[] };
}): SuiteId[] {
  const raw =
    Array.isArray(r.targets) && r.targets.length > 0
      ? r.targets
      : Array.isArray(r.model_meta?.targets) && r.model_meta.targets.length > 0
        ? r.model_meta.targets
        : String(r.official_suite || r.model_meta?.official_suite || "")
            .split("+")
            .map((s) => s.trim())
            .filter(Boolean);
  const suites = suitesFromTargets(raw);
  return SUITE_IDS.filter((id) => suites.has(id));
}

export function suitesLabelZh(suites: Iterable<string>): string {
  const labels: string[] = [];
  for (const s of suites) {
    if (s === "retrieval") labels.push("检索");
    else if (s === "retrieval_zh" || s === "cmteb") labels.push("中文检索");
    else if (s === "context") labels.push("上下文");
    else if (s === "coding" || s === "coding_infer" || s === "coding_pull") {
      labels.push("编码");
    }
  }
  return labels.join(" · ") || "bench";
}

export function runSuitesLabel(r: {
  targets?: string[];
  official_suite?: string;
  model_meta?: { official_suite?: string; targets?: string[] };
}): string {
  return suitesLabelZh(suitesFromRun(r));
}

export function tierFromLimit(
  limit: number | null | undefined,
  kind: "context" | "retrieval",
): string {
  const n = Number(limit || 0);
  if (!Number.isFinite(n) || n <= 0)
    return kind === "context" ? "full" : "full";
  if (kind === "context") {
    if (n >= 40) return "40";
    if (n >= 20) return "20";
    if (n >= 10) return "10";
    return "5";
  }
  if (n >= 50) return "50";
  if (n >= 20) return "20";
  if (n >= 10) return "10";
  return "5";
}
