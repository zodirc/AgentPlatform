import { describe, expect, it } from "vitest";
import { deriveAgentActivity } from "./AgentActivityPanel";

const completedWorkbench = {
  busy: false,
  awaitingApproval: false,
  displayStatus: "completed",
  view: null,
  pendingToolName: null,
} as const;

describe("deriveAgentActivity delivery status", () => {
  it("does not present a failed delivery as successful", () => {
    const activity = deriveAgentActivity(
      [
        {
          sequence: 1,
          type: "turn.completed",
          payload: {
            summary: "done",
            delivery_status: "failed",
            delivery_issues: ["missing or empty sections: chapter-2"],
          },
        },
      ] as never,
      completedWorkbench as never,
    );

    expect(activity.phase).toBe("failed");
    expect(activity.label).toBe("执行完成，交付异常");
    expect(activity.detail).toContain("chapter-2");
  });

  it("keeps a validated delivery successful", () => {
    const activity = deriveAgentActivity(
      [
        {
          sequence: 1,
          type: "turn.completed",
          payload: { summary: "done", delivery_status: "ok" },
        },
      ] as never,
      completedWorkbench as never,
    );

    expect(activity).toEqual({ phase: "completed", label: "任务已完成" });
  });
});
