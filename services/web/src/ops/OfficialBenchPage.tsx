import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  OpsShell,
  opsOfficialPath,
  opsRawPath,
  opsRunPath,
  secretFromOpsPath,
  statusClass,
} from "./OpsShell";

const TURN_ID_IN_LOG = /turn_id=([0-9a-fA-F-]{36})/;

function OfficialLogLine({
  line,
  secret,
}: {
  line: string;
  secret: string;
}) {
  const nodes: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(TURN_ID_IN_LOG.source, "g");
  while ((m = re.exec(line)) !== null) {
    if (m.index > last) nodes.push(line.slice(last, m.index));
    const id = m[1];
    nodes.push(
      <Link
        key={`${id}-${m.index}`}
        to={opsRawPath(secret, id)}
        className="underline decoration-dotted underline-offset-2 text-foreground hover:text-primary"
        title="打开 Raw 快照看逐步 turn_events"
        target="_blank"
        rel="noreferrer"
      >
        turn_id={id}
      </Link>,
    );
    last = m.index + m[0].length;
  }
  if (last < line.length) nodes.push(line.slice(last));
  if (!nodes.length) return <>{line}</>;
  return <>{nodes}</>;
}

type Criterion = {
  id: string;
  official: string;
  title: string;
  metrics: string;
  pass_rule: string;
  notes: string;
};

type TargetMeta = {
  id: string;
  label: string;
  group?: string;
  description: string;
  needs_model?: boolean;
};

type ContextTier = "full" | "40" | "20" | "10" | "5";
type RetrievalTier = "full" | "50" | "20" | "10" | "5";

type Preset = {
  id: string;
  label: string;
  targets: string[];
  coding_tier?: string;
  coding_n_instances?: number | null;
  coding_harness?: boolean;
  coding_checkout_repo?: boolean;
  retrieval_prod?: boolean;
  eval_path?: "agent" | "component";
  context_tier?: ContextTier;
  retrieval_tier?: RetrievalTier;
  l1_max_parallel?: number;
  retrieval_arm?: "free" | "forced";
  context_arm?: "free" | "oracle";
  hint: string;
};

const CUSTOM_PROFILE_ID = "custom";

/** Human labels for the profile parameter form. */
function retrievalTierLabel(t: RetrievalTier): string {
  if (t === "full") return "全量 qrels (~1.3k)";
  return `${t} q/集`;
}

function contextTierLabel(t: ContextTier): string {
  if (t === "full") return "全量 (~120)";
  return String(t);
}

/** Client fallback if meta.presets is old / empty — 一键配置档. */
const L1_RUN_PROFILES: Preset[] = [
  {
    id: "l1_balanced",
    label: "适中（推荐）",
    targets: ["retrieval", "coding"],
    eval_path: "agent",
    coding_tier: "n5",
    coding_harness: false,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "20",
    retrieval_tier: "20",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "L1 m3 · 自由臂 · 检索 20q/集 + 编码 n5 checkout · 冒烟档",
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
    coding_harness: false,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "20",
    retrieval_tier: "20",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "L1 三套自由臂 · 每 task 20 · 冒烟档",
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
    coding_harness: false,
    coding_checkout_repo: true,
    retrieval_prod: true,
    context_tier: "20",
    retrieval_tier: "20",
    l1_max_parallel: 1,
    retrieval_arm: "free",
    context_arm: "free",
    hint: "只要检索 L1 自由臂 · 20q/集",
  },
];

/** Infer which profile chip matches saved run params (legacy prefs without active_profile_id). */
function inferProfileIdFromSaved(saved: {
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
        .filter((t): t is SuiteId => (SUITE_IDS as readonly string[]).includes(t)),
    );
    if (want.size !== suites.size || [...want].some((s) => !suites.has(s))) continue;
    if ((p.coding_tier || "n5") !== (saved.coding_tier || "n5")) continue;
    if ((p.coding_harness === true) !== (saved.coding_harness === true)) continue;
    if ((p.coding_checkout_repo !== false) !== (saved.coding_checkout_repo !== false)) {
      continue;
    }
    if ((p.retrieval_prod !== false) !== (saved.retrieval_prod !== false)) continue;
    if ((p.eval_path || "agent") !== (saved.eval_path || "agent")) continue;
    if ((p.context_tier || "20") !== (saved.context_tier || "20")) continue;
    if ((p.retrieval_tier || "20") !== (saved.retrieval_tier || "20")) continue;
    if ((p.l1_max_parallel ?? 1) !== (saved.l1_max_parallel ?? 1)) continue;
    if ((p.retrieval_arm || "free") !== (saved.retrieval_arm || "free")) continue;
    if ((p.context_arm || "free") !== (saved.context_arm || "free")) continue;
    return p.id;
  }
  return CUSTOM_PROFILE_ID;
}

type CodingTierMeta = { id: string; n_instances: number | null };

type Caps = Record<string, boolean>;

const SUITE_IDS = ["retrieval", "context", "coding"] as const;
type SuiteId = (typeof SUITE_IDS)[number];

type ApiStyle = "openai" | "anthropic";

type ProviderPreset = {
  id: string;
  label: string;
  api_style: ApiStyle;
  model: string;
  base_url: string;
  context_window?: string;
};

