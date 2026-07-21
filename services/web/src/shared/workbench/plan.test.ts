import { describe, expect, it } from "vitest";
import cases from "../../../../../eval/plan_suggest/cases.json";
import {
  currentPlanStep,
  evaluatePlanSuggest,
  executePlanMessage,
  isPlanSuggestCooldownActive,
  latestPlanFromArtifacts,
  livePlanStep,
  normalizePlanStatus,
  planHasOpenItems,
  planHasStaleInProgress,
  planIsProposedOnly,
  PLAN_SUGGEST_COOLDOWN_MS,
  shouldSuggestPlanMode,
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

  it("execute CTA uses a short user-facing message", () => {
    expect(executePlanMessage()).toBe("按此执行");
    expect(executePlanMessage("先做第一步")).toBe("先做第一步");
  });
});

describe("plan suggest scoring (docs/26)", () => {
  for (const c of cases) {
    it(`case ${c.id}`, () => {
      const decision = evaluatePlanSuggest(c.message, {
        scenarioId: c.scenario_id,
        cooldownActive: Boolean(c.cooldown_active),
      });
      expect(decision.suggest).toBe(c.suggest);
      expect(shouldSuggestPlanMode(c.message, {
        scenarioId: c.scenario_id,
        cooldownActive: Boolean(c.cooldown_active),
      })).toBe(c.suggest);
      if (c.expect_signal) {
        expect(decision.signals).toContain(c.expect_signal);
      }
      if (c.suggest) {
        expect(decision.reasons.length).toBeGreaterThan(0);
        expect(decision.reasons.length).toBeLessThanOrEqual(2);
      }
    });
  }

  it("cooldown window is 30 minutes", () => {
    const now = 1_000_000;
    expect(isPlanSuggestCooldownActive(now - 1000, now)).toBe(true);
    expect(
      isPlanSuggestCooldownActive(now - PLAN_SUGGEST_COOLDOWN_MS - 1, now),
    ).toBe(false);
  });
});
