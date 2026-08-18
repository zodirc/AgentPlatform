import { describe, expect, it } from "vitest";
import {
  formatTurnElapsed,
  liveRunningTool,
  resolveStartedMs,
  toolCallElapsedSeconds,
} from "./turnElapsed";

describe("formatTurnElapsed", () => {
  it("formats minutes and seconds", () => {
    expect(formatTurnElapsed(5)).toBe("0:05");
    expect(formatTurnElapsed(65)).toBe("1:05");
    expect(formatTurnElapsed(3605)).toBe("1:00:05");
  });
});

const t0 = "2026-08-18T09:00:00.000Z";
const t12 = "2026-08-18T09:00:12.000Z";
const now = Date.parse("2026-08-18T09:00:45.000Z");

describe("toolCallElapsedSeconds", () => {
  it("ticks from started ts until now while running", () => {
    expect(
      toolCallElapsedSeconds(
        [
          {
            type: "tool.started",
            sequence: 1,
            ts: t0,
            payload: { tool_call_id: "c1", tool_name: "run_command" },
          },
        ],
        "c1",
        now,
      ),
    ).toBe(45);
  });

  it("uses completed ts once finished", () => {
    expect(
      toolCallElapsedSeconds(
        [
          {
            type: "tool.started",
            sequence: 1,
            ts: t0,
            payload: { tool_call_id: "c1" },
          },
          {
            type: "tool.completed",
            sequence: 2,
            ts: t12,
            payload: { tool_call_id: "c1", status: "ok" },
          },
        ],
        "c1",
        now,
      ),
    ).toBe(12);
  });

  it("returns null when start ts is missing", () => {
    expect(
      toolCallElapsedSeconds(
        [
          {
            type: "tool.started",
            sequence: 1,
            payload: { tool_call_id: "c1" },
          },
        ],
        "c1",
        now,
      ),
    ).toBeNull();
  });
});

describe("liveRunningTool", () => {
  it("returns the latest unfinished tool.started", () => {
    const live = liveRunningTool([
      {
        type: "tool.started",
        sequence: 1,
        ts: t0,
        payload: {
          tool_call_id: "old",
          tool_name: "read_file",
          arguments: { path: "a.ts" },
        },
      },
      {
        type: "tool.completed",
        sequence: 2,
        ts: t12,
        payload: { tool_call_id: "old" },
      },
      {
        type: "tool.started",
        sequence: 3,
        ts: t12,
        payload: {
          tool_call_id: "cur",
          tool_name: "run_command",
          arguments: { command: "python -m pip install tree-sitter-javascript" },
        },
      },
    ]);
    expect(live?.toolCallId).toBe("cur");
    expect(live?.toolName).toBe("run_command");
    expect(live?.detail).toContain("tree-sitter");
    expect(live?.startedMs).toBe(Date.parse(t12));
  });
});

describe("resolveStartedMs", () => {
  it("prefers event ts and sticks to the first local sighting otherwise", () => {
    expect(resolveStartedMs("x", 1000, 5000)).toBe(1000);
    const id = "missing-ts-local-clock";
    expect(resolveStartedMs(id, null, 9000)).toBe(9000);
    expect(resolveStartedMs(id, null, 12000)).toBe(9000);
  });
});
