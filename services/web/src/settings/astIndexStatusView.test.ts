import { describe, expect, it } from "vitest";
import {
  catchupHint,
  progressPercent,
  statusLabel,
} from "./astIndexStatusView";

describe("astIndexStatusView", () => {
  it("does not treat GC-aligned files_done as 100% while stale", () => {
    const status = {
      status: "stale" as const,
      files_done: 11,
      files_total: 11,
      files_indexed: 11,
      files_stored: 2711,
      pending_delete: 2700,
      pending_upsert: 0,
      catchup_remaining: 2700,
      catchup_total: 2700,
      generation: 3,
    };
    expect(statusLabel(status)).toContain("待删 2700");
    expect(statusLabel(status)).toContain("内存 11 文件");
    expect(progressPercent(status)).toBe(0);
  });

  it("moves the catch-up bar as remaining shrinks", () => {
    expect(
      progressPercent({
        status: "stale",
        catchup_remaining: 1700,
        catchup_total: 2700,
        pending_delete: 1700,
      }),
    ).toBe(37);
  });

  it("hints when the indexer has not claimed work", () => {
    expect(
      catchupHint({
        status: "stale",
        catchup_remaining: 2700,
        jobs_pending: 0,
        jobs_running: 0,
      }),
    ).toMatch(/ast-indexer/);
  });

  it("labels ready with indexed file count", () => {
    expect(
      statusLabel({ status: "ready", files_indexed: 11, generation: 4 }),
    ).toBe("就绪 · 11 文件");
    expect(
      progressPercent({
        status: "ready",
        files_done: 11,
        files_total: 11,
      }),
    ).toBe(100);
  });
});