/** Mainstream chat endpoints for Bench context/coding (not product user profiles). */
const PROVIDER_PRESETS: ProviderPreset[] = [
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

function presetById(id: string): ProviderPreset | undefined {
  return PROVIDER_PRESETS.find((p) => p.id === id);
}

function inferApiStyle(provider: string, explicit?: string | null): ApiStyle {
  if (explicit === "openai" || explicit === "anthropic") return explicit;
  if (provider === "anthropic" || provider === "claude") return "anthropic";
  return "openai";
}

/** Map Ops suite cards → bench worker targets. */
function suitesToTargets(suites: Iterable<string>): string[] {
  const out: string[] = [];
  for (const s of suites) {
    if (s === "coding") {
      if (!out.includes("coding_infer")) out.push("coding_infer");
    } else if (s === "retrieval" || s === "context") {
      if (!out.includes(s)) out.push(s);
    } else if (
      s === "coding_infer" ||
      s === "coding_pull" ||
      s === "pull"
    ) {
      // Legacy history rows
      if (s === "coding_pull" || s === "coding_infer") {
        if (!out.includes("coding_infer")) out.push("coding_infer");
      } else if (!out.includes(s)) out.push(s);
    }
  }
  return out;
}

function suitesFromRun(r: {
  targets?: string[];
  official_suite?: string;
  model_meta?: { official_suite?: string };
}): SuiteId[] {
  const raw =
    Array.isArray(r.targets) && r.targets.length > 0
      ? r.targets
      : String(r.official_suite || r.model_meta?.official_suite || "")
          .split("+")
          .map((s) => s.trim())
          .filter(Boolean);
  const suites = new Set<SuiteId>();
  for (const t of raw) {
    if (t === "retrieval") suites.add("retrieval");
    else if (t === "context") suites.add("context");
    else if (t === "coding" || t === "coding_infer" || t === "coding_pull") {
      suites.add("coding");
    }
  }
  return SUITE_IDS.filter((id) => suites.has(id));
}

type OfficialRun = {
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
  retrieval_prod?: boolean;
  cancel_requested?: boolean;
  report_html_available?: boolean;
  child_reports?: Array<{ case_id?: string; bench_run_id?: string; report_html?: string }>;
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
    context_dry?: boolean;
    coding_skip_api?: boolean;
    coding_tier?: string;
    coding_n_instances?: number | null;
    coding_harness?: boolean;
    retrieval_prod?: boolean;
    reclaimed?: boolean;
    report_html_available?: boolean;
    child_reports?: Array<{ case_id?: string; bench_run_id?: string; report_html?: string }>;
  };
  source?: string;
  cases?: Array<{
    case_id: string;
    status: string;
    metrics?: Record<string, number>;
    error?: string | null;
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

function isActiveStatus(status?: string): boolean {
  return status === "queued" || status === "running" || status === "cancelling";
}

function targetsFromRun(r: OfficialRun): string[] {
  return suitesToTargets(suitesFromRun(r));
}

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Human duration: 12s · 3m 05s · 1h 02m */
function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m ${String(rem).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return `${h}h ${String(remM).padStart(2, "0")}m`;
}

function elapsedSeconds(
  startedIso: string | null | undefined,
  endedIso: string | null | undefined,
  nowMs: number,
): number | null {
  if (!startedIso) return null;
  const start = Date.parse(startedIso);
  if (!Number.isFinite(start)) return null;
  const end = endedIso ? Date.parse(endedIso) : nowMs;
  if (!Number.isFinite(end)) return null;
  return Math.max(0, (end - start) / 1000);
}

function shortId(id: string): string {
  return id.slice(0, 8);
}

function cleanPhase(raw: string): string {
  return raw.replace(/^\[phase\]\s*/i, "").trim();
}

type DetailProgress = {
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
};

const SUITE_DETAIL_LABEL: Record<string, string> = {
  context: "上下文",
  coding: "编码",
  retrieval: "检索",
};

const SUITE_UNIT: Record<string, string> = {
  retrieval: "查询",
  context: "题",
  coding: "题",
};

function aggregateParts(
  parts: Record<string, { done: number; total: number }> | undefined,
): { done: number; total: number } | null {
  if (!parts) return null;
  const vals = Object.values(parts);
  if (!vals.length) return null;
  return {
    done: vals.reduce((a, p) => a + (Number.isFinite(p.done) ? p.done : 0), 0),
    total: vals.reduce((a, p) => a + (Number.isFinite(p.total) ? p.total : 0), 0),
  };
}

function mergeDetailProgress(
  prev: DetailProgress | undefined,
  next: DetailProgress,
): DetailProgress {
  const parts: Record<string, { done: number; total: number }> = {
    ...(prev?.parts || {}),
  };
  if (next.parts) {
    for (const [k, v] of Object.entries(next.parts)) {
      parts[k] = { ...parts[k], ...v };
    }
  }
  if (
    next.partKey &&
    next.done != null &&
    Number.isFinite(next.done) &&
    next.total != null &&
    Number.isFinite(next.total)
  ) {
    parts[next.partKey] = { done: next.done, total: next.total };
  }

  const summed = aggregateParts(Object.keys(parts).length ? parts : undefined);
  const pct =
    next.pct != null && Number.isFinite(next.pct) ? next.pct : (prev?.pct ?? null);
  const done = summed
    ? summed.done
    : next.done != null && Number.isFinite(next.done)
      ? next.done
      : (prev?.done ?? null);
  const total = summed
    ? summed.total
    : next.total != null && Number.isFinite(next.total)
      ? next.total
      : (prev?.total ?? null);
  const unit = next.unit || prev?.unit || undefined;
  const outPct =
    summed && summed.total > 0
      ? Math.max(0, Math.min(100, Math.round((summed.done / summed.total) * 100)))
      : pct;
  return {
    ...next,
    pct: outPct,
    done,
    total,
    unit,
    parts: Object.keys(parts).length ? parts : undefined,
    partKey: next.partKey || prev?.partKey,
  };
}

function formatSuiteDetails(details: Record<string, DetailProgress>): {
  label: string;
  pct: number | null;
  kind: DetailProgress["kind"];
  done: number | null;
  total: number | null;
  remain: number | null;
  unit: string | null;
  suiteKey: string | null;
} {
  const keys = Object.keys(details);
  if (!keys.length) {
    return {
      label: "尚未开始",
      pct: null,
      kind: "idle",
      done: null,
      total: null,
      remain: null,
      unit: null,
      suiteKey: null,
    };
  }
  const order = ["retrieval", "context", "coding"];
  const sorted = [
    ...order.filter((k) => k in details),
    ...keys.filter((k) => !order.includes(k)).sort(),
  ];
  const label = sorted
    .map((k) => {
      const d = details[k];
      if (k === "_") return d.label;
      const name = SUITE_DETAIL_LABEL[k] || k;
      const bucket =
        d.done != null && d.total != null ? ` ${d.done}/${d.total}` : "";
      return `${name}: ${d.label}${bucket && !d.label.includes(`${d.done}/${d.total}`) ? bucket : ""}`;
    })
    .join(" · ");
  const kind = sorted.some((k) => details[k].kind === "eval")
    ? "eval"
    : sorted.some((k) => details[k].kind === "pull")
      ? "pull"
      : "idle";

  // Active suite = last unfinished among known suite keys; else latest with totals.
  let focus: DetailProgress | null = null;
  let focusKey: string | null = null;
  for (const k of order) {
    const d = details[k];
    if (!d) continue;
    if (d.total != null && Number.isFinite(d.total) && d.total > 0) {
      focus = d;
      focusKey = k;
      if (d.done == null || d.done < d.total) break;
    }
  }
  if (!focus) {
    for (const k of [...sorted].reverse()) {
      const d = details[k];
      if (d.total != null && Number.isFinite(d.total) && d.total > 0) {
        focus = d;
        focusKey = k === "_" ? null : k;
        break;
      }
    }
  }
  const done = focus?.done ?? null;
  const total = focus?.total ?? null;
  const remain =
    done != null && total != null ? Math.max(0, total - done) : null;
  const unit =
    focus?.unit ||
    (focusKey ? SUITE_UNIT[focusKey] : null) ||
    null;
  const pct =
    done != null && total != null && total > 0
      ? Math.max(0, Math.min(100, Math.round((done / total) * 100)))
      : focus?.pct ?? null;

  return { label, pct, kind, done, total, remain, unit, suiteKey: focusKey };
}

function suiteFromL1Token(token: string): string | null {
  const t = token.trim().toLowerCase();
  if (!t) return null;
  if (t.startsWith("swe.") || t === "coding" || t.startsWith("coding.")) {
    return "coding";
  }
  if (t.startsWith("longbench.") || t === "context" || t.startsWith("context.")) {
    return "context";
  }
  if (t.startsWith("beir.") || t === "retrieval" || t.startsWith("retrieval.")) {
    return "retrieval";
  }
  return null;
}

function parseProgressLine(line: string): DetailProgress | null {
  // L1 agent-path live lines (official_agent_path)
  const l1Coding = line.match(/^\[L1\]\s+coding\s+(\d+)\s*\/\s*(\d+)\s+(\S+)/i);
  if (l1Coding) {
    const cur = Number(l1Coding[1]);
    const total = Number(l1Coding[2]);
    const iid = l1Coding[3];
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite: "coding",
      label: `L1 编码 ${cur}/${total || "?"} · ${iid}`,
      pct,
      done: Number.isFinite(cur) ? cur : null,
      total: Number.isFinite(total) ? total : null,
      unit: "题",
    };
  }
  const l1CtxPlan = line.match(
    /^\[L1\]\s+context plan\s+n=(\d+)(?:\s+parallel=(\d+))?/i,
  );
  if (l1CtxPlan) {
    const n = Number(l1CtxPlan[1]);
    const p = l1CtxPlan[2] ? ` · 并行${l1CtxPlan[2]}` : "";
    return {
      kind: "eval",
      suite: "context",
      label: `L1 上下文计划 ${n} 题${p}`,
      pct: 0,
      done: 0,
      total: Number.isFinite(n) ? n : null,
      unit: "题",
    };
  }
  const l1CodePlan = line.match(
    /^\[L1\]\s+coding plan\s+n=(\d+)\s+tier=(\S+)(?:\s+parallel=(\d+))?/i,
  );
  if (l1CodePlan) {
    const n = Number(l1CodePlan[1]);
    return {
      kind: "eval",
      suite: "coding",
      label: `L1 编码计划 ${l1CodePlan[1]} · ${l1CodePlan[2]}${
        l1CodePlan[3] ? ` · 并行${l1CodePlan[3]}` : ""
      }`,
      pct: 0,
      done: 0,
      total: Number.isFinite(n) ? n : null,
      unit: "题",
    };
  }
  const l1RetPlan = line.match(
    /^\[L1\]\s+(\S+)\s+queries plan\s+n=(\d+)(?:\s+\(qrels-only[^)]*\))?(?:\s+parallel=(\d+))?/i,
  );
  if (l1RetPlan) {
    const n = Number(l1RetPlan[2]);
    const ds = l1RetPlan[1];
    return {
      kind: "eval",
      suite: "retrieval",
      label: `L1 检索 ${ds} · ${l1RetPlan[2]} qrels${
        l1RetPlan[3] ? ` · 并行${l1RetPlan[3]}` : ""
      }`,
      pct: 0,
      done: 0,
      total: Number.isFinite(n) ? n : null,
      unit: "查询",
      partKey: ds,
      parts: Number.isFinite(n) ? { [ds]: { done: 0, total: n } } : undefined,
    };
  }
  const l1Ctx = line.match(/^\[L1\]\s+context\s+(\d+)\s*\/\s*(\d+)/i);
  if (l1Ctx) {
    const cur = Number(l1Ctx[1]);
    const total = Number(l1Ctx[2]);
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite: "context",
      label: `L1 上下文 ${cur}/${total || "?"}`,
      pct,
      done: Number.isFinite(cur) ? cur : null,
      total: Number.isFinite(total) ? total : null,
      unit: "题",
    };
  }
  const l1Q = line.match(/^\[L1\]\s+(\S+)\s+queries\s+(\d+)\s*\/\s*(\d+)/i);
  if (l1Q) {
    const ds = l1Q[1];
    const cur = Number(l1Q[2]);
    const total = Number(l1Q[3]);
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite: "retrieval",
      label: `L1 检索 ${ds} · 查询 ${cur}/${total || "?"}`,
      pct,
      done: Number.isFinite(cur) ? cur : null,
      total: Number.isFinite(total) ? total : null,
      unit: "查询",
      partKey: ds,
      parts:
        Number.isFinite(cur) && Number.isFinite(total)
          ? { [ds]: { done: cur, total } }
          : undefined,
    };
  }
  const l1Pull = line.match(/^\[L1\]\s+pull\s+(.+)$/i);
  if (l1Pull) {
    const what = l1Pull[1].trim();
    const suite = /swe/i.test(what)
      ? "coding"
      : /longbench|context/i.test(what)
        ? "context"
        : "retrieval";
    return {
      kind: "pull",
      suite,
      label: `L1 拉取 · ${what}`,
      pct: null,
    };
  }
  const l1Mat = line.match(
    /^\[L1\]\s+materialize\s+(\S+):\s+(\d+)\s*\/\s*(\d+)/i,
  );
  if (l1Mat) {
    const cur = Number(l1Mat[2]);
    const total = Number(l1Mat[3]);
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite: "retrieval",
      label: `L1 物化 ${l1Mat[1]} · ${cur}/${total || "?"}`,
      pct,
    };
  }
  const l1Sync = line.match(/^\[L1\]\s+sync\s+(\S+):\s+(.+)$/i);
  if (l1Sync) {
    const ds = l1Sync[1];
    const rest = l1Sync[2];
    if (/^done\b/i.test(rest)) {
      return {
        kind: "eval",
        suite: "retrieval",
        label: `L1 索引完成 · ${ds}`,
        pct: 100,
      };
    }
    const files = rest.match(/files=(\d+)\s*\/\s*(\d+)/i);
    const chunks = rest.match(/chunks=(\d+)\s*\/\s*(\d+)/i);
    const phase = rest.match(/phase=(\S+)/i)?.[1] || "building";
    const eta = rest.match(/eta=([\d.]+)s/i)?.[1];
    const rate = rest.match(/rate=([\d.]+)\/s/i)?.[1];
    let pct: number | null = null;
    if (chunks) {
      const c = Number(chunks[1]);
      const t = Number(chunks[2]);
      if (t > 0 && Number.isFinite(c)) {
        pct = Math.max(0, Math.min(100, Math.round((c / t) * 100)));
      }
    } else if (files) {
      const c = Number(files[1]);
      const t = Number(files[2]);
      if (t > 0 && Number.isFinite(c)) {
        pct = Math.max(0, Math.min(100, Math.round((c / t) * 100)));
      }
    }
    const bits = [`L1 索引 ${ds}`, phase];
    if (chunks) bits.push(`chunks ${chunks[1]}/${chunks[2]}`);
    else if (files) bits.push(`files ${files[1]}/${files[2]}`);
    if (rate) bits.push(`${rate}/s`);
    if (eta) bits.push(`ETA ${eta}s`);
    return {
      kind: "eval",
      suite: "retrieval",
      label: bits.join(" · "),
      pct,
    };
  }
  if (/^\[L1\]\s+dataset\s+\S+:\s+materialize/i.test(line)) {
    const name = line.match(/^\[L1\]\s+dataset\s+(\S+):/i)?.[1] || "?";
    return {
      kind: "eval",
      suite: "retrieval",
      label: `L1 检索物化/索引 · ${name}`,
      pct: null,
    };
  }
  const l1TurnStart = line.match(/^\[L1\]\s+turn start\s+(\S+)/i);
  if (l1TurnStart) {
    const label = l1TurnStart[1];
    const suite = suiteFromL1Token(label);
    if (suite) {
      return {
        kind: "eval",
        suite,
        label: `L1 Turn 进行中 · ${label}`,
        pct: null,
      };
    }
  }
  const l1TurnDone = line.match(
    /^\[L1\]\s+turn done\s+(\S+)\s+status=(\S+)\s+events=(\d+)\s+(\d+)s/i,
  );
  if (l1TurnDone) {
    const label = l1TurnDone[1];
    const suite = suiteFromL1Token(label);
    if (suite) {
      return {
        kind: "eval",
        suite,
        label: `L1 Turn 结束 · ${l1TurnDone[2]} · ${l1TurnDone[4]}s · ${label}`,
        pct: null,
      };
    }
  }
  const l1Wait = line.match(
    /^\[L1\]\s+(?:…|\.\.\.)\s+waiting\s+(\S+)\s+(\d+)s\s+last=(\S+)/i,
  );
  if (l1Wait) {
    const label = l1Wait[1];
    const suite = suiteFromL1Token(label);
    if (suite) {
      return {
        kind: "eval",
        suite,
        label: `L1 等待 Turn · ${l1Wait[2]}s · last=${l1Wait[3]} · ${label}`,
        pct: null,
      };
    }
  }
  // "[L1] · tool.started read_file · swe.xxx turn_id=..."
  const l1Step = line.match(/^\[L1\]\s+·\s+(\S+)(?:\s+(.+?))?\s+·\s+(\S+)\s+turn_id=/i);
  if (l1Step) {
    const et = l1Step[1];
    const detail = (l1Step[2] || "").trim();
    const label = l1Step[3];
    const suite = suiteFromL1Token(label);
    if (suite) {
      return {
        kind: "eval",
        suite,
        label: `L1 ${et}${detail ? ` ${detail}` : ""} · ${label}`,
        pct: null,
      };
    }
  }
  if (/^\[L1\]\s+coding infer done/i.test(line)) {
    return { kind: "eval", suite: "coding", label: "L1 编码套件结束", pct: 100 };
  }
  if (/^\[L1\]\s+context done/i.test(line)) {
    return { kind: "eval", suite: "context", label: "L1 上下文套件结束", pct: 100 };
  }
  if (/^\[L1\]\s+retrieval done/i.test(line)) {
    return { kind: "eval", suite: "retrieval", label: "L1 检索套件结束", pct: 100 };
  }

  // Context / coding infer lines: "[context] infer — 72/120 hotpotqa arm=full"
  // Dash may be em/en/hyphen; keep tolerant for Ops log replay.
  const infer = line.match(
    /^\[(context|coding)\]\s+infer\s+\D*?(\d+)\s*\/\s*(\d+)\s+(.+)$/i,
  );
  if (infer) {
    const suite = infer[1].toLowerCase();
    const cur = Number(infer[2]);
    const total = Number(infer[3]);
    const rest = infer[4].trim();
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite,
      label: `推理 ${cur}/${total || "?"} · ${rest}`,
      pct,
    };
  }
  if (/^\[(context|coding)\]\s+run_finished/i.test(line)) {
    const suite = line.match(/^\[(context|coding)\]/i)?.[1]?.toLowerCase();
    const failed = /\bfailed\b/i.test(line);
    return {
      kind: "eval",
      suite,
      label: failed ? "套件结束（未达标）" : "套件结束",
      pct: 100,
    };
  }

  const m = line.match(
    /^\[progress\]\s+(pull|eval)\s+(.+)$/i,
  );
  if (!m) return null;
  const kind = m[1].toLowerCase() as "pull" | "eval";
  const rest = m[2];
  const kv: Record<string, string> = {};
  for (const part of rest.split(/\s+/)) {
    const eq = part.indexOf("=");
    if (eq > 0) kv[part.slice(0, eq)] = part.slice(eq + 1);
  }
  if (kind === "pull" && rest.startsWith("plan")) {
    const fileHint = `${kv.file || ""} ${rest}`.toLowerCase();
    const suite = /longbench|multifield|hotpot|narrative/.test(fileHint)
      ? "context"
      : /swe|instance/.test(fileHint)
        ? "coding"
        : "retrieval";
    return {
      kind: "pull",
      suite,
      label: `拉取计划：共 ${kv.total || "?"} 集 · 已缓存 ${kv.cached || "0"} · 待下 ${kv.need || "?"} · 约 ${kv.approx_mib || "?"} MiB`,
      pct: kv.need === "0" ? 100 : 0,
    };
  }
  if (kind === "pull") {
    const pct = kv.pct != null ? Number(kv.pct) : null;
    const size = kv.size_mib ? ` · ${kv.size_mib} MiB` : "";
    const cached = kv.cached === "1" ? "（缓存跳过）" : "";
    const fileHint = `${kv.file || ""}`.toLowerCase();
    const suite = /longbench|multifield|hotpot|narrative|data\.zip/.test(fileHint)
      ? "context"
      : /swe|instance/.test(fileHint)
        ? "coding"
        : "retrieval";
    return {
      kind: "pull",
      suite,
      label: `拉取 ${kv.dataset || "?"} · ${kv.file || ""}${size}${cached}`,
      pct: Number.isFinite(pct as number) ? (pct as number) : null,
    };
  }
  if (rest.startsWith("plan")) {
    return {
      kind: "eval",
      suite: "retrieval",
      label: `评测计划：${kv.datasets || "?"} 集 × ${kv.arms || "?"} 臂 = ${kv.units || "?"} 块`,
      pct: kv.pct != null && Number.isFinite(Number(kv.pct)) ? Number(kv.pct) : 0,
    };
  }
  const pct = kv.pct != null ? Number(kv.pct) : null;
  const q = kv.queries ? ` · 查询 ${kv.queries}` : "";
  const arm = kv.arm ? `/${kv.arm}` : "";
  const unit = kv.unit ? `块 ${kv.unit}` : `集 ${kv.dataset || "?"}`;
  return {
    kind: "eval",
    suite: "retrieval",
    label: `评测 ${unit} · ${kv.name || ""}${arm} · ${kv.stage || ""}${q}`,
    pct: Number.isFinite(pct as number) ? (pct as number) : null,
  };
}

function isEffectEligible(r: OfficialRun): boolean {
  /** Only completed runs; exclude dry / skip_api / reclaimed from effect aggregates. */
  if (String(r.status || "") !== "completed") return false;
  if (r.model_meta?.reclaimed) return false;
  const err = String(r.error || "");
  if (err.includes("reclaimed")) return false;
  const dry = r.context_dry ?? r.model_meta?.context_dry;
  const skip = r.coding_skip_api ?? r.model_meta?.coding_skip_api;
  const targets = targetsFromRun(r);
  if (targets.includes("context") && dry) return false;
  if (targets.includes("coding_infer") && skip) return false;
  // Hash smoke retrieval is not an effect score.
  const prod = r.retrieval_prod ?? r.model_meta?.retrieval_prod;
  if (targets.includes("retrieval") && prod === false && targets.length === 1) return false;
  return true;
}

