import type { PatchCandidate, PinnedCards } from "./types";

export function patchCandidateFromPayload(
  raw: Record<string, unknown> | null | undefined,
): PatchCandidate | null {
  if (!raw || typeof raw.patch_id !== "string" || !raw.patch_id) return null;
  return {
    patch_id: raw.patch_id,
    path: typeof raw.path === "string" ? raw.path : "",
    old_text: typeof raw.old_text === "string" ? raw.old_text : "",
    new_text: typeof raw.new_text === "string" ? raw.new_text : "",
    summary: typeof raw.summary === "string" ? raw.summary : undefined,
    status: typeof raw.status === "string" ? raw.status : "pending",
  };
}

export function pinnedCardsFromPayload(
  raw: Record<string, unknown> | null | undefined,
): PinnedCards | null {
  if (!raw || !Array.isArray(raw.cards)) return null;
  return {
    type: "writing_cards",
    cards: raw.cards as PinnedCards["cards"],
    chars: typeof raw.chars === "number" ? raw.chars : undefined,
    available_count:
      typeof raw.available_count === "number" ? raw.available_count : undefined,
    summary: typeof raw.summary === "string" ? raw.summary : undefined,
  };
}

/** 回合进行中事件投影优先；结束后服务器制品优先，缺了再退回投影。 */
export function selectWhileRunning<T>(
  busy: boolean,
  fromEvents: T | null,
  fromServer: T | null,
  isEmpty: (value: T) => boolean,
): T | null {
  if (busy && fromEvents != null && !isEmpty(fromEvents)) return fromEvents;
  if (fromServer != null && !isEmpty(fromServer)) return fromServer;
  return fromEvents;
}
