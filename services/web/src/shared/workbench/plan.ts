/** Platform Plan mode helpers (docs/25). */

export type PlanItemStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "cancelled"
  | string;

export type PlanItem = {
  id: string;
  title: string;
  status: PlanItemStatus;
};

export type PlanArtifact = {
  type?: "plan";
  plan_id?: string;
  summary?: string;
  items?: PlanItem[];
};

/** Server-bound Plan phase on StartTurn (docs/25). `ready` is UI-only. */
export type PlanPhaseWire = "planning" | "executing";

/** Workbench-visible Plan phase (includes armed / awaiting consent). */
export type PlanPhase = "off" | "planning" | "ready" | "executing";

export const PLAN_PHASE_LABEL: Record<PlanPhase, string> = {
  off: "",
  planning: "规划中 · 仅列步骤，不改文件",
  ready: "待确认 · 同意后按清单执行",
  executing: "执行中 · 清单内写盘已授权",
};

/** Formal Plan mode vs ordinary Agent progress checklist (Cursor Todo vs Plan). */
export function isFormalPlanPhase(planPhase: PlanPhase | undefined | null): boolean {
  return planPhase === "planning" || planPhase === "ready" || planPhase === "executing";
}

export function planPanelTitle(planPhase: PlanPhase | undefined | null): string {
  return isFormalPlanPhase(planPhase) ? "任务计划" : "任务进度";
}

/** Soften backend plan/progress summary for ordinary Agent checklists. */
export function planPanelSummaryDisplay(
  summary: string | undefined,
  planPhase: PlanPhase | undefined | null,
): string {
  const raw = String(summary ?? "").trim();
  if (!raw) return "";
  if (isFormalPlanPhase(planPhase)) return raw;
  const progress = /^(?:Plan|Progress) with (\d+) item\(s\)(.*)$/i.exec(raw);
  if (progress) {
    const n = progress[1];
    const rest = (progress[2] || "").trim();
    return rest ? `进度 · ${n} 项 ${rest}` : `进度 · ${n} 项`;
  }
  if (/^Plan with /i.test(raw)) {
    return raw.replace(/^Plan with /i, "进度 · ");
  }
  return raw;
}

export {
  clearPlanSuggestDismissedAt,
  evaluatePlanSuggest,
  isPlanSuggestCooldownActive,
  planSuggestPrimaryReason,
  PLAN_SUGGEST_COOLDOWN_MS,
  readPlanSuggestDismissedAt,
  shouldSuggestPlanMode,
  writePlanSuggestDismissedAt,
} from "./planSuggest";
export type { PlanSuggestDecision, PlanSuggestOptions } from "./planSuggest";

export function normalizePlanStatus(raw: string | undefined): PlanItemStatus {
  const s = String(raw ?? "pending").trim().toLowerCase();
  if (s === "in_progress" || s === "in-progress" || s === "running") {
    return "in_progress";
  }
  if (s === "completed" || s === "done" || s === "complete") {
    return "completed";
  }
  if (s === "cancelled" || s === "canceled" || s === "skipped") {
    return "cancelled";
  }
  if (s === "pending" || s === "todo" || s === "open") {
    return "pending";
  }
  return s || "pending";
}

export function normalizePlanItems(
  items: Array<{ id?: string; title?: string; status?: string }> | undefined,
): PlanItem[] {
  if (!Array.isArray(items)) return [];
  return items.map((item, i) => ({
    id: String(item.id ?? i + 1),
    title: String(item.title ?? "item").trim() || `步骤 ${i + 1}`,
    status: normalizePlanStatus(item.status),
  }));
}

/** Prefer the last plan artifact (projection should keep one; tolerate legacy append). */
export function latestPlanFromArtifacts(
  artifacts: Record<string, unknown>[] | undefined | null,
): PlanArtifact | null {
  if (!artifacts?.length) return null;
  let found: PlanArtifact | null = null;
  for (const art of artifacts) {
    if (art?.type === "plan") {
      found = art as PlanArtifact;
    }
  }
  if (!found) return null;
  return {
    ...found,
    items: normalizePlanItems(found.items),
  };
}

export function planFromEventPayload(
  payload: Record<string, unknown>,
): PlanArtifact {
  const items = normalizePlanItems(
    payload.items as Array<{ id?: string; title?: string; status?: string }>,
  );
  return {
    type: "plan",
    plan_id: payload.plan_id ? String(payload.plan_id) : undefined,
    summary: payload.summary ? String(payload.summary) : undefined,
    items,
  };
}

export function currentPlanStep(plan: PlanArtifact | null): PlanItem | null {
  if (!plan?.items?.length) return null;
  return (
    plan.items.find((i) => normalizePlanStatus(i.status) === "in_progress") ??
    null
  );
}

export function planHasOpenItems(plan: PlanArtifact | null): boolean {
  if (!plan?.items?.length) return false;
  return plan.items.some((i) => {
    const s = normalizePlanStatus(i.status);
    return s === "pending" || s === "in_progress";
  });
}

/** in_progress is only "live" while the turn is still running. */
export function isActiveTurnStatus(status: string | null | undefined): boolean {
  const s = String(status ?? "");
  return s === "running" || s === "pending" || s === "waiting_approval";
}

/**
 * Current step for live UI. After turn completes, leftover in_progress is stale
 * (model often forgets to mark done) — do not present as still executing.
 */
export function livePlanStep(
  plan: PlanArtifact | null,
  turnStatus: string | null | undefined,
): PlanItem | null {
  if (!isActiveTurnStatus(turnStatus)) return null;
  return currentPlanStep(plan);
}

export function planHasStaleInProgress(
  plan: PlanArtifact | null,
  turnStatus: string | null | undefined,
): boolean {
  if (isActiveTurnStatus(turnStatus)) return false;
  return currentPlanStep(plan) != null;
}

/**
 * True only when every step is still pending — i.e. proposed, not started.
 * Once any step is in_progress/completed/cancelled, "按此执行" must not show
 * (re-clicking would double-run an already advancing plan).
 */
export function planIsProposedOnly(plan: PlanArtifact | null): boolean {
  if (!plan?.items?.length) return false;
  return plan.items.every(
    (i) => normalizePlanStatus(i.status) === "pending",
  );
}

/**
 * Message for the「按此执行」button. Keep short — never inject long instructions
 * into the chat; executing discipline is plan_phase + runtime system prompt.
 */
export function executePlanMessage(extra?: string): string {
  const note = (extra ?? "").trim();
  return note || "按此执行";
}