function runMetrics(r: OfficialRun | null | undefined): Record<string, number> {
  if (!r) return {};
  const m = r.metrics || r.summary?.metrics || {};
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(m)) {
    if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
  }
  // Also flatten case metrics with prefix for comparison richness
  for (const c of r.cases || []) {
    for (const [k, v] of Object.entries(c.metrics || {})) {
      if (typeof v === "number" && Number.isFinite(v)) {
        out[`${c.case_id}.${k}`] = v;
      }
    }
  }
  return out;
}

function median(sorted: number[]): number {
  if (!sorted.length) return Number.NaN;
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

type MetricAgg = {
  key: string;
  n: number;
  min: number;
  median: number;
  mean: number;
  max: number;
  latest: number;
};

function aggregateMetrics(runs: OfficialRun[]): MetricAgg[] {
  const byKey: Record<string, number[]> = {};
  const latestByKey: Record<string, number> = {};
  for (const r of runs) {
    if (!isEffectEligible(r)) continue;
    const m = runMetrics(r);
    if (!Object.keys(m).length) continue;
    for (const [k, v] of Object.entries(m)) {
      (byKey[k] ||= []).push(v);
      // runs is newest-first from list; first write wins as latest
      if (!(k in latestByKey)) latestByKey[k] = v;
    }
  }
  return Object.keys(byKey)
    .sort()
    .map((key) => {
      const vals = byKey[key].slice().sort((a, b) => a - b);
      const sum = vals.reduce((a, b) => a + b, 0);
      return {
        key,
        n: vals.length,
        min: vals[0],
        median: median(vals),
        mean: sum / vals.length,
        max: vals[vals.length - 1],
        latest: latestByKey[key],
      };
    });
}

function MetricBars({ metrics }: { metrics: Record<string, number> }) {
  const entries = Object.entries(metrics);
  if (!entries.length) {
    return (
      <p className="text-sm text-muted-foreground">
        本次尚无数值指标（套件未完成、dry / skip_api，或旧跑次未按套件回写时常见）。
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => {
        const width = Math.max(0, Math.min(100, v > 1 ? v : v * 100));
        return (
          <div key={k}>
            <div className="mb-0.5 flex justify-between gap-2 text-xs">
              <span className="truncate font-mono text-muted-foreground">{k}</span>
              <strong className="shrink-0 tabular-nums">{v.toFixed(4)}</strong>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-foreground/75" style={{ width: `${width}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

class EventSourcePolyfill {
  private controller = new AbortController();
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string, secret: string) {
    void this.start(url, secret);
  }

  private async start(url: string, secret: string) {
    try {
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${secret}`, Accept: "text/event-stream" },
        signal: this.controller.signal,
      });
      if (!resp.ok || !resp.body) {
        this.onerror?.();
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data:"));
          if (line) this.onmessage?.({ data: line.slice(5).trim() });
        }
      }
    } catch {
      if (!this.controller.signal.aborted) this.onerror?.();
    }
  }

  close() {
    this.controller.abort();
  }
}

export function OfficialBenchPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const secret = secretFromOpsPath(pathname);
  const selectedId = pathname.match(/\/official\/([^/]+)\/?$/)?.[1] || "";

  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [targetsMeta, setTargetsMeta] = useState<TargetMeta[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [caps, setCaps] = useState<Caps>({});
  const [selectedSuites, setSelectedSuites] = useState<Set<SuiteId>>(
    () => new Set(["retrieval", "coding"]),
  );
  const [codingTier, setCodingTier] = useState("n5");
  const [codingNInstances, setCodingNInstances] = useState(5);
  const [codingHarness, setCodingHarness] = useState(false);
  const [codingCheckoutRepo, setCodingCheckoutRepo] = useState(true);
  const [retrievalArm, setRetrievalArm] = useState<"free" | "forced">("free");
  const [contextArm, setContextArm] = useState<"free" | "oracle">("free");
  const [codingTierMeta, setCodingTierMeta] = useState<CodingTierMeta[]>([
    { id: "n3", n_instances: 3 },
    { id: "n5", n_instances: 5 },
    { id: "n10", n_instances: 10 },
    { id: "n25", n_instances: 25 },
    { id: "full300", n_instances: 300 },
    { id: "custom", n_instances: null },
  ]);
  const [retrievalProd, setRetrievalProd] = useState(true);
  /** agent = L1 product Turn (default); component = L0 bench worker. */
  const [evalPath, setEvalPath] = useState<"agent" | "component">("agent");
  /** L1 LongBench size tier: full ≈120; others are hard caps. */
  const [contextTier, setContextTier] = useState<ContextTier>("20");
  /** L1 BEIR qrels queries-per-dataset tier. */
  const [retrievalTier, setRetrievalTier] = useState<RetrievalTier>("20");
  /** Concurrent product Turns inside one L1 suite. */
  const [l1Parallel, setL1Parallel] = useState(1);
  const [activeProfileId, setActiveProfileId] = useState("l1_balanced");
  /** Which profile's param form is expanded (click chip again to collapse). */
  const [profileFormOpen, setProfileFormOpen] = useState(true);
  // Empty until user picks a preset or restores real prefs — do not invent deepseek defaults.
  const [modelProvider, setModelProvider] = useState("");
  const [modelApiStyle, setModelApiStyle] = useState<ApiStyle>("openai");
  const [modelName, setModelName] = useState("");
  const [modelBaseUrl, setModelBaseUrl] = useState("");
  const [modelApiKey, setModelApiKey] = useState("");
  const [modelContextWindow, setModelContextWindow] = useState("");
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeMessage, setProbeMessage] = useState<string | null>(null);
  const [probeOk, setProbeOk] = useState<boolean | null>(null);
  const [prefsReady, setPrefsReady] = useState(false);
  /** Last api_key successfully written to localStorage ("" = none saved). */
  const [storedApiKey, setStoredApiKey] = useState("");
  const [apiKeyEditing, setApiKeyEditing] = useState(false);
  const [apiKeySaveFlash, setApiKeySaveFlash] = useState(false);
  const [showCriteria, setShowCriteria] = useState(false);
  const [pagePane, setPagePane] = useState<"run" | "summary">("run");
  const [suiteFilter, setSuiteFilter] = useState<string>("");
  const [runs, setRuns] = useState<OfficialRun[]>([]);
  const [detail, setDetail] = useState<OfficialRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [clearingHistory, setClearingHistory] = useState(false);
  const [historySelectMode, setHistorySelectMode] = useState(false);
  const [checkedRunIds, setCheckedRunIds] = useState<Set<string>>(() => new Set());
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [phaseHint, setPhaseHint] = useState(
    "全过程：① 拉取（已有则跳过）→ ② 评测 → ③ 回归对比上次指标",
  );
  const [suiteDetails, setSuiteDetails] = useState<Record<string, DetailProgress>>({});
  const detailProgress = useMemo(
    () => formatSuiteDetails(suiteDetails),
    [suiteDetails],
  );
  const [tab, setTab] = useState<"overview" | "metrics" | "cases" | "log">("overview");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const logBoxRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSourcePolyfill | null>(null);
  const attachedRunIdRef = useRef<string | null>(null);

  const headers = useMemo(
    () => ({
      Authorization: `Bearer ${secret}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    }),
    [secret],
  );

  // Restore Bench prefs (model + suites + run profile). api_key only if explicitly saved.
  // v1 auto-wrote form defaults (deepseek-chat) — only restore model when v>=2 or key present.
  useEffect(() => {
    try {
      const raw = localStorage.getItem("ops.bench.prefs");
      if (raw) {
        const saved = JSON.parse(raw) as {
          v?: number;
          provider?: string;
          api_style?: string;
          model_name?: string;
          base_url?: string;
          context_window_tokens?: string;
          remember_api_key?: boolean;
          api_key?: string;
          suites?: string[];
          coding_tier?: string;
          coding_n?: number;
          coding_harness?: boolean;
          coding_checkout_repo?: boolean;
          retrieval_prod?: boolean;
          eval_path?: string;
          context_tier?: string;
          retrieval_tier?: string;
          l1_max_parallel?: number;
          retrieval_arm?: string;
          context_arm?: string;
          active_profile_id?: string;
        };
        const storedKey =
          saved.remember_api_key === false ? "" : String(saved.api_key || "");
        const hasKey = Boolean(storedKey);
        const restoreModel = (saved.v ?? 0) >= 2 || hasKey;
        if (restoreModel) {
          if (saved.provider) setModelProvider(saved.provider);
          if (saved.model_name) {
            const migrated =
              saved.provider === "deepseek" &&
              saved.model_name === "deepseek-chat"
                ? "deepseek-v4-flash"
                : saved.model_name;
            setModelName(migrated);
          }
          if (saved.base_url != null) setModelBaseUrl(saved.base_url);
          if (saved.context_window_tokens != null) {
            setModelContextWindow(String(saved.context_window_tokens));
          } else if (
            saved.provider === "deepseek" &&
            (!saved.model_name || saved.model_name === "deepseek-chat")
          ) {
            setModelContextWindow("128000");
          }
          setModelApiStyle(inferApiStyle(saved.provider || "", saved.api_style));
        }
        if (hasKey) {
          setModelApiKey(storedKey);
          setStoredApiKey(storedKey);
          setApiKeyEditing(false);
        } else {
          setApiKeyEditing(true);
        }
        if (Array.isArray(saved.suites) && saved.suites.length) {
          setSelectedSuites(
            new Set(saved.suites.filter((s): s is SuiteId => (SUITE_IDS as readonly string[]).includes(s))),
          );
        }
        if (saved.coding_tier) setCodingTier(saved.coding_tier);
        if (saved.coding_n != null) setCodingNInstances(saved.coding_n);
        if (typeof saved.coding_harness === "boolean") setCodingHarness(saved.coding_harness);
        if (typeof saved.coding_checkout_repo === "boolean") {
          setCodingCheckoutRepo(saved.coding_checkout_repo);
        }
        if (typeof saved.retrieval_prod === "boolean") setRetrievalProd(saved.retrieval_prod);
        if (saved.eval_path === "agent" || saved.eval_path === "component") {
          setEvalPath(saved.eval_path);
        }
        if (saved.context_tier === "10" || saved.context_tier === "20" || saved.context_tier === "full") {
          setContextTier(saved.context_tier);
        }
        if (
          saved.retrieval_tier === "10" ||
          saved.retrieval_tier === "20" ||
          saved.retrieval_tier === "full"
        ) {
          setRetrievalTier(saved.retrieval_tier);
        }
        if (saved.l1_max_parallel != null && Number.isFinite(saved.l1_max_parallel)) {
          setL1Parallel(Number(saved.l1_max_parallel));
        }
        if (saved.retrieval_arm === "free" || saved.retrieval_arm === "forced") {
          setRetrievalArm(saved.retrieval_arm);
        }
        if (saved.context_arm === "free" || saved.context_arm === "oracle") {
          setContextArm(saved.context_arm);
        }
        if (typeof saved.active_profile_id === "string" && saved.active_profile_id) {
          setActiveProfileId(saved.active_profile_id);
        } else if (Array.isArray(saved.suites) && saved.suites.length) {
          setActiveProfileId(inferProfileIdFromSaved(saved));
        }
      } else {
        const old = localStorage.getItem("ops.bench.model");
        if (old) {
          const key = sessionStorage.getItem("ops.bench.model.api_key");
          if (key) {
            const saved = JSON.parse(old) as {
              provider?: string;
              model_name?: string;
              base_url?: string;
              context_window_tokens?: string;
            };
            if (saved.provider) setModelProvider(saved.provider);
            if (saved.model_name) setModelName(saved.model_name);
            if (saved.base_url != null) setModelBaseUrl(saved.base_url);
            if (saved.context_window_tokens != null) {
              setModelContextWindow(String(saved.context_window_tokens));
            }
            setModelApiKey(key);
            setStoredApiKey(key);
            setApiKeyEditing(false);
          } else {
            setApiKeyEditing(true);
          }
        } else {
          setApiKeyEditing(true);
        }
      }
    } catch {
      setApiKeyEditing(true);
    } finally {
      setPrefsReady(true);
    }
  }, []);

  // Persist non-secret prefs; keep previously saved api_key unless save/clear handlers update it.
  useEffect(() => {
    if (!prefsReady) return;
    try {
      let existingKey = "";
      try {
        const raw = localStorage.getItem("ops.bench.prefs");
        if (raw) {
          const prev = JSON.parse(raw) as { api_key?: string; remember_api_key?: boolean };
          if (prev.remember_api_key !== false) existingKey = String(prev.api_key || "");
        }
      } catch {
        /* ignore */
      }
      localStorage.setItem(
        "ops.bench.prefs",
        JSON.stringify({
          v: 3,
          provider: modelProvider,
          api_style: modelApiStyle,
          model_name: modelName,
          base_url: modelBaseUrl,
          context_window_tokens: modelContextWindow,
          api_key: existingKey,
          suites: Array.from(selectedSuites),
          coding_tier: codingTier,
          coding_n: codingNInstances,
          coding_harness: codingHarness,
          coding_checkout_repo: codingCheckoutRepo,
          retrieval_prod: retrievalProd,
          eval_path: evalPath,
          context_tier: contextTier,
          retrieval_tier: retrievalTier,
          l1_max_parallel: l1Parallel,
          retrieval_arm: retrievalArm,
          context_arm: contextArm,
          active_profile_id: activeProfileId,
        }),
      );
    } catch {
      /* ignore */
    }
  }, [
    prefsReady,
    modelProvider,
    modelApiStyle,
    modelName,
    modelBaseUrl,
    modelContextWindow,
    selectedSuites,
    codingTier,
    codingNInstances,
    codingHarness,
    codingCheckoutRepo,
    retrievalProd,
    evalPath,
    contextTier,
    retrievalTier,
    l1Parallel,
    retrievalArm,
    contextArm,
    activeProfileId,
  ]);

  const persistApiKey = useCallback((key: string) => {
    try {
      let base: Record<string, unknown> = { v: 2 };
      try {
        const raw = localStorage.getItem("ops.bench.prefs");
        if (raw) base = { ...JSON.parse(raw), v: 2 };
      } catch {
        /* ignore */
      }
      base.api_key = key;
      delete base.remember_api_key;
      localStorage.setItem("ops.bench.prefs", JSON.stringify(base));
    } catch {
      /* ignore */
    }
    setStoredApiKey(key);
  }, []);

  const saveApiKey = useCallback(() => {
    const key = modelApiKey.trim();
    if (!key) return;
    persistApiKey(key);
    setModelApiKey(key);
    setApiKeyEditing(false);
    setApiKeySaveFlash(true);
    window.setTimeout(() => setApiKeySaveFlash(false), 1500);
  }, [modelApiKey, persistApiKey]);

  const clearApiKey = useCallback(() => {
    persistApiKey("");
    setModelApiKey("");
    setApiKeyEditing(true);
    setApiKeySaveFlash(false);
  }, [persistApiKey]);

  const probeModel = useCallback(async () => {
    const key = modelApiKey.trim();
    const name = modelName.trim();
    const provider = modelProvider.trim() || "custom";
    if (!key || !name) {
      setProbeOk(false);
      setProbeMessage("请先填写 model_name 与 api_key。");
      return;
    }
    setProbeBusy(true);
    setProbeOk(null);
    setProbeMessage("正在从 bench 容器探测…");
    try {
      const cw = Number(modelContextWindow);
      const resp = await fetch("/api/v1/ops/official/model/probe", {
        method: "POST",
        headers,
        body: JSON.stringify({
          provider,
          api_style: inferApiStyle(provider, modelApiStyle),
          model_name: name,
          api_key: key,
          base_url: modelBaseUrl.trim() || undefined,
          context_window_tokens:
            Number.isFinite(cw) && cw >= 1024 ? Math.floor(cw) : undefined,
        }),
      });
      const text = await resp.text();
      let data: {
        ok?: boolean;
        latency_ms?: number;
        preview?: string;
        error?: string;
        endpoint?: string;
        detail?: string;
      } = {};
      try {
        data = JSON.parse(text) as typeof data;
      } catch {
        /* keep */
      }
      if (!resp.ok) {
        setProbeOk(false);
        setProbeMessage(
          data.detail || data.error || text || `HTTP ${resp.status}`,
        );
        return;
      }
      if (data.ok) {
        setProbeOk(true);
        const preview = (data.preview || "").replace(/\s+/g, " ").trim();
        setProbeMessage(
          `联通成功 · ${data.latency_ms ?? "?"}ms` +
            (data.endpoint ? ` · ${data.endpoint}` : "") +
            (preview ? ` · 回复「${preview.slice(0, 40)}」` : ""),
        );
      } else {
        setProbeOk(false);
        setProbeMessage(
          data.error ||
            `联通失败` +
              (data.endpoint ? ` · ${data.endpoint}` : "") +
              (data.latency_ms != null ? ` · ${data.latency_ms}ms` : ""),
        );
      }
    } catch (e) {
      setProbeOk(false);
      setProbeMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setProbeBusy(false);
    }
  }, [
    headers,
    modelApiKey,
    modelApiStyle,
    modelBaseUrl,
    modelContextWindow,
    modelName,
    modelProvider,
  ]);

  const apiKeyDirty = modelApiKey.trim() !== storedApiKey;
  const apiKeyStored = Boolean(storedApiKey);

  const needsLiveModel = useMemo(
    () =>
      selectedSuites.has("context") ||
      selectedSuites.has("coding") ||
      // L1 retrieval drives real Turns → must use Ops 评测模型 (not product Web settings).
      (evalPath === "agent" && selectedSuites.has("retrieval")),
    [selectedSuites, evalPath],
  );

  const applyProviderPreset = (provider: string) => {
    setModelProvider(provider);
    if (!provider) {
      setModelName("");
      setModelBaseUrl("");
      setModelApiStyle("openai");
      return;
    }
    if (provider === "custom") {
      // Keep current fields; user chooses API protocol explicitly.
      return;
    }
    const preset = presetById(provider);
    if (!preset) return;
    setModelApiStyle(preset.api_style);
    setModelName(preset.model);
    setModelBaseUrl(preset.base_url);
    if (preset.context_window && !modelContextWindow) {
      setModelContextWindow(preset.context_window);
    } else if (preset.context_window) {
      setModelContextWindow(preset.context_window);
    }
  };

  const applyRunSnapshot = useCallback((run: OfficialRun, opts?: { logs?: boolean }) => {
    setProgress({
      done: run.progress_done ?? run.summary?.progress_done ?? 0,
      total:
        run.progress_total ??
        run.summary?.progress_total ??
        targetsFromRun(run).length ??
        0,
    });
    if (run.phase_hint || run.current_phase) {
      setPhaseHint(cleanPhase(run.phase_hint || run.current_phase || ""));
    }
    // Rebuild per-suite detail from logs (parallel suites keep independent rows).
    const nextDetails: Record<string, DetailProgress> = {};
    for (const item of run.logs || []) {
      if (String(item.kind || "") !== "log" || !item.message) continue;
      const parsed = parseProgressLine(String(item.message));
      if (!parsed?.suite) continue;
      const prev = nextDetails[parsed.suite];
      // Don't let a late pull line clobber eval/infer for the same suite.
      if (parsed.kind === "pull" && prev?.kind === "eval") continue;
      nextDetails[parsed.suite] = mergeDetailProgress(prev, parsed);
    }
    setSuiteDetails(nextDetails);

    if (opts?.logs === false) return;
    const lines: string[] = [];
    for (const item of run.logs || []) {
      const kind = String(item.kind || "");
      if (kind === "log" && item.message) {
        const msg = String(item.message);
        if (!msg.startsWith("[progress]")) lines.push(msg);
      } else if (kind === "phase" && item.message) {
        setPhaseHint(cleanPhase(String(item.message)));
      } else if (kind === "case_started" && item.case_id) {
        lines.push(`→ ${item.case_id}`);
      } else if (kind === "case_finished" && item.case_id) {
        lines.push(
          `${item.status === "pass" ? "✓" : item.status === "skipped" ? "○" : "✗"} ${item.case_id}`,
        );
      }
    }
    if (lines.length) setLiveLogs(lines.slice(-800));
  }, []);

  const targetEnabled = useCallback(
    (id: string) => {
      if (id === "retrieval") return caps.retrieval !== false && caps.script !== false;
      if (!caps.script && !caps.bench_worker) return false;
      if (id === "coding") {
        return caps.coding_infer !== false || caps.script !== false || caps.bench_worker === true;
      }
      if (caps.datasets === false && (id === "context" || id === "coding")) {
        // Still ok if remote bench has datasets
        if (caps.bench_worker) return true;
        return false;
      }
      return true;
    },
    [caps],
  );

  const loadMeta = useCallback(async () => {
    const resp = await fetch("/api/v1/ops/official/meta", { headers });
    if (resp.status === 401 || resp.status === 403 || resp.status === 404) {
      setError(resp.status === 404 ? "Ops 未启用" : "无效密钥");
      return;
    }
    if (!resp.ok) {
      setError(`meta HTTP ${resp.status}`);
      return;
    }
    const body = (await resp.json()) as {
      criteria: Criterion[];
      targets: TargetMeta[];
      presets?: Preset[];
      capabilities: Caps;
      coding_tiers?: CodingTierMeta[];
      defaults?: {
        coding_tier?: string;
        coding_n_instances?: number | null;
        coding_harness?: boolean;
        retrieval_prod?: boolean;
        eval_path?: "agent" | "component";
        context_tier?: ContextTier;
        retrieval_tier?: RetrievalTier;
        l1_max_parallel?: number;
        targets?: string[];
      };
    };
    setCriteria(body.criteria || []);
    setTargetsMeta(body.targets || []);
    const apiPresets = body.presets || [];
    const merged =
      apiPresets.some((p) => p.id === "l1_balanced" || p.retrieval_tier != null)
        ? apiPresets
        : L1_RUN_PROFILES;
    setPresets(merged);
    setCaps(body.capabilities || {});
    if (body.coding_tiers?.length) setCodingTierMeta(body.coding_tiers);

    // Local prefs win over API defaults. Previously loadMeta always forced
    // l1_balanced + defaults, so refresh after 「自定义」looked like 「适中」again.
    let hasLocalRunPrefs = false;
    let savedProfileId = "";
    try {
      const raw = localStorage.getItem("ops.bench.prefs");
      if (raw) {
        const saved = JSON.parse(raw) as {
          suites?: unknown;
          active_profile_id?: string;
        };
        hasLocalRunPrefs = Array.isArray(saved.suites) && saved.suites.length > 0;
        if (typeof saved.active_profile_id === "string") {
          savedProfileId = saved.active_profile_id;
        }
      }
    } catch {
      /* ignore */
    }

    if (!hasLocalRunPrefs) {
      const d = body.defaults;
      if (d?.coding_tier) setCodingTier(d.coding_tier);
      if (d?.coding_n_instances != null) setCodingNInstances(d.coding_n_instances);
      if (d?.coding_harness !== undefined) setCodingHarness(d.coding_harness);
      if (d?.retrieval_prod !== undefined) setRetrievalProd(d.retrieval_prod);
      if (d?.eval_path === "agent" || d?.eval_path === "component") {
        setEvalPath(d.eval_path);
      }
      if (d?.context_tier) setContextTier(d.context_tier);
      if (d?.retrieval_tier) setRetrievalTier(d.retrieval_tier);
      if (d?.l1_max_parallel != null) setL1Parallel(d.l1_max_parallel);
      if (d?.targets?.length) {
        const suites = new Set<SuiteId>();
        for (const t of d.targets) {
          if (t === "retrieval" || t === "context" || t === "coding") suites.add(t);
        }
        if (suites.size) setSelectedSuites(suites);
      }
      setActiveProfileId(
        merged.some((p) => p.id === "l1_balanced") ? "l1_balanced" : merged[0]?.id || "",
      );
    } else if (savedProfileId) {
      const known =
        savedProfileId === CUSTOM_PROFILE_ID ||
        merged.some((p) => p.id === savedProfileId) ||
        L1_RUN_PROFILES.some((p) => p.id === savedProfileId);
      setActiveProfileId(known ? savedProfileId : CUSTOM_PROFILE_ID);
    } else {
      try {
        const raw = localStorage.getItem("ops.bench.prefs");
        if (raw) setActiveProfileId(inferProfileIdFromSaved(JSON.parse(raw)));
      } catch {
        /* ignore */
      }
    }
    setError(null);
  }, [headers]);

  const loadList = useCallback(async (): Promise<OfficialRun[]> => {
    const resp = await fetch("/api/v1/ops/official/runs?limit=80", { headers });
    if (!resp.ok) return [];
    const body = (await resp.json()) as { runs: OfficialRun[] };
    const list = body.runs || [];
    setRuns(list);
    return list;
  }, [headers]);

  const loadDetail = useCallback(async (): Promise<OfficialRun | null> => {
    if (!selectedId) {
      setDetail(null);
      return null;
    }
    const resp = await fetch(`/api/v1/ops/official/runs/${selectedId}`, { headers });
    if (!resp.ok) return null;
    const body = (await resp.json()) as OfficialRun;
    setDetail(body);
    setProgress({
      done: body.progress_done ?? body.summary?.progress_done ?? 0,
      total:
        body.progress_total ??
        body.summary?.progress_total ??
        targetsFromRun(body).length ??
        0,
    });
    if (body.phase_hint || body.current_phase) {
      setPhaseHint(cleanPhase(body.phase_hint || body.current_phase || ""));
    }
    return body;
  }, [headers, selectedId]);

  const attachLiveStream = useCallback(
    (runId: string, opts?: { resetLogs?: boolean }) => {
      if (attachedRunIdRef.current === runId && esRef.current) {
        setBusy(true);
        return;
      }
      esRef.current?.close();
      attachedRunIdRef.current = runId;
      setBusy(true);
      setError(null);
      if (opts?.resetLogs) {
        setLiveLogs([]);
        setSuiteDetails({});
      }
      const es = new EventSourcePolyfill(
        `/api/v1/ops/official/runs/${runId}/stream`,
        secret,
      );
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as Record<string, unknown>;
          const kind = String(data.kind || "");
          if (kind === "phase") {
            setPhaseHint(cleanPhase(String(data.message || data.phase || "")));
          } else if (kind === "log") {
            const msg = String(data.message || "");
            const parsed = parseProgressLine(msg);
            if (parsed?.suite) {
              setSuiteDetails((prev) => {
                const cur = prev[parsed.suite!];
                if (parsed.kind === "pull" && cur?.kind === "eval") return prev;
                return {
                  ...prev,
                  [parsed.suite!]: mergeDetailProgress(cur, parsed),
                };
              });
            } else if (
              msg.startsWith("[pull]") ||
              msg.startsWith("[L1] pull") ||
              msg.startsWith("[progress] pull")
            ) {
              // Untyped pull chatter still drives the detail strip.
              setSuiteDetails((prev) => ({
                ...prev,
                _: {
                  kind: "pull",
                  label: msg.replace(/^\[(pull|progress|L1)\]\s*/i, "").slice(0, 120),
                  pct: prev._?.pct ?? null,
                },
              }));
            }
            // Keep pull progress % visible in the log pane (eval [progress] stays out).
            if (!msg.startsWith("[progress]") || msg.startsWith("[progress] pull")) {
              setLiveLogs((prev) => [...prev.slice(-800), msg]);
            }
          } else if (kind === "case_started") {
            setLiveLogs((prev) => [...prev, `→ ${data.case_id}`]);
            void loadList();
          } else if (kind === "case_finished") {
            setLiveLogs((prev) => [
              ...prev,
              `${data.status === "pass" ? "✓" : data.status === "skipped" ? "○" : "✗"} ${data.case_id}`,
            ]);
            setProgress((prev) => ({
              done: Number(
                data.progress_done != null ? data.progress_done : prev.done,
              ),
              total: Number(data.progress_total || prev.total || 0),
            }));
            // Optimistic: paint suite metrics as soon as SSE carries them (L1 per-suite).
            const sseMetrics = data.metrics;
            const finishedCaseId = String(data.case_id || "");
            if (
              finishedCaseId &&
              sseMetrics &&
              typeof sseMetrics === "object" &&
              !Array.isArray(sseMetrics)
            ) {
              setDetail((prev) => {
                if (!prev || prev.id !== runId) return prev;
                const nextCases = (prev.cases || []).map((c) =>
                  c.case_id === finishedCaseId
                    ? {
                        ...c,
                        status: String(data.status || c.status),
                        metrics: sseMetrics as Record<string, number>,
                      }
                    : c,
                );
                const pass = nextCases.filter((c) => c.status === "pass").length;
                const fail = nextCases.filter((c) => c.status === "fail").length;
                const skipped = nextCases.filter((c) => c.status === "skipped").length;
                const pending = nextCases.filter(
                  (c) => c.status === "pending" || c.status === "running",
                ).length;
                return {
                  ...prev,
                  cases: nextCases,
                  summary: {
                    ...(prev.summary || {}),
                    total: nextCases.length,
                    pass,
                    fail,
                    skipped,
                    pending,
                    progress_done: Number(data.progress_done || prev.summary?.progress_done || 0),
                    progress_total: Number(
                      data.progress_total || prev.summary?.progress_total || 0,
                    ),
                  },
                };
              });
            }
            void loadDetail();
            void loadList();
          } else if (kind === "run_started") {
            void loadList();
          }
          if (kind === "run_finished") {
            es.close();
            if (attachedRunIdRef.current === runId) attachedRunIdRef.current = null;
            setBusy(false);
            setSuiteDetails((prev) => {
              if (!Object.keys(prev).length) {
                return {
                  _: { kind: "idle", label: "本轮结束", pct: 100 },
                };
              }
              return prev;
            });
            void loadDetail();
            void loadList();
          }
        } catch {
          /* ignore */
        }
      };
      es.onerror = () => {
        es.close();
        if (attachedRunIdRef.current === runId) attachedRunIdRef.current = null;
        void loadDetail().finally(() => setBusy(false));
      };
    },
    [secret, loadDetail, loadList],
  );

  useEffect(() => {
    void loadMeta();
    void (async () => {
      const list = await loadList();
      // Do not auto-navigate into the latest/live run — user picks from 历史.
      // Only reconnect SSE when the URL already points at that live run.
      const live = list.find(
        (r) => isActiveStatus(r.status) && (r.source === "live" || !r.finished_at),
      );
      if (!live || !selectedId || selectedId !== live.id) return;
      applyRunSnapshot(live, { logs: false });
      attachLiveStream(live.id, { resetLogs: true });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount reconnect
  }, [loadMeta, loadList, secret]);

  const liveRun = useMemo(
    () =>
      runs.find(
        (r) => isActiveStatus(r.status) && (r.source === "live" || !r.finished_at),
      ) ?? null,
    [runs],
  );

  useEffect(() => {
    void (async () => {
      const body = await loadDetail();
      if (!body) return;
      if (isActiveStatus(body.status)) {
        applyRunSnapshot(body, { logs: false });
        // SSE replays in-memory history; only clear if this is a fresh attach.
        attachLiveStream(body.id, {
          resetLogs: attachedRunIdRef.current !== body.id,
        });
      } else {
        applyRunSnapshot(body);
        if (attachedRunIdRef.current === body.id) {
          esRef.current?.close();
          attachedRunIdRef.current = null;
          setBusy(false);
        }
      }
    })();
  }, [loadDetail, applyRunSnapshot, attachLiveStream]);

  useEffect(() => {
    const box = logBoxRef.current;
    if (!box) return;
    // Only scroll the log pane — never scrollIntoView (that moves the whole page).
    box.scrollTop = box.scrollHeight;
  }, [liveLogs]);

  useEffect(() => () => esRef.current?.close(), []);

  // Tick wall clock while a run is live so elapsed / ETA update.
  useEffect(() => {
    if (!busy) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [busy]);

  const applyPreset = (p: Preset) => {
    const suites = new Set<SuiteId>();
    for (const t of p.targets) {
      if (t === "retrieval" || t === "context" || t === "coding") suites.add(t);
      else if (t === "coding_infer" || t === "coding_pull") suites.add("coding");
    }
    setSelectedSuites(suites);
    setCodingTier(p.coding_tier || "n5");
    if (p.coding_n_instances != null) setCodingNInstances(p.coding_n_instances);
    setCodingHarness(Boolean(p.coding_harness));
    setCodingCheckoutRepo(p.coding_checkout_repo !== false);
    if (p.retrieval_arm === "free" || p.retrieval_arm === "forced") {
      setRetrievalArm(p.retrieval_arm);
    }
    if (p.context_arm === "free" || p.context_arm === "oracle") {
      setContextArm(p.context_arm);
    }
    setRetrievalProd(p.retrieval_prod !== false);
    if (p.eval_path === "agent" || p.eval_path === "component") {
      setEvalPath(p.eval_path);
    }
    if (p.context_tier) setContextTier(p.context_tier);
    if (p.retrieval_tier) setRetrievalTier(p.retrieval_tier);
    if (p.l1_max_parallel != null) setL1Parallel(p.l1_max_parallel);
    setActiveProfileId(p.id);
    setProfileFormOpen(true);
  };

  const markCustomProfile = () => {
    setActiveProfileId(CUSTOM_PROFILE_ID);
    setProfileFormOpen(true);
  };

  const selectCustomProfile = () => {
    setActiveProfileId(CUSTOM_PROFILE_ID);
    setProfileFormOpen(true);
  };

  const profileButtons = presets.length ? presets : L1_RUN_PROFILES;
  const activeProfileLabel =
    activeProfileId === CUSTOM_PROFILE_ID
      ? "自定义"
      : profileButtons.find((p) => p.id === activeProfileId)?.label || "自定义";
  const activeProfileHint =
    activeProfileId === CUSTOM_PROFILE_ID
      ? "在下方表单改参数；不再绑定预设档。"
      : profileButtons.find((p) => p.id === activeProfileId)?.hint || "";

  const toggleSuite = (id: SuiteId) => {
    if (!targetEnabled(id)) return;
    setSelectedSuites((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const startRun = async (opts?: {
    force?: boolean;
    suites?: SuiteId[];
    coding_tier?: string;
    coding_n_instances?: number | null;
    coding_harness?: boolean;
    retrieval_prod?: boolean;
  }) => {
    const suites = (opts?.suites ?? Array.from(selectedSuites)).filter((s) =>
      targetEnabled(s),
    ) as SuiteId[];
    const apiTargets = suites.map((s) => (s === "coding" ? "coding" : s));
    if (apiTargets.length === 0) return;
    if (busy && !opts?.force) return;
    const tier = opts?.coding_tier ?? codingTier;
    const nInst = opts?.coding_n_instances ?? (tier === "custom" ? codingNInstances : null);
    const harness = opts?.coding_harness ?? codingHarness;
    const prod = opts?.retrieval_prod ?? retrievalProd;
    if (suites.includes("coding") && tier === "custom" && (nInst == null || nInst < 3)) {
      setError("自定义编码档位需要 N ≥ 3（且 ≤ 300）");
      return;
    }
    if (suites.includes("coding") && tier === "full300") {
      const ok = window.confirm(
        "全量 SWE-bench Lite（300 题）耗时长、负载大。确认以 full300 启动？",
      );
      if (!ok) return;
    }
    const needModel =
      suites.includes("context") ||
      suites.includes("coding") ||
      (evalPath === "agent" && suites.includes("retrieval"));
    const hasKey = Boolean(modelApiKey.trim() && modelName.trim() && modelProvider.trim());
    if (needModel && !hasKey) {
      setError(
        evalPath === "agent" && suites.includes("retrieval") && !suites.includes("context") && !suites.includes("coding")
          ? "L1 检索需走真实 Turn：请填写下方评测模型（供应商 / model / api_key）并点保存。"
          : "已选上下文/编码（或 L1 检索）：请填写下方评测模型（供应商 / model / api_key）。",
      );
      return;
    }
    let modelPayload:
      | {
          provider: string;
          api_style: ApiStyle;
          model_name: string;
          api_key: string;
          base_url?: string;
          context_window_tokens?: number;
        }
      | undefined;
    if (needModel && hasKey) {
      const cw = Number(modelContextWindow);
      const provider = modelProvider.trim() || "custom";
      modelPayload = {
        provider,
        api_style: inferApiStyle(provider, modelApiStyle),
        model_name: modelName.trim(),
        api_key: modelApiKey.trim(),
        base_url: modelBaseUrl.trim() || undefined,
        context_window_tokens:
          Number.isFinite(cw) && cw >= 1024 ? Math.floor(cw) : undefined,
      };
    }
    if (opts?.suites) {
      setSelectedSuites(new Set(suites));
      setCodingTier(tier);
      if (nInst != null) setCodingNInstances(nInst);
      setCodingHarness(harness);
      setRetrievalProd(prod);
    }
    setBusy(true);
    setLiveLogs([]);
    setError(null);
    setTab("log");
    try {
      const resp = await fetch("/api/v1/ops/official/runs", {
        method: "POST",
        headers,
        body: JSON.stringify({
          targets: apiTargets,
          context_dry: false,
          coding_skip_api: false,
          coding_tier: tier,
          coding_n_instances: tier === "custom" ? nInst : null,
          coding_harness: harness,
          coding_checkout_repo: codingCheckoutRepo,
          retrieval_prod: prod,
          eval_path: evalPath,
          retrieval_arm: retrievalArm,
          context_arm: contextArm,
          context_limit:
            evalPath === "agent" && contextTier !== "full"
              ? Number(contextTier)
              : 0,
          retrieval_query_limit:
            evalPath === "agent" && retrievalTier !== "full"
              ? Number(retrievalTier)
              : 0,
          l1_max_parallel: evalPath === "agent" ? l1Parallel : 1,
          force: Boolean(opts?.force),
          model: modelPayload ?? null,
        }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        let msg = text || `HTTP ${resp.status}`;
        try {
          const j = JSON.parse(text) as {
            error?: { message?: string };
            detail?: string;
          };
          msg = j.error?.message || j.detail || msg;
        } catch {
          /* keep */
        }
        if (String(msg).includes("official_run_already_active") && !opts?.force) {
          setError(
            "已有 Bench 在跑（或上次未干净结束）。可点右上角「取消」，或点「强制重开」。",
          );
          setBusy(false);
          return;
        }
        throw new Error(msg);
      }
      const created = (await resp.json()) as OfficialRun;
      setProgress({
        done: 0,
        total: created.progress_total || apiTargets.length,
      });
      navigate(opsOfficialPath(secret, created.id));
      attachLiveStream(created.id, { resetLogs: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const stopRun = async (runId?: string) => {
    const id = runId || selectedId;
    if (!id) return;
    setError(null);
    setPhaseHint("正在停止…");
    setSuiteDetails({ _: { kind: "idle", label: "正在停止…", pct: null } });
    const resp = await fetch(`/api/v1/ops/official/runs/${id}/stop`, {
      method: "POST",
      headers,
    });
    if (!resp.ok) {
      const text = await resp.text();
      setError(text || `停止失败 HTTP ${resp.status}`);
    } else {
      // Live SSE may still deliver run_finished; DB-only cancel won't.
      const body = (await resp.json().catch(() => null)) as OfficialRun | null;
      if (body?.phase_hint) {
        setPhaseHint(cleanPhase(body.phase_hint));
      }
      if (body && !isActiveStatus(body.status)) {
        setBusy(false);
        setSuiteDetails({ _: { kind: "idle", label: "已取消", pct: null } });
        setPhaseHint("已停止");
      } else {
        // Force UI out of infinite「正在停止…」even if SSE is wedged.
        window.setTimeout(() => {
          void (async () => {
            const latest = await loadDetail();
            if (!latest || !isActiveStatus(latest.status)) {
              setBusy(false);
              setPhaseHint("已停止");
              setSuiteDetails({ _: { kind: "idle", label: "已取消", pct: null } });
              return;
            }
            setBusy(false);
            setPhaseHint("停止超时 — 可强制重开");
            setSuiteDetails({ _: { kind: "idle", label: "停止超时", pct: null } });
            setError("停止超过约 8s 仍未终态。可刷新或点「强制重开」。");
            await loadList();
          })();
        }, 8000);
      }
    }
    await loadList();
    if (id === selectedId) await loadDetail();
  };

  const deleteHistory = async (opts: {
    ids?: string[];
    before?: string;
    force?: boolean;
    confirmLabel: string;
  }) => {
    if (clearingHistory) return;
    const ok = window.confirm(opts.confirmLabel);
    if (!ok) return;
    setClearingHistory(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/ops/official/runs/delete", {
        method: "POST",
        headers,
        body: JSON.stringify({
          ids: opts.ids ?? [],
          before: opts.before ?? null,
          include_filesystem: true,
          force: Boolean(opts.force),
        }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        let msg = text || `HTTP ${resp.status}`;
        try {
          const j = JSON.parse(text) as {
            detail?: string;
            error?: { message?: string };
          };
          msg = j.error?.message || j.detail || msg;
        } catch {
          /* keep */
        }
        throw new Error(msg);
      }
      const deletedIds = new Set(opts.ids || []);
      const wipeAll = !opts.ids?.length && !opts.before;
      if (wipeAll || (selectedId && deletedIds.has(selectedId))) {
        esRef.current?.close();
        attachedRunIdRef.current = null;
        setBusy(false);
        setDetail(null);
        setLiveLogs([]);
        setProgress({ done: 0, total: 0 });
        setSuiteDetails({});
        if (selectedId) {
          navigate(opsOfficialPath(secret), { replace: true });
        }
      } else if (opts.before && selectedId) {
        const sel = runs.find((r) => r.id === selectedId);
        if (sel?.created_at) {
          const cut = Date.parse(opts.before);
          const created = Date.parse(sel.created_at);
          if (Number.isFinite(cut) && Number.isFinite(created) && created < cut) {
            esRef.current?.close();
            attachedRunIdRef.current = null;
            setBusy(false);
            setDetail(null);
            navigate(opsOfficialPath(secret), { replace: true });
          }
        }
      }
      setCheckedRunIds(new Set());
      if (wipeAll) setHistorySelectMode(false);
      await loadList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setClearingHistory(false);
    }
  };

  const clearHistory = async () => {
    if (runs.length === 0) return;
    const hasActive = runs.some((r) => isActiveStatus(r.status));
    await deleteHistory({
      force: hasActive,
      confirmLabel: hasActive
        ? `清空全部 Bench 历史（约 ${runs.length} 条）？\n含进行中的任务会先强制停止再删。\n保留 BEIR/LongBench 数据缓存。`
        : `清空全部 Bench 历史（约 ${runs.length} 条）？\n会删除数据库记录与报告目录，保留 BEIR/LongBench 数据缓存。`,
    });
  };

  const deleteSelectedHistory = async () => {
    const ids = Array.from(checkedRunIds);
    if (ids.length === 0) return;
    const hasActive = runs.some(
      (r) => checkedRunIds.has(r.id) && isActiveStatus(r.status),
    );
    await deleteHistory({
      ids,
      force: hasActive,
      confirmLabel: `删除选中的 ${ids.length} 条历史？${
        hasActive ? "\n含进行中的会先强制停止。" : ""
      }`,
    });
  };

  const clearHistoryBefore = async (hoursAgo: number, label: string) => {
    const before = new Date(Date.now() - hoursAgo * 3600 * 1000).toISOString();
    const n = runs.filter((r) => {
      if (!r.created_at) return false;
      const t = Date.parse(r.created_at);
      return Number.isFinite(t) && t < Date.parse(before);
    }).length;
    if (n === 0) {
      setError(`没有早于「${label}」的历史可删`);
      return;
    }
    const hasActive = runs.some((r) => {
      if (!isActiveStatus(r.status) || !r.created_at) return false;
      const t = Date.parse(r.created_at);
      return Number.isFinite(t) && t < Date.parse(before);
    });
    await deleteHistory({
      before,
      force: hasActive,
      confirmLabel: `删除「${label}」之前的约 ${n} 条历史？${
        hasActive ? "\n含进行中的会先强制停止。" : ""
      }`,
    });
  };

  const toggleCheckedRun = (id: string) => {
    setCheckedRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const rerunFrom = async (r: OfficialRun) => {
    const suites = suitesFromRun(r).filter((s) => targetEnabled(s));
    if (suites.length === 0) {
      setError("该记录没有可重跑的目标（或当前镜像不支持）。");
      return;
    }
    await startRun({
      force: true,
      suites,
      coding_tier: r.coding_tier ?? r.model_meta?.coding_tier ?? "n25",
      coding_n_instances:
        r.coding_n_instances ?? r.model_meta?.coding_n_instances ?? null,
      coding_harness: r.coding_harness ?? r.model_meta?.coding_harness ?? false,
      retrieval_prod: r.retrieval_prod ?? r.model_meta?.retrieval_prod ?? true,
    });
  };

  const suitePct =
    progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;
  const detailPct =
    detailProgress.pct != null && Number.isFinite(detailProgress.pct)
      ? Math.max(0, Math.min(100, Math.round(detailProgress.pct)))
      : null;
  // Prefer fine-grained bar while a suite is mid-flight (suite bar stuck at 0/N is misleading).
  const barPct =
    busy && detailPct != null
      ? Math.max(4, Math.round(suitePct * 0.35 + detailPct * 0.65))
      : suitePct || (busy ? 4 : 0);

  const suitesRemaining =
    progress.total > 0 ? Math.max(0, progress.total - progress.done) : null;
  const currentSuiteNo =
    progress.total > 0 && busy
      ? Math.min(
          progress.total,
          progress.done + (suitesRemaining && suitesRemaining > 0 ? 1 : 0),
        )
      : null;
  const activeSuiteName = detailProgress.suiteKey
    ? SUITE_DETAIL_LABEL[detailProgress.suiteKey] || detailProgress.suiteKey
    : null;
  // L1 pipeline suites = retrieval / context / coding (at most 3), NOT BEIR datasets / queries.
  const suiteProgressLabel =
    progress.total > 0
      ? busy && suitesRemaining != null && suitesRemaining > 0
        ? `L1套件 ${progress.done}/${progress.total}` +
          (activeSuiteName
            ? ` · 进行中：${activeSuiteName}`
            : ` · 进行中第 ${currentSuiteNo} 套`)
        : `L1套件 ${progress.done}/${progress.total}`
      : null;
  const itemsRemainLabel =
    detailProgress.remain != null && detailProgress.unit
      ? `${activeSuiteName || "套内"} ${detailProgress.done ?? 0}/${detailProgress.total ?? "?"} · 剩 ${detailProgress.remain} ${detailProgress.unit}`
      : null;
  const remainLabel = (() => {
    const parts: string[] = [];
    if (itemsRemainLabel) parts.push(itemsRemainLabel);
    if (suiteProgressLabel) parts.push(suiteProgressLabel);
    return parts.length ? parts.join(" · ") : null;
  })();

  const runStartedAt = detail?.created_at || null;
  const runFinishedAt = busy ? null : detail?.finished_at || null;
  const elapsedSec = elapsedSeconds(runStartedAt, runFinishedAt, nowMs);
  const timingLabel = (() => {
    if (elapsedSec == null) return null;
    if (busy) {
      const rem = remainLabel ? ` · ${remainLabel}` : "";
      return `已用 ${formatDuration(elapsedSec)}${rem}`;
    }
    if (runFinishedAt) return `用时 ${formatDuration(elapsedSec)}`;
    return `已用 ${formatDuration(elapsedSec)}`;
  })();

  const filteredRuns = useMemo(() => {
    if (!suiteFilter) return runs;
    return runs.filter((r) =>
      (r.official_suite || r.model_meta?.official_suite || "").includes(suiteFilter),
    );
  }, [runs, suiteFilter]);

  /** History list keeps all statuses; aggregates only completed (+ effect-eligible). */
  const summaryRuns = useMemo(
    () => filteredRuns.filter((r) => isEffectEligible(r)),
    [filteredRuns],
  );

  const metricAggs = useMemo(() => aggregateMetrics(summaryRuns), [summaryRuns]);
  const scoredRunCount = useMemo(
    () => summaryRuns.filter((r) => Object.keys(runMetrics(r)).length > 0).length,
    [summaryRuns],
  );

  const detailMetrics = runMetrics(detail);

  return (
    <OpsShell
      wide
      secret={secret}
      title="Bench"
      subtitle="BEIR · LongBench · SWE-bench Lite · 指标与过程"
      actions={
        <>
          <div className="flex rounded-md border border-border p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setPagePane("run")}
              className={`rounded px-2.5 py-1 ${
                pagePane === "run" ? "bg-foreground text-background" : "hover:bg-muted"
              }`}
            >
              评测
            </button>
            <button
              type="button"
              onClick={() => setPagePane("summary")}
              className={`rounded px-2.5 py-1 ${
                pagePane === "summary" ? "bg-foreground text-background" : "hover:bg-muted"
              }`}
            >
              指标汇总
            </button>
          </div>
          <button
            type="button"
            onClick={() => setShowCriteria((v) => !v)}
            className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            {showCriteria ? "收起标准" : "评判标准"}
          </button>
          {busy ? (
            <button
              type="button"
              onClick={() => void stopRun()}
              className="rounded-md border border-destructive/40 px-2 py-1 text-xs text-destructive hover:bg-destructive/10"
            >
              取消
            </button>
          ) : null}
          {error?.includes("已有 Bench") ? (
            <button
              type="button"
              onClick={() => void startRun({ force: true })}
              className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
            >
              强制重开
            </button>
          ) : null}
        </>
      }
    >
      {error ? (
        <p className="mb-4 whitespace-pre-wrap rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
          {error}
        </p>
      ) : null}

      {showCriteria ? (
        <section className="mb-5 grid gap-3 md:grid-cols-3">
          {criteria.map((c) => (
            <article key={c.id} className="rounded-lg border border-border bg-card/50 p-3 text-xs">
              <h3 className="font-semibold tracking-tight">{c.title}</h3>
              <p className="mt-0.5 text-muted-foreground">{c.official}</p>
              <p className="mt-2">
                <span className="text-muted-foreground">指标 </span>
                {c.metrics}
              </p>
              <p className="mt-1">
                <span className="text-muted-foreground">判定 </span>
                {c.pass_rule}
              </p>
            </article>
          ))}
        </section>
      ) : null}

      {pagePane === "run" ? (
      <>
      {/* Process legend */}
      <section className="mb-4 rounded-xl border border-border bg-muted/30 px-4 py-3 text-xs">
        <p className="font-semibold text-foreground">你始终该知道在干嘛（每个套件都是这三步）</p>
        <ol className="mt-2 grid gap-2 sm:grid-cols-3">
          <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
            <span className="font-medium">① 拉取 Pull</span>
            <p className="mt-0.5 text-muted-foreground">
              BEIR / LongBench / SWE 题集进缓存；<strong>已有则跳过下载</strong>。慢通常只发生在第一次。
            </p>
          </li>
          <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
            <span className="font-medium">② 评测 Eval</span>
            <p className="mt-0.5 text-muted-foreground">
              跑检索 / 上下文 / 编码，产出 nDCG、retention、patch 率等指标。
            </p>
          </li>
          <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
            <span className="font-medium">③ 回归 Regress</span>
            <p className="mt-0.5 text-muted-foreground">
              「指标汇总」页看多次 <strong>completed</strong> 跑分的最高 / 平均 / 中位；相对上次 Δ 也在检索日志里。
            </p>
          </li>
        </ol>
        <p className="mt-2 text-muted-foreground">
          首次拉 BEIR 走德国 UKP 源，国内慢可开代理；<strong>拉完会缓存</strong>，之后主要是 ②③。
        </p>
      </section>

      {/* Launch strip */}
      <section className="mb-5 rounded-xl border border-border bg-gradient-to-b from-card/80 to-background p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">发起一次 Bench</h2>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy || Array.from(selectedSuites).filter(targetEnabled).length === 0}
              onClick={() => void startRun()}
              className="rounded-md bg-foreground px-4 py-1.5 text-sm text-background disabled:opacity-40"
            >
              {busy ? "运行中…" : "开始"}
            </button>
            {error?.includes("已有 Bench") ? (
              <button
                type="button"
                onClick={() => void startRun({ force: true })}
                className="rounded-md border border-border px-3 py-1.5 text-sm"
              >
                强制重开
              </button>
            ) : null}
          </div>
        </div>

        <p className="mt-2 text-[11px] text-muted-foreground">
          点配置档会套用参数并打开下方表单；再点同一档可收起。改任一字段会切到「自定义」——刷新后仍保留（写在本机 prefs）。
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {profileButtons.map((p) => {
            const on = activeProfileId === p.id;
            return (
              <button
                key={p.id}
                type="button"
                disabled={busy}
                title={p.hint}
                onClick={() => {
                  if (on && profileFormOpen) {
                    setProfileFormOpen(false);
                    return;
                  }
                  applyPreset(p);
                }}
                className={`rounded-full border px-2.5 py-1 text-[11px] disabled:opacity-40 ${
                  on
                    ? "border-foreground/60 bg-foreground text-background"
                    : "border-border hover:bg-muted"
                }`}
              >
                {p.label}
              </button>
            );
          })}
          <button
            type="button"
            disabled={busy}
            title="保留当前参数，打开表单自行修改"
            onClick={() => {
              if (activeProfileId === CUSTOM_PROFILE_ID && profileFormOpen) {
                setProfileFormOpen(false);
                return;
              }
              selectCustomProfile();
            }}
            className={`rounded-full border px-2.5 py-1 text-[11px] disabled:opacity-40 ${
              activeProfileId === CUSTOM_PROFILE_ID
                ? "border-foreground/60 bg-foreground text-background"
                : "border-border border-dashed hover:bg-muted"
            }`}
          >
            自定义
          </button>
        </div>

        {profileFormOpen ? (
          <div className="mt-3 rounded-lg border border-border bg-muted/15 px-3 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-xs font-semibold">
                运行参数 · {activeProfileLabel}
              </h3>
              <button
                type="button"
                className="text-[11px] text-muted-foreground underline-offset-2 hover:underline"
                onClick={() => setProfileFormOpen(false)}
              >
                收起
              </button>
            </div>
            {activeProfileHint ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                {activeProfileHint}
              </p>
            ) : null}

            <dl className="mt-3 grid gap-x-4 gap-y-1.5 text-[11px] sm:grid-cols-2">
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-muted-foreground">评测路径</dt>
                <dd>
                  {evalPath === "agent" ? "L1 agent（主路径）" : "L0 component"}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-muted-foreground">套件</dt>
                <dd>
                  {Array.from(selectedSuites)
                    .map((s) =>
                      s === "retrieval"
                        ? "检索"
                        : s === "context"
                          ? "上下文"
                          : "编码",
                    )
                    .join(" · ") || "（未选）"}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-muted-foreground">检索档位</dt>
                <dd>{retrievalTierLabel(retrievalTier)}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-muted-foreground">上下文档位</dt>
                <dd>{contextTierLabel(contextTier)}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-muted-foreground">编码档位</dt>
                <dd>
                  {selectedSuites.has("coding")
                    ? codingTier === "custom"
                      ? `custom N=${codingNInstances}`
                      : codingTier
                    : "—（未开编码）"}
                  {selectedSuites.has("coding") && codingHarness
                    ? " · harness"
                    : ""}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-muted-foreground">并行 Turn</dt>
                <dd>
                  {evalPath === "agent"
                    ? l1Parallel === 1
                      ? "1（串行）"
                      : String(l1Parallel)
                    : "—（L0 不用）"}
                </dd>
              </div>
            </dl>

            <p className="mt-3 text-[11px] font-medium text-muted-foreground">
              修改表单
            </p>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              {(targetsMeta.length
                ? targetsMeta
                : [
                    {
                      id: "retrieval",
                      label: "检索",
                      description: "BEIR · hybrid + BM25",
                    },
                    {
                      id: "context",
                      label: "上下文",
                      description: "LongBench · 三臂",
                    },
                    {
                      id: "coding",
                      label: "编码",
                      description: "SWE-bench Lite",
                    },
                  ]
              ).map((t) => {
                const id = t.id as SuiteId;
                if (!(SUITE_IDS as readonly string[]).includes(id)) return null;
                const enabled = targetEnabled(id);
                const on = selectedSuites.has(id);
                return (
                  <button
                    key={id}
                    type="button"
                    disabled={!enabled || busy}
                    onClick={() => {
                      markCustomProfile();
                      toggleSuite(id);
                    }}
                    className={`rounded-md border px-3 py-2 text-left text-xs transition-colors ${
                      on && enabled
                        ? "border-foreground/50 bg-background"
                        : "border-border bg-background/60 hover:bg-muted/50"
                    } ${!enabled ? "cursor-not-allowed opacity-45" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{t.label}</span>
                      <span
                        className={`h-2 w-2 rounded-full ${on && enabled ? "bg-foreground" : "bg-border"}`}
                      />
                    </div>
                    <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
                      {t.description}
                    </p>
                  </button>
                );
              })}
            </div>

            <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
              <label className="grid gap-1">
                <span className="text-[11px] text-muted-foreground">评测路径</span>
                <select
                  value={evalPath}
                  disabled={busy}
                  onChange={(e) => {
                    markCustomProfile();
                    setEvalPath(
                      e.target.value === "component" ? "component" : "agent",
                    );
                  }}
                  className="rounded border border-border bg-background px-1.5 py-1"
                >
                  <option value="agent">L1 agent（主路径）</option>
                  <option value="component">L0 component（对照）</option>
                </select>
              </label>
              {evalPath === "agent" ? (
                <>
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      检索档位（qrels/集）
                    </span>
                    <select
                      value={retrievalTier}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setRetrievalTier(e.target.value as RetrievalTier);
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      <option value="full">全量 qrels (~1.3k)</option>
                      <option value="50">50 q/集</option>
                      <option value="20">20 q/集</option>
                      <option value="10">10 q/集</option>
                      <option value="5">5 q/集</option>
                    </select>
                  </label>
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      上下文档位
                    </span>
                    <select
                      value={contextTier}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setContextTier(e.target.value as ContextTier);
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      <option value="full">全量 (~120)</option>
                      <option value="40">40</option>
                      <option value="20">20</option>
                      <option value="10">10</option>
                      <option value="5">5</option>
                    </select>
                  </label>
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      并行 Turn
                    </span>
                    <select
                      value={l1Parallel}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setL1Parallel(Number(e.target.value) || 1);
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      <option value={1}>1（串行）</option>
                      <option value={2}>2</option>
                      <option value={3}>3</option>
                      <option value={4}>4</option>
                    </select>
                  </label>
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      检索臂（m3）
                    </span>
                    <select
                      value={retrievalArm}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setRetrievalArm(
                          e.target.value === "forced" ? "forced" : "free",
                        );
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      <option value="free">free（主栏）</option>
                      <option value="forced">forced（L2 诊断）</option>
                    </select>
                  </label>
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      上下文臂（m3）
                    </span>
                    <select
                      value={contextArm}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setContextArm(
                          e.target.value === "oracle" ? "oracle" : "free",
                        );
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      <option value="free">free（主栏）</option>
                      <option value="oracle">oracle（L2 retention）</option>
                    </select>
                  </label>
                </>
              ) : null}
              {selectedSuites.has("coding") ? (
                <>
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      SWE 档位
                    </span>
                    <select
                      value={codingTier}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setCodingTier(e.target.value);
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      {codingTierMeta.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.id}
                          {t.n_instances != null
                            ? ` (${t.n_instances})`
                            : " (自定义 N)"}
                        </option>
                      ))}
                    </select>
                  </label>
                  {codingTier === "custom" ? (
                    <label className="grid gap-1">
                      <span className="text-[11px] text-muted-foreground">
                        自定义 N
                      </span>
                      <input
                        type="number"
                        min={3}
                        max={300}
                        value={codingNInstances}
                        disabled={busy}
                        onChange={(e) => {
                          markCustomProfile();
                          setCodingNInstances(Number(e.target.value) || 3);
                        }}
                        className="rounded border border-border bg-background px-1.5 py-1"
                      />
                    </label>
                  ) : null}
                  <label
                    className="flex items-end gap-2 pb-1"
                    title="需 Docker + swebench。官方 resolve 分仅此项。"
                  >
                    <input
                      type="checkbox"
                      checked={codingHarness}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setCodingHarness(e.target.checked);
                      }}
                    />
                    <span className="text-[11px] leading-tight">
                      harness resolve
                    </span>
                  </label>
                  <label
                    className="flex items-end gap-2 pb-1"
                    title="A-3：按 base_commit 检出仓库；关闭则仅 problem.md（旧行为）"
                  >
                    <input
                      type="checkbox"
                      checked={codingCheckoutRepo}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setCodingCheckoutRepo(e.target.checked);
                      }}
                    />
                    <span className="text-[11px] leading-tight">
                      checkout repo
                    </span>
                  </label>
                </>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="mt-2 text-[11px] text-muted-foreground">
            参数已收起 — 再点「{activeProfileLabel}」或「自定义」查看表单。
            {activeProfileHint ? ` ${activeProfileHint}` : ""}
          </p>
        )}

        <div
          className={`mt-4 rounded-lg border px-3 py-3 ${
            needsLiveModel
              ? "border-foreground/30 bg-foreground/[0.03]"
              : "border-border/70 bg-muted/20"
          }`}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-xs font-semibold">
              评测模型
              {needsLiveModel ? "（本次运行需要）" : "（L0 仅检索可留空）"}
            </h3>
            <p className="text-[11px] text-muted-foreground">
              {needsLiveModel
                ? "供应商与模型自动记住；api_key 需点「保存」。L1 检索也会下发此模型，不走 Web 用户设置。"
                : "L0 组件检索不调模型；切到 L1 或勾选上下文/编码后需填写"}
            </p>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <label className="grid gap-1 text-[11px]">
              <span className="text-muted-foreground">供应商</span>
              <select
                value={modelProvider}
                disabled={busy || !needsLiveModel}
                onChange={(e) => applyProviderPreset(e.target.value)}
                className="rounded border border-border bg-background px-2 py-1.5 text-xs disabled:opacity-50"
              >
                <option value="">未选择</option>
                {PROVIDER_PRESETS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
                <option value="custom">自定义</option>
              </select>
            </label>
            {modelProvider === "custom" ? (
              <label className="grid gap-1 text-[11px]">
                <span className="text-muted-foreground">API 协议</span>
                <select
                  value={modelApiStyle}
                  disabled={busy || !needsLiveModel}
                  onChange={(e) =>
                    setModelApiStyle(e.target.value as ApiStyle)
                  }
                  className="rounded border border-border bg-background px-2 py-1.5 text-xs disabled:opacity-50"
                >
                  <option value="openai">OpenAI 兼容</option>
                  <option value="anthropic">Anthropic Messages</option>
                </select>
              </label>
            ) : (
              <label className="grid gap-1 text-[11px]">
                <span className="text-muted-foreground">API 协议</span>
                <input
                  value={
                    modelApiStyle === "anthropic"
                      ? "Anthropic Messages"
                      : "OpenAI 兼容"
                  }
                  disabled
                  className="rounded border border-border bg-muted/30 px-2 py-1.5 text-xs text-muted-foreground"
                />
              </label>
            )}
            <label className="grid gap-1 text-[11px]">
              <span className="text-muted-foreground">model_name</span>
              <input
                value={modelName}
                disabled={busy || !needsLiveModel}
                onChange={(e) => setModelName(e.target.value)}
                className="rounded border border-border bg-background px-2 py-1.5 text-xs disabled:opacity-50"
                placeholder={
                  modelApiStyle === "anthropic"
                    ? "claude-sonnet-4-20250514"
                    : "gpt-4o-mini"
                }
              />
            </label>
            <label className="grid gap-1 text-[11px]">
              <span className="text-muted-foreground">base_url</span>
              <input
                value={modelBaseUrl}
                disabled={busy || !needsLiveModel}
                onChange={(e) => setModelBaseUrl(e.target.value)}
                className="rounded border border-border bg-background px-2 py-1.5 text-xs disabled:opacity-50"
                placeholder={
                  modelApiStyle === "anthropic"
                    ? "https://api.anthropic.com"
                    : "https://api.openai.com/v1"
                }
              />
            </label>
            <div className="grid gap-1 text-[11px] sm:col-span-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-muted-foreground">api_key</span>
                <span className="text-[10px] text-muted-foreground">
                  {apiKeySaveFlash
                    ? "已保存"
                    : apiKeyStored && !apiKeyEditing && !apiKeyDirty
                      ? "本机已保存"
                      : apiKeyDirty
                        ? "未保存更改"
                        : "未保存"}
                </span>
              </div>
              {apiKeyStored && !apiKeyEditing ? (
                <div className="flex flex-wrap items-center gap-2">
                  <div className="min-w-0 flex-1 rounded border border-border bg-muted/30 px-2 py-1.5 font-mono text-xs tracking-wide text-muted-foreground">
                    {"•".repeat(Math.min(12, Math.max(8, storedApiKey.length - 4)))}
                    {storedApiKey.slice(-4)}
                  </div>
                  <button
                    type="button"
                    disabled={busy || !needsLiveModel}
                    onClick={() => {
                      setModelApiKey(storedApiKey);
                      setApiKeyEditing(true);
                    }}
                    className="rounded border border-border px-2 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    disabled={busy || !needsLiveModel}
                    onClick={clearApiKey}
                    className="rounded border border-border px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
                  >
                    清除
                  </button>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="password"
                    value={modelApiKey}
                    disabled={busy || !needsLiveModel}
                    onChange={(e) => setModelApiKey(e.target.value)}
                    className="min-w-0 flex-1 rounded border border-border bg-background px-2 py-1.5 text-xs disabled:opacity-50"
                    placeholder="评测专用 key（不写产品用户设置）"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    disabled={busy || !needsLiveModel || !modelApiKey.trim()}
                    onClick={saveApiKey}
                    className="rounded border border-border bg-foreground px-2.5 py-1.5 text-xs text-background disabled:opacity-40"
                  >
                    保存
                  </button>
                  {apiKeyStored ? (
                    <button
                      type="button"
                      disabled={busy || !needsLiveModel}
                      onClick={() => {
                        setModelApiKey(storedApiKey);
                        setApiKeyEditing(false);
                      }}
                      className="rounded border border-border px-2 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
                    >
                      取消
                    </button>
                  ) : null}
                </div>
              )}
            </div>
            <label className="grid gap-1 text-[11px]">
              <span className="text-muted-foreground">上下文窗口 tokens（可选）</span>
              <input
                type="number"
                min={1024}
                value={modelContextWindow}
                disabled={busy || !needsLiveModel}
                onChange={(e) => setModelContextWindow(e.target.value)}
                className="rounded border border-border bg-background px-2 py-1.5 text-xs disabled:opacity-50"
                placeholder="如 128000"
              />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={
                busy ||
                probeBusy ||
                !modelApiKey.trim() ||
                !modelName.trim() ||
                !modelProvider.trim()
              }
              onClick={() => void probeModel()}
              className="rounded border border-border bg-background px-2.5 py-1.5 text-xs hover:bg-muted disabled:opacity-40"
            >
              {probeBusy ? "探测中…" : "测试联通"}
            </button>
            <span className="text-[10px] text-muted-foreground">
              从 bench 容器出站探测（与正式评测同路径）
            </span>
            {probeMessage ? (
              <p
                className={`w-full text-[11px] ${
                  probeOk === true
                    ? "text-emerald-700 dark:text-emerald-400"
                    : probeOk === false
                      ? "text-red-700 dark:text-red-400"
                      : "text-muted-foreground"
                }`}
              >
                {probeMessage}
              </p>
            ) : null}
          </div>
        </div>

        {(busy || liveLogs.length > 0) && (
          <div className="mt-4 space-y-2">
            <div className="rounded-md border border-border/80 bg-background/80 px-3 py-2 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  <span className="text-muted-foreground">当前阶段 · </span>
                  <span className="font-medium whitespace-pre-wrap">{phaseHint}</span>
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  {timingLabel ? (
                    <span className="tabular-nums text-muted-foreground">{timingLabel}</span>
                  ) : null}
                  {busy ? (
                    <span className="rounded bg-foreground/10 px-1.5 py-0.5 text-[10px] tabular-nums">
                      直播中
                    </span>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">已结束 · 过程日志保留</span>
                  )}
                </div>
              </div>
            </div>
            <div className="rounded-md border border-border/80 bg-background/60 px-3 py-2 text-xs">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span>
                  <span className="text-muted-foreground">明细 · </span>
                  <span className="font-medium">
                    {busy && detailProgress.kind === "idle"
                      ? "拉取中 / 等待进度…"
                      : detailProgress.label}
                  </span>
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {detailProgress.done != null && detailProgress.total != null
                    ? `${detailProgress.done}/${detailProgress.total}` +
                      (detailProgress.remain != null && detailProgress.unit
                        ? ` · 剩 ${detailProgress.remain} ${detailProgress.unit}`
                        : "")
                    : detailPct != null
                      ? `${detailPct}%`
                      : "—"}
                </span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-foreground/70 transition-[width] duration-200"
                  style={{ width: `${detailPct != null ? detailPct : busy ? 8 : 0}%` }}
                />
              </div>
            </div>
            <div className="flex justify-between text-[11px] text-muted-foreground">
              <span>
                {suiteProgressLabel ||
                  `L1套件 ${progress.done}/${progress.total || "—"}`}
                <span className="text-muted-foreground/80">
                  {" "}
                  （检索/上下文/编码，最多 3 套；与 BEIR 三数据集不是同一层）
                </span>
              </span>
              <span className="tabular-nums">
                {busy && itemsRemainLabel
                  ? itemsRemainLabel
                  : busy && suiteProgressLabel
                    ? suiteProgressLabel
                    : progress.total
                      ? `${suitePct}%`
                      : "—"}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-foreground/80 transition-[width] duration-300"
                style={{ width: `${barPct}%` }}
              />
            </div>
            <div
              ref={logBoxRef}
              className="max-h-72 overflow-y-auto overscroll-contain rounded-md border border-border/80 bg-muted/40 p-2 font-mono text-[11px] leading-relaxed"
            >
              {liveLogs.length === 0 ? (
                <p className="text-muted-foreground">
                  {busy
                    ? "等待拉取日志…（L1 会先打 [L1] pull … starting，随后 [pull] / [progress] pull）"
                    : "日志：L1 会打 pull → turn start / tool·retrieval 步骤 / 心跳；点 turn_id 打开 Raw 逐步。"}
                </p>
              ) : (
                liveLogs.map((line, i) => (
                  <div
                    key={`${i}-${line.slice(0, 24)}`}
                    className={
                      line.includes("[phase]") ||
                      line.startsWith("[pull]") ||
                      line.startsWith("[progress] pull") ||
                      line.startsWith("[L1] pull") ||
                      line.startsWith("[L1] turn ")
                        ? "font-semibold text-foreground"
                        : line.startsWith("[L1] ·") || line.startsWith("[L1] …")
                          ? "text-muted-foreground"
                          : undefined
                    }
                  >
                    <OfficialLogLine line={line} secret={secret} />
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </section>

      {liveRun && liveRun.id !== selectedId ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
          <span>
            有进行中的跑次{" "}
            <span className="font-mono">{shortId(liveRun.id)}</span>
            {" · "}
            {liveRun.official_suite || liveRun.model_meta?.official_suite || "bench"}
            （不会自动打开，需手动进入）
          </span>
          <button
            type="button"
            className="rounded-md border border-border bg-background px-2.5 py-1 hover:bg-muted"
            onClick={() => navigate(opsOfficialPath(secret, liveRun.id))}
          >
            打开进行中
          </button>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        {/* History table */}
        <aside className="rounded-xl border border-border">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
            <h2 className="text-sm font-semibold">历史 ({filteredRuns.length})</h2>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="text-[11px] text-muted-foreground underline disabled:opacity-40"
                disabled={runs.length === 0}
                onClick={() => {
                  setHistorySelectMode((v) => {
                    if (v) setCheckedRunIds(new Set());
                    return !v;
                  });
                }}
              >
                {historySelectMode ? "取消多选" : "多选"}
              </button>
              {historySelectMode ? (
                <>
                  <button
                    type="button"
                    className="text-[11px] text-muted-foreground underline disabled:opacity-40"
                    disabled={filteredRuns.length === 0}
                    onClick={() => {
                      const allVisible = filteredRuns.every((r) =>
                        checkedRunIds.has(r.id),
                      );
                      if (allVisible) {
                        setCheckedRunIds(new Set());
                      } else {
                        setCheckedRunIds(new Set(filteredRuns.map((r) => r.id)));
                      }
                    }}
                  >
                    {filteredRuns.every((r) => checkedRunIds.has(r.id)) &&
                    filteredRuns.length > 0
                      ? "取消全选"
                      : "全选"}
                  </button>
                  <button
                    type="button"
                    className="text-[11px] text-destructive underline disabled:opacity-40"
                    disabled={clearingHistory || checkedRunIds.size === 0}
                    onClick={() => void deleteSelectedHistory()}
                  >
                    {clearingHistory ? "删除中…" : `删除选中(${checkedRunIds.size})`}
                  </button>
                </>
              ) : (
                <>
                  <label className="text-[11px] text-muted-foreground">
                    按时间
                    <select
                      className="ml-1 rounded border border-border bg-background px-1 py-0.5 text-[11px]"
                      defaultValue=""
                      disabled={clearingHistory || runs.length === 0}
                      onChange={(e) => {
                        const v = e.target.value;
                        e.target.value = "";
                        if (v === "all") void clearHistory();
                        else if (v === "1h")
                          void clearHistoryBefore(1, "1 小时前");
                        else if (v === "24h")
                          void clearHistoryBefore(24, "1 天前");
                        else if (v === "7d")
                          void clearHistoryBefore(24 * 7, "7 天前");
                        else if (v === "30d")
                          void clearHistoryBefore(24 * 30, "30 天前");
                      }}
                    >
                      <option value="" disabled>
                        清除…
                      </option>
                      <option value="1h">早于 1 小时</option>
                      <option value="24h">早于 1 天</option>
                      <option value="7d">早于 7 天</option>
                      <option value="30d">早于 30 天</option>
                      <option value="all">全部清空</option>
                    </select>
                  </label>
                </>
              )}
              <button
                type="button"
                className="text-[11px] text-muted-foreground underline"
                onClick={() => {
                  void loadList();
                  if (selectedId) void loadDetail();
                }}
              >
                刷新
              </button>
            </div>
          </div>
          <div className="max-h-[32rem] overflow-y-auto">
            {filteredRuns.length === 0 ? (
              <p className="p-3 text-xs text-muted-foreground">暂无记录。</p>
            ) : (
              <ul>
                {filteredRuns.map((r) => {
                  const active = selectedId === r.id;
                  const checked = checkedRunIds.has(r.id);
                  const m = runMetrics(r);
                  const headline =
                    m.ndcg_at_10 ??
                    m.retention_vs_full_f1 ??
                    m.patch_rate ??
                    m.n_instances;
                  const durSec = elapsedSeconds(
                    r.created_at,
                    isActiveStatus(r.status) ? null : r.finished_at,
                    nowMs,
                  );
                  return (
                    <li key={r.id} className="border-b border-border/70 last:border-0">
                      <div
                        className={`flex items-start gap-2 px-3 py-2.5 text-xs ${
                          active ? "bg-muted" : "hover:bg-muted/60"
                        }`}
                      >
                        {historySelectMode ? (
                          <input
                            type="checkbox"
                            className="mt-1"
                            checked={checked}
                            aria-label={`选择 ${shortId(r.id)}`}
                            onChange={() => toggleCheckedRun(r.id)}
                          />
                        ) : null}
                        <button
                          type="button"
                          className="min-w-0 flex-1 text-left"
                          onClick={() => {
                            if (historySelectMode) {
                              toggleCheckedRun(r.id);
                              return;
                            }
                            navigate(opsOfficialPath(secret, r.id));
                          }}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">
                              {r.official_suite ||
                                r.model_meta?.official_suite ||
                                "bench"}
                            </span>
                            <span className={statusClass(r.status)}>{r.status}</span>
                          </div>
                          <div className="mt-0.5 flex justify-between gap-2 text-[11px] text-muted-foreground">
                            <span>{formatTime(r.created_at)}</span>
                            {durSec != null ? (
                              <span className="tabular-nums shrink-0">
                                {isActiveStatus(r.status) ? "已用 " : ""}
                                {formatDuration(durSec)}
                              </span>
                            ) : null}
                          </div>
                          <div className="mt-1 flex justify-between font-mono text-[10px] text-muted-foreground">
                            <span>{shortId(r.id)}</span>
                            <span>
                              {typeof headline === "number"
                                ? headline.toFixed(3)
                                : `${r.summary?.pass ?? 0}/${r.summary?.total ?? 0}`}
                            </span>
                          </div>
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        {/* Detail */}
        <div className="rounded-xl border border-border p-4">
          {!selectedId ? (
            <p className="text-sm text-muted-foreground">
              从左侧历史手动选一次 run 查看详情。进入评测台不会自动打开最新结果。
            </p>
          ) : !detail ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (
            <div className="space-y-4">
              <header>
                <h2 className="text-lg font-semibold tracking-tight">
                  {detail.title || detail.model_meta?.title || detail.id}
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  <span className={statusClass(detail.status)}>{detail.status}</span>
                  {" · "}
                  {formatTime(detail.created_at)} → {formatTime(detail.finished_at)}
                  {elapsedSec != null ? (
                    <>
                      {" · "}
                      <span className="tabular-nums">
                        {busy ? "已用" : "用时"} {formatDuration(elapsedSec)}
                        {busy && remainLabel ? ` · ${remainLabel}` : ""}
                      </span>
                    </>
                  ) : null}
                  {" · "}
                  pass {detail.summary?.pass ?? 0}/{detail.summary?.total ?? 0}
                </p>
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <button
                    type="button"
                    className="rounded-md border border-border px-2 py-1 hover:bg-muted"
                    disabled={!targetsFromRun(detail).some(targetEnabled)}
                    title="按相同目标强制重跑（会停掉当前活动轮）"
                    onClick={() => void rerunFrom(detail)}
                  >
                    重跑
                  </button>
                  <Link
                    className="rounded-md border border-border px-2 py-1 hover:bg-muted"
                    to={opsRunPath(secret, detail.id)}
                  >
                    通用 Run 页
                  </Link>
                </div>
                {detail.error ? (
                  <p className="mt-2 text-sm text-destructive">{detail.error}</p>
                ) : null}
              </header>

              <div className="flex flex-wrap gap-1.5 text-xs">
                {(["overview", "metrics", "cases", "log"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setTab(t)}
                    className={`rounded-md border px-2.5 py-1 ${
                      tab === t ? "border-foreground/40 bg-muted" : "border-border"
                    }`}
                  >
                    {t === "overview"
                      ? "总览"
                      : t === "metrics"
                        ? "指标"
                        : t === "cases"
                          ? "步骤"
                          : "日志"}
                  </button>
                ))}
              </div>

              {tab === "overview" ? (
                <div className="grid gap-3 sm:grid-cols-4">
                  {(
                    [
                      ["total", detail.summary?.total],
                      ["pass", detail.summary?.pass],
                      ["fail", detail.summary?.fail],
                      ["skipped", detail.summary?.skipped],
                    ] as const
                  ).map(([label, val]) => (
                    <div key={label} className="rounded-lg bg-muted/40 px-3 py-2 text-center">
                      <div className="text-[11px] text-muted-foreground">{label}</div>
                      <div className="text-xl font-semibold tabular-nums">{val ?? 0}</div>
                    </div>
                  ))}
                  <p className="sm:col-span-4 text-xs text-muted-foreground">
                    单次指标见「指标」页签；跨跑次汇总见顶栏「指标汇总」（仅 completed）。
                  </p>
                </div>
              ) : null}

              {tab === "metrics" ? <MetricBars metrics={detailMetrics} /> : null}

              {tab === "cases" ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-border text-muted-foreground">
                      <tr>
                        <th className="py-2 pr-2">步骤</th>
                        <th className="py-2 pr-2">状态</th>
                        <th className="py-2">指标</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.cases || []).map((c) => (
                        <tr key={c.case_id} className="border-b border-border/60">
                          <td className="py-1.5 pr-2 font-mono">{c.case_id}</td>
                          <td className={`py-1.5 pr-2 ${statusClass(c.status)}`}>{c.status}</td>
                          <td className="py-1.5 font-mono text-[10px]">
                            {JSON.stringify(c.metrics || {})}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              {tab === "log" ? (
                <ol className="max-h-[28rem] space-y-2 overflow-y-auto text-xs">
                  {(detail.logs || []).map((item, i) => (
                    <li key={`${item.at}-${i}`} className="border-b border-border/50 pb-2">
                      <span className="text-muted-foreground">{formatTime(item.at)}</span>{" "}
                      <span className="rounded-full border border-border px-1.5 text-[10px] uppercase">
                        {item.kind || "log"}
                      </span>
                      <div className="mt-0.5 whitespace-pre-wrap font-mono text-[11px]">
                        {item.message}
                      </div>
                    </li>
                  ))}
                </ol>
              ) : null}
            </div>
          )}
        </div>
      </div>
      </>
      ) : (
      <section className="mb-5 rounded-xl border border-border p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">指标汇总</h2>
            <p className="text-[11px] text-muted-foreground">
              仅统计 <strong>completed</strong>；已排除 running / cancelled / dry / skip_api / reclaimed / 仅 hash 冒烟
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              n · 最低 · 中位 · 平均 · 最高 · 最近一次。
              {scoredRunCount > 0 ? ` 当前 ${scoredRunCount} 次 completed 计入。` : ""}
            </p>
          </div>
          <label className="flex items-center gap-1.5 text-xs">
            筛选
            <select
              className="rounded-md border border-border bg-background px-2 py-1"
              value={suiteFilter}
              onChange={(e) => setSuiteFilter(e.target.value)}
            >
              <option value="">全部套件</option>
              <option value="retrieval">含 retrieval</option>
              <option value="context">含 context</option>
              <option value="coding">含 coding</option>
            </select>
          </label>
        </div>

        {metricAggs.length === 0 ? (
          <p className="mt-4 text-xs text-muted-foreground">
            还没有可汇总的 completed 跑次。跑完整场并成功结束后，指标会出现在这里。
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="border-b border-border py-2 pr-2 font-medium">指标</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">n</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">最低</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">中位</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">平均</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">最高</th>
                  <th className="border-b border-border py-2 font-medium">最近</th>
                </tr>
              </thead>
              <tbody>
                {metricAggs.map((row) => (
                  <tr key={row.key} className="border-b border-border/60">
                    <td className="py-1.5 pr-2 font-mono text-[11px]">{row.key}</td>
                    <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">{row.n}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{row.min.toFixed(4)}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{row.median.toFixed(4)}</td>
                    <td className="py-1.5 pr-2 tabular-nums font-medium">{row.mean.toFixed(4)}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{row.max.toFixed(4)}</td>
                    <td className="py-1.5 tabular-nums text-muted-foreground">
                      {row.latest.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      )}
    </OpsShell>
  );
}
