import type { TurnEvent, TurnSummary, TurnView } from "../api/client";
import {
  latestPlanFromArtifacts,
  normalizePlanArtifact,
  type PlanArtifact,
} from "./plan";
import type { ScenarioId, TurnHistoryItem } from "./types";

/** Merge snapshot + any stream events that arrived while it was in flight. */
export function mergeEventsBySequence(
  snapshot: TurnEvent[],
  live: TurnEvent[],
): TurnEvent[] {
  if (live.length === 0) return snapshot;
  if (snapshot.length === 0) return live;
  const bySeq = new Map<number, TurnEvent>();
  for (const ev of snapshot) {
    if (typeof ev.sequence === "number") bySeq.set(ev.sequence, ev);
  }
  for (const ev of live) {
    if (typeof ev.sequence === "number") bySeq.set(ev.sequence, ev);
  }
  return [...bySeq.values()].sort((a, b) => a.sequence - b.sequence);
}

export function toHistoryItem(turn: TurnSummary): TurnHistoryItem {
  return {
    id: turn.id,
    scenario_id: turn.scenario_id as ScenarioId,
    status: turn.status,
    user_input: turn.user_input ?? "",
    latest_output: turn.latest_output,
    created_at: turn.created_at,
    plan: normalizePlanArtifact(turn.plan ?? null),
  };
}

export function upsertHistoryItem(
  items: TurnHistoryItem[],
  item: TurnHistoryItem,
): TurnHistoryItem[] {
  const idx = items.findIndex((row) => row.id === item.id);
  if (idx < 0) return [...items, item];
  const next = [...items];
  const prev = next[idx];
  next[idx] = {
    ...prev,
    ...item,
    // Avoid clobbering a live plan with an older partial merge that omitted plan.
    plan: item.plan !== undefined ? item.plan : prev.plan,
  };
  return next;
}

export function historyItemFromView(v: TurnView): TurnHistoryItem {
  return {
    id: v.turn_id,
    scenario_id: v.scenario_id as ScenarioId,
    status: v.status,
    user_input: v.user_input,
    latest_output: v.latest_output ?? null,
    created_at: v.updated_at,
    plan: latestPlanFromArtifacts(
      v.artifacts as Record<string, unknown>[] | undefined,
    ),
  };
}

export function patchHistoryPlan(
  items: TurnHistoryItem[],
  turnId: string,
  plan: PlanArtifact | null,
): TurnHistoryItem[] {
  return items.map((row) => (row.id === turnId ? { ...row, plan } : row));
}
