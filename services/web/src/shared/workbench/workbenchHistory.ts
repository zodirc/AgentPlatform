import type { TurnEvent, TurnSummary, TurnView } from "../api/client";
import {
  latestPlanFromArtifacts,
  normalizePlanArtifact,
  type PlanArtifact,
} from "./plan";
import {
  isOpeningChoiceMessage,
  latestOpeningPondsFromArtifacts,
  normalizeOpeningPondsArtifact,
  type OpeningPondsArtifact,
} from "./openingPonds";
import type { ScenarioId, TurnHistoryItem } from "./types";

/** Merge snapshot + any stream events that arrived while it was in flight. */
export function mergeEventsBySequence(
  snapshot: TurnEvent[],
  live: TurnEvent[],
): TurnEvent[] {
  if (live.length === 0) return snapshot;
  if (snapshot.length === 0) return live;

  const bySeq = new Map<number, TurnEvent>();
  const byLiveId = new Map<string, TurnEvent>();

  const ingest = (ev: TurnEvent) => {
    if (ev.live || ev.sequence == null) {
      byLiveId.set(ev.event_id, ev);
      return;
    }
    bySeq.set(ev.sequence, ev);
  };
  for (const ev of snapshot) ingest(ev);
  for (const ev of live) ingest(ev);

  const durable = [...bySeq.values()].sort(
    (a, b) => (a.sequence as number) - (b.sequence as number),
  );
  const liveOnly = [...byLiveId.values()].sort((a, b) => {
    const la = a.live_seq ?? 0;
    const lb = b.live_seq ?? 0;
    if (la !== lb) return la - lb;
    return String(a.ts ?? "").localeCompare(String(b.ts ?? ""));
  });
  // Live deltas are display-only; keep durable first, then live chronologically.
  return [...durable, ...liveOnly];
}

export function toHistoryItem(turn: TurnSummary): TurnHistoryItem {
  const user_input = turn.user_input ?? "";
  return {
    id: turn.id,
    scenario_id: turn.scenario_id as ScenarioId,
    status: turn.status,
    user_input,
    latest_output: turn.latest_output,
    created_at: turn.created_at,
    hideUserInput: isOpeningChoiceMessage(user_input),
    plan: normalizePlanArtifact(turn.plan ?? null),
    openingPonds: normalizeOpeningPondsArtifact(turn.opening_ponds ?? null),
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
    plan: item.plan !== undefined ? item.plan : prev.plan,
    openingPonds:
      item.openingPonds != null ? item.openingPonds : prev.openingPonds,
    hideUserInput:
      Boolean(item.hideUserInput) ||
      Boolean(prev.hideUserInput) ||
      isOpeningChoiceMessage(item.user_input ?? prev.user_input),
  };
  return next;
}

export function historyItemFromView(v: TurnView): TurnHistoryItem {
  const user_input = v.user_input ?? "";
  return {
    id: v.turn_id,
    scenario_id: v.scenario_id as ScenarioId,
    status: v.status,
    user_input,
    latest_output: v.latest_output ?? null,
    created_at: v.updated_at,
    hideUserInput: isOpeningChoiceMessage(user_input),
    plan: latestPlanFromArtifacts(
      v.artifacts as Record<string, unknown>[] | undefined,
    ),
    openingPonds: latestOpeningPondsFromArtifacts(
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

export function patchHistoryOpeningPonds(
  items: TurnHistoryItem[],
  turnId: string,
  openingPonds: OpeningPondsArtifact | null,
): TurnHistoryItem[] {
  return items.map((row) =>
    row.id === turnId ? { ...row, openingPonds } : row,
  );
}
