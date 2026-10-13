export type TurnEnvelope = {
  type?: string;
  sequence?: number;
  payload?: Record<string, unknown>;
};

export type TurnProjection = {
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  opening_ponds: Record<string, unknown> | null;
  plan: Record<string, unknown> | null;
  patch_candidates: Record<string, unknown>[];
  pinned_cards: Record<string, unknown> | null;
  usage: { input_tokens: number; output_tokens: number } | null;
  last_event_sequence: number;
};

export function emptyTurnView(): TurnProjection {
  return {
    status: "pending",
    opening_ponds: null,
    plan: null,
    patch_candidates: [],
    pinned_cards: null,
    usage: null,
    last_event_sequence: 0,
  };
}

/** 按 sequence 去重后折叠。相位只从事件推出。 */
export function reduceTurn(events: TurnEnvelope[]): TurnProjection {
  const ordered = [...events].sort(
    (a, b) => (a.sequence ?? 0) - (b.sequence ?? 0),
  );
  const seen = new Set<number>();
  return ordered.reduce((view, event) => {
    const sequence = event.sequence ?? 0;
    if (sequence > 0 && seen.has(sequence)) return view;
    if (sequence > 0) seen.add(sequence);
    return applyEvent(view, event);
  }, emptyTurnView());
}

function applyEvent(view: TurnProjection, event: TurnEnvelope): TurnProjection {
  const next = { ...view, patch_candidates: [...view.patch_candidates] };
  const sequence = event.sequence ?? next.last_event_sequence;
  if (sequence > next.last_event_sequence) next.last_event_sequence = sequence;
  const payload = event.payload ?? {};
  switch (event.type) {
    case "turn.accepted":
    case "step.started":
      if (next.status === "pending") next.status = "running";
      break;
    case "opening.ponds":
      next.opening_ponds = payload;
      break;
    case "turn.plan":
      next.plan = payload;
      break;
    case "patch.proposed":
      next.patch_candidates.push(payload);
      break;
    case "cards.pinned":
      next.pinned_cards = payload;
      break;
    case "usage.reported":
      next.usage = {
        input_tokens: numberField(payload, "input_tokens"),
        output_tokens: numberField(payload, "output_tokens"),
      };
      break;
    case "step.completed": {
      const usage = payload.usage;
      if (usage && typeof usage === "object") {
        const row = usage as Record<string, unknown>;
        next.usage = {
          input_tokens: numberField(row, "input_tokens"),
          output_tokens: numberField(row, "output_tokens"),
        };
      }
      break;
    }
    case "turn.completed":
      next.status = "completed";
      break;
    case "turn.failed":
      next.status = "failed";
      break;
    case "turn.cancelled":
      next.status = "cancelled";
      break;
    default:
      break;
  }
  return next;
}

function numberField(payload: Record<string, unknown>, key: string): number {
  const value = payload[key];
  return typeof value === "number" ? value : 0;
}
