import type { TurnEvent } from "../api/client";
import type { TokenUsage } from "./types";

/** Prefer turn-total fields from usage events; fall back to summing per-step deltas. */
export function tokenUsageFromEvents(events: TurnEvent[]): TokenUsage | null {
  let lastCumulative: TokenUsage | null = null;
  let stepIn = 0;
  let stepOut = 0;
  let hasStepDelta = false;
  let source: TokenUsage["source"];

  for (const ev of events) {
    if (ev.type === "usage.reported") {
      const p = ev.payload as Record<string, unknown>;
      const stepInput = Number(p.step_input_tokens ?? NaN);
      const stepOutput = Number(p.step_output_tokens ?? NaN);
      if (Number.isFinite(stepInput) || Number.isFinite(stepOutput)) {
        hasStepDelta = true;
        stepIn += Number.isFinite(stepInput) ? stepInput : 0;
        stepOut += Number.isFinite(stepOutput) ? stepOutput : 0;
      }
      const input = Number(p.input_tokens ?? NaN);
      const output = Number(p.output_tokens ?? NaN);
      if (Number.isFinite(input) || Number.isFinite(output)) {
        lastCumulative = {
          input_tokens: Number.isFinite(input) ? input : 0,
          output_tokens: Number.isFinite(output) ? output : 0,
          source: p.source as TokenUsage["source"],
        };
      }
      if (typeof p.source === "string") {
        source = p.source as TokenUsage["source"];
      }
      continue;
    }
    if (ev.type === "turn.completed") {
      const usage = (ev.payload as { token_usage?: TokenUsage }).token_usage;
      if (usage && typeof usage === "object") {
        lastCumulative = {
          input_tokens: Number(usage.input_tokens ?? 0),
          output_tokens: Number(usage.output_tokens ?? 0),
          source: usage.source,
        };
      }
    }
  }

  if (lastCumulative) return lastCumulative;
  if (hasStepDelta) {
    return { input_tokens: stepIn, output_tokens: stepOut, source };
  }
  return null;
}
