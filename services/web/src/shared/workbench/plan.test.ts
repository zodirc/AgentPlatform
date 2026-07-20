import { describe, expect, it } from "vitest";
import {
  currentPlanStep,
  executePlanMessage,
  latestPlanFromArtifacts,
  livePlanStep,
  normalizePlanStatus,
  planHasOpenItems,
  planHasStaleInProgress,
  planIsProposedOnly,
  shouldSuggestPlanMode,
  wrapMessageForPlanMode,
} from "./plan";

describe("plan helpers", () => {
  it("normalizes status aliases", () => {
    expect(normalizePlanStatus("done")).toBe("completed");
    expect(normalizePlanStatus("in-progress")).toBe("in_progress");
    expect(normalizePlanStatus("todo")).toBe("pending");
  });

  it("picks the latest plan artifact", () => {
    const plan = latestPlanFromArtifacts([
      {
        type: "plan",
        plan_id: "old",
        items: [{ id: "1", title: "A", status: "pending" }],
      },
      {
        type: "plan",
        plan_id: "new",
        items: [
          { id: "1", title: "A", status: "completed" },
          { id: "2", title: "B", status: "in_progress" },
        ],
      },
    ]);
    expect(plan?.plan_id).toBe("new");
    expect(currentPlanStep(plan)?.title).toBe("B");
    expect(planHasOpenItems(plan)).toBe(true);
    expect(planIsProposedOnly(plan)).toBe(false);
  });

  it("treats all-pending plans as proposed-only", () => {
    expect(
      planIsProposedOnly({
        items: [
          { id: "1", title: "A", status: "pending" },
          { id: "2", title: "B", status: "pending" },
        ],
      }),
    ).toBe(true);
    expect(
      planIsProposedOnly({
        items: [
          { id: "1", title: "A", status: "in_progress" },
          { id: "2", title: "B", status: "pending" },
        ],
      }),
    ).toBe(false);
  });

  it("hides live step when turn already completed", () => {
    const plan = {
      items: [{ id: "1", title: "A", status: "in_progress" }],
    };
    expect(livePlanStep(plan, "completed")).toBeNull();
    expect(planHasStaleInProgress(plan, "completed")).toBe(true);
    expect(livePlanStep(plan, "running")?.title).toBe("A");
  });

  it("suggests plan only for multi-goal text", () => {
    expect(shouldSuggestPlanMode("改一下语气")).toBe(false);
    expect(
      shouldSuggestPlanMode(
        "1. 先改大纲\n2. 再写第三章\n3. 最后检查引用是否齐全",
      ),
    ).toBe(true);
  });

  it("wraps plan / execute messages with visible prefixes", () => {
    expect(wrapMessageForPlanMode("写后面几章")).toContain("【Plan 模式】");
    expect(wrapMessageForPlanMode("写后面几章")).toContain("写后面几章");
    expect(executePlanMessage()).toContain("【执行计划】");
  });
});
