/** Plan suggest complexity scoring (docs/26). Suggest only — never auto-enter. */

import weightsConfig from "../../../../../packages/contracts/plan_suggest/weights.json";

export type ScenarioIdForSuggest = "writing" | "agent" | "interview";

export type PlanSuggestDecision = {
  suggest: boolean;
  score: number;
  reasons: string[];
  signals: string[];
};

export type PlanSuggestOptions = {
  scenarioId?: ScenarioIdForSuggest | string | null;
  /** Session cooldown after dismiss (docs/26 PS3). */
  cooldownActive?: boolean;
};

type WeightsFile = {
  cooldown_ms?: number;
  abs_min_len?: number;
  soft_min_len?: number;
  scores?: Record<string, number>;
  threshold?: Record<string, number>;
  high_risk_tokens?: string[];
  reasons?: Record<string, string>;
};

const cfg = weightsConfig as WeightsFile;
const SCORES = cfg.scores ?? {};
const THRESHOLD = cfg.threshold ?? {};
const REASON = cfg.reasons ?? {};
const HIGH_RISK_TOKENS = cfg.high_risk_tokens ?? [];

export const PLAN_SUGGEST_COOLDOWN_MS = cfg.cooldown_ms ?? 30 * 60 * 1000;
const ABS_MIN_LEN = cfg.abs_min_len ?? 8;
const SOFT_MIN_LEN = cfg.soft_min_len ?? 24;

const PLAN_PREFIX = "【Plan 模式】";
const EXECUTE_PREFIX = "【执行计划】";

const NUMBERED_GOAL = /^\s*(?:\d+[\.\)、]|[-*•]\s+\S)/gm;
const GOAL_JOIN =
  /(?:然后|接着|并且|同时|另外|还要|此外|and then|also|finally)\s*/gi;
const PATH_AT = /@([\w./-]+\.(?:md|txt|py|ts|tsx|json|yaml|yml)|[\w./-]+)/g;
const CHAPTER_REF = /第\s*[0-9一二三四五六七八九十百零两]+\s*章/g;

const EXPLICIT_PLAN =
  /先规划|先做计划|给个方案|先列步骤|分步(?:做|完成|实现)?|make a plan|plan first|before (?:we |you )?(?:start|begin|implement)/i;

const CONTINUE_ONLY =
  /^(?:继续|接着写|往下写|续写|再顺一下|继续写|continue)\s*[。.!！]?$/i;

const CONTINUE_LOOSE = /(?:继续|接着写|往下写|续写|再顺一下)/;
const MICRO =
  /语气|错字|错别字|标点|改一句|\btypo\b|\bfix the typo\b/i;

function countMatches(re: RegExp, text: string): number {
  const flags = re.flags.includes("g") ? re.flags : `${re.flags}g`;
  return [...text.matchAll(new RegExp(re.source, flags))].length;
}

function scoreOf(key: string, fallback: number): number {
  const v = SCORES[key];
  return typeof v === "number" ? v : fallback;
}

export function planSuggestThreshold(scenarioId?: string | null): number {
  const key = String(scenarioId ?? "writing").trim().toLowerCase();
  return THRESHOLD[key] ?? THRESHOLD.default ?? 4;
}

export function isPlanSuggestCooldownActive(
  dismissedAt: number | null | undefined,
  now: number = Date.now(),
): boolean {
  if (dismissedAt == null || !Number.isFinite(dismissedAt)) return false;
  return now - dismissedAt < PLAN_SUGGEST_COOLDOWN_MS;
}

export function planSuggestStorageKey(sessionId: string | null): string {
  return `plan-suggest-cooldown:${sessionId ?? "local"}`;
}

export function readPlanSuggestDismissedAt(
  sessionId: string | null,
): number | null {
  if (typeof sessionStorage === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(planSuggestStorageKey(sessionId));
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

export function writePlanSuggestDismissedAt(
  sessionId: string | null,
  at: number,
): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(planSuggestStorageKey(sessionId), String(at));
  } catch {
    /* ignore quota / private mode */
  }
}

