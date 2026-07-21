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

const PLAN_PREFIX = "【Plan 模式】";
const EXECUTE_PREFIX = "【执行计划】";

/** Server-bound Plan phase on StartTurn (docs/25). `ready` is UI-only. */
export type PlanPhaseWire = "planning" | "executing";

/** Workbench-visible Plan phase (includes armed / awaiting consent). */
export type PlanPhase = "off" | "planning" | "ready" | "executing";

export const PLAN_PHASE_LABEL: Record<PlanPhase, string> = {
  off: "",
  planning: "",
  ready: "",
  executing: "",
};

const NUMBERED_GOAL = /^\s*(?:\d+[\.\)、]|[-*•]\s+\S)/gm;
const GOAL_JOIN =
  /(?:然后|接着|并且|同时|另外|还要|此外|and then|also|finally)\s*/gi;

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

/** Mirror runtime detect_plan_hint — suggest switch, never auto-enter. */
export function shouldSuggestPlanMode(message: string): boolean {
  const text = message.trim();
  if (text.length < 24) return false;
  if (text.startsWith(PLAN_PREFIX) || text.startsWith(EXECUTE_PREFIX)) {
    return false;
  }
  const numbered = text.match(NUMBERED_GOAL)?.length ?? 0;
  if (numbered >= 3) return true;
  const joins = text.match(GOAL_JOIN)?.length ?? 0;
  return joins >= 2 && text.length >= 40;
}

/**
 * Message for the「按此执行」button. Keep short — never inject long instructions
 * into the chat; executing discipline is plan_phase + runtime system prompt.
 */
export function executePlanMessage(extra?: string): string {
  const note = (extra ?? "").trim();
  return note || "按此执行";
}
