import { describe, expect, it } from "vitest";
import {
  buildUnifiedDiffLines,
  countDiffChanges,
} from "./unifiedDiff";

describe("buildUnifiedDiffLines", () => {
  it("marks added and removed lines", () => {
    const lines = buildUnifiedDiffLines("a\nb\nc\n", "a\nx\nc\n");
    expect(lines.map((l) => [l.kind, l.text])).toEqual([
      ["context", "a"],
      ["del", "b"],
      ["add", "x"],
      ["context", "c"],
    ]);
    expect(countDiffChanges(lines)).toEqual({ additions: 1, deletions: 1 });
  });

  it("treats empty old as all additions", () => {
    const lines = buildUnifiedDiffLines("", "hello\nworld\n");
    expect(lines.every((l) => l.kind === "add")).toBe(true);
    expect(countDiffChanges(lines).additions).toBe(2);
  });
});