export function clearPlanSuggestDismissedAt(sessionId: string | null): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.removeItem(planSuggestStorageKey(sessionId));
  } catch {
    /* ignore */
  }
}

/**
 * Deterministic complexity score for Plan suggest bar / soft plan_hint.
 * Never sets plan_phase; never forces tools (docs/26).
 */
export function evaluatePlanSuggest(
  message: string,
  opts?: PlanSuggestOptions,
): PlanSuggestDecision {
  const text = message.trim();
  const signals: string[] = [];
  const reasons: string[] = [];
  let score = 0;

  const push = (id: string, delta: number) => {
    signals.push(id);
    score += delta;
    const reason = REASON[id];
    if (reason && reasons.length < 2 && !reasons.includes(reason)) {
      reasons.push(reason);
    }
  };

  if (opts?.cooldownActive) {
    return { suggest: false, score: 0, reasons: [], signals: ["cooldown_active"] };
  }

  if (!text || text.length < ABS_MIN_LEN) {
    return { suggest: false, score: 0, reasons: [], signals: ["too_short"] };
  }

  if (text.startsWith(PLAN_PREFIX) || text.startsWith(EXECUTE_PREFIX)) {
    return {
      suggest: false,
      score: 0,
      reasons: [],
      signals: ["already_plan_prefix"],
    };
  }

  if (CONTINUE_ONLY.test(text)) {
    return {
      suggest: false,
      score: 0,
      reasons: [],
      signals: ["continue_refine"],
    };
  }

  const numbered = countMatches(NUMBERED_GOAL, text);
  if (numbered >= 3) push("multi_numbered", scoreOf("multi_numbered", 4));

  const joins = countMatches(GOAL_JOIN, text);
  if (joins >= 2 && text.length >= 40) {
    push("multi_join", scoreOf("multi_join", 2));
  }

  if (EXPLICIT_PLAN.test(text)) {
    push("explicit_plan", scoreOf("explicit_plan", 4));
  }

  const atPaths = countMatches(PATH_AT, text);
  const chapters = countMatches(CHAPTER_REF, text);
  if (atPaths >= 2 || chapters >= 2) {
    push("multi_path", scoreOf("multi_path", 2));
  }

  const lower = text.toLowerCase();
  const riskHits = HIGH_RISK_TOKENS.filter((tok) =>
    /[a-z]/.test(tok) ? lower.includes(tok) : text.includes(tok),
  );
  if (riskHits.length > 0) {
    const per = scoreOf("high_risk_per_hit", 2);
    const cap = scoreOf("high_risk_cap", 4);
    push("high_risk_verb", Math.min(cap, per * riskHits.length));
  }

  const strong =
    signals.includes("multi_numbered") ||
    signals.includes("explicit_plan") ||
    signals.includes("high_risk_verb");

  if (text.length < SOFT_MIN_LEN && !strong) {
    return { suggest: false, score: 0, reasons: [], signals: ["too_short"] };
  }

  if (CONTINUE_LOOSE.test(text) && numbered < 3) {
    push("continue_refine", scoreOf("continue_refine", -3));
  }

  if (MICRO.test(text)) {
    push("single_micro", scoreOf("single_micro", -2));
  }

  const threshold = planSuggestThreshold(opts?.scenarioId);
  const suggest = score >= threshold;
  return {
    suggest,
    score,
    reasons: suggest ? reasons.slice(0, 2) : [],
    signals,
  };
}

/** Thin boolean wrapper (backward compatible). */
export function shouldSuggestPlanMode(
  message: string,
  opts?: PlanSuggestOptions,
): boolean {
  return evaluatePlanSuggest(message, opts).suggest;
}

/** Primary reason line for the suggest banner (at most one). */
export function planSuggestPrimaryReason(
  message: string,
  opts?: PlanSuggestOptions,
): string | null {
  const d = evaluatePlanSuggest(message, opts);
  if (!d.suggest) return null;
  return d.reasons[0] ?? null;
}
