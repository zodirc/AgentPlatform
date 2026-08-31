import { describe, expect, it } from "vitest";
import type { TurnEvent } from "../api/client";
import { mergeEventsBySequence } from "./workbenchHistory";

function durable(seq: number, type = "turn.accepted"): TurnEvent {
  return {
    event_id: `d-${seq}`,
    sequence: seq,
    type,
    turn_id: "t1",
    payload: {},
  };
}

function live(liveSeq: number, type = "turn.token"): TurnEvent {
  return {
    event_id: `l-${liveSeq}`,
    sequence: null,
    live: true,
    live_seq: liveSeq,
    type,
    turn_id: "t1",
    payload: { delta: "x" },
    ts: `2026-08-31T00:00:0${liveSeq}Z`,
  };
}

describe("mergeEventsBySequence", () => {
  it("keeps live envelopes that have null sequence", () => {
    const merged = mergeEventsBySequence(
      [durable(1)],
      [live(1), live(2), durable(2)],
    );
    expect(merged.map((e) => e.event_id)).toEqual([
      "d-1",
      "d-2",
      "l-1",
      "l-2",
    ]);
  });

  it("dedupes live by event_id", () => {
    const a = live(1);
    const merged = mergeEventsBySequence([a], [{ ...a, payload: { delta: "y" } }]);
    expect(merged.filter((e) => e.live)).toHaveLength(1);
    expect(merged.find((e) => e.live)?.payload).toEqual({ delta: "y" });
  });
});
