import { describe, expect, it } from "vitest";

import { suiteWallTimes } from "./suiteTiming";

describe("suiteWallTimes", () => {
  it("prefers persisted suite_wall_s on cases", () => {
    const rows = suiteWallTimes(
      {
        official_suite: "retrieval+coding_infer",
        cases: [
          { case_id: "official.retrieval", status: "pass", metrics: { suite_wall_s: 120 } },
          { case_id: "official.coding", status: "pass", suite_wall_s: 300 },
        ],
        logs: [],
        status: "completed",
        finished_at: "2026-08-15T05:00:00Z",
      },
      Date.parse("2026-08-15T05:00:00Z"),
    );
    expect(rows.map((r) => [r.key, r.elapsedSec, r.label])).toEqual([
      ["retrieval", 120, "检索"],
      ["coding", 300, "编码"],
    ]);
  });

  it("derives sequential walls from suite start logs", () => {
    const rows = suiteWallTimes(
      {
        official_suite: "coding_infer+retrieval_zh+retrieval+context",
        cases: [
          { case_id: "official.coding", status: "pass" },
          { case_id: "official.retrieval_zh", status: "pass" },
          { case_id: "official.retrieval", status: "pass" },
          { case_id: "official.context", status: "pass" },
        ],
        logs: [
          { at: "2026-08-15T03:02:24Z", message: "[L1] suite start coding_infer" },
          { at: "2026-08-15T04:00:00Z", message: "[L1] suite start retrieval_zh" },
          { at: "2026-08-15T04:20:00Z", message: "[L1] suite start retrieval" },
          { at: "2026-08-15T04:40:00Z", message: "[L1] suite start context" },
        ],
        status: "completed",
        finished_at: "2026-08-15T05:01:04Z",
      },
      Date.parse("2026-08-15T05:01:04Z"),
    );
    const byKey = Object.fromEntries(rows.map((r) => [r.key, Math.round(r.elapsedSec || 0)]));
    expect(byKey.coding).toBe(3456);
    expect(byKey.retrieval_zh).toBe(1200);
    expect(byKey.retrieval).toBe(1200);
    expect(byKey.context).toBe(1264);
    expect(rows.every((r) => !r.running)).toBe(true);
  });
});
