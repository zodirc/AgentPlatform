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

export const PLAN_MODE_INSTRUCTION =
  `${PLAN_PREFIX}请先调用 update_plan 列出清晰步骤（每项 status=pending）。` +
  `本回合不要写正文、不要改工作区文件、不要跑会改系统的命令。` +
  `列出计划后用简短说明等待确认；我会再发「按此执行」。`;

export const EXECUTE_PLAN_INSTRUCTION =
  `${EXECUTE_PREFIX}请按当前计划逐步执行。` +
  `开始某步时将该项标为 in_progress，完成标为 completed，并再次调用 update_plan 更新整份清单。` +
  `不要跳过状态更新。`;

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

export function wrapMessageForPlanMode(userText: string): string {
  const body = userText.trim();
  if (body.startsWith(PLAN_PREFIX) || body.startsWith(EXECUTE_PREFIX)) {
    return body;
  }
  return `${PLAN_MODE_INSTRUCTION}\n\n用户请求：\n${body}`;
}

export function executePlanMessage(extra?: string): string {
  const note = (extra ?? "").trim();
  return note
    ? `${EXECUTE_PLAN_INSTRUCTION}\n\n${note}`
    : EXECUTE_PLAN_INSTRUCTION;
}
