import { describe, expect, it } from "vitest";
import { tokenUsageFromEvents } from "./tokenUsage";

describe("tokenUsageFromEvents", () => {
  it("uses turn-cumulative fields from the latest usage.reported", () => {
    const usage = tokenUsageFromEvents([
      {
        sequence: 1,
        type: "usage.reported",
        payload: {
          input_tokens: 100,
          output_tokens: 20,
          step_input_tokens: 100,
          step_output_tokens: 20,
          source: "provider",
        },
      },
      {
        sequence: 2,
        type: "usage.reported",
        payload: {
          input_tokens: 350,
          output_tokens: 55,
          step_input_tokens: 250,
          step_output_tokens: 35,
          source: "provider",
        },
      },
    ] as never);

    expect(usage).toEqual({
      input_tokens: 350,
      output_tokens: 55,
      source: "provider",
    });
  });

  it("sums step deltas when only step_* fields are present", () => {
    const usage = tokenUsageFromEvents([
      {
        sequence: 1,
        type: "usage.reported",
        payload: {
          step_input_tokens: 100,
          step_output_tokens: 20,
          source: "estimated",
        },
      },
      {
        sequence: 2,
        type: "usage.reported",
        payload: {
          step_input_tokens: 250,
          step_output_tokens: 35,
          source: "estimated",
        },
      },
    ] as never);

    expect(usage).toEqual({
      input_tokens: 350,
      output_tokens: 55,
      source: "estimated",
    });
  });
});
