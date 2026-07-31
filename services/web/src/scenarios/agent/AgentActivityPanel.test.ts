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

describe("deriveAgentActivity thinking rounds", () => {
  it("shows 1-based rounds instead of engine step_index 0", () => {
    const activity = deriveAgentActivity(
      [
        {
          sequence: 1,
          type: "turn.thinking",
          payload: { step_index: 0 },
        },
      ] as never,
      {
        busy: true,
        awaitingApproval: false,
        displayStatus: "running",
        view: null,
        pendingToolName: null,
      } as never,
    );

    expect(activity).toEqual({
      phase: "thinking",
      label: "模型思考中",
      detail: "第 1 轮",
    });
  });
});

describe("deriveAgentActivity tool_timeline fallback", () => {
  it("shows running tool from TurnView when events are not loaded yet", () => {
    const activity = deriveAgentActivity([] as never, {
      busy: true,
      awaitingApproval: false,
      displayStatus: "running",
      view: {
        tool_timeline: [
          { tool_call_id: "1", tool_name: "read_file", status: "ok" },
          {
            tool_call_id: "2",
            tool_name: "delegate",
            status: "running",
            arguments: { task: "explore auth module carefully" },
          },
        ],
      },
      pendingToolName: null,
    } as never);

    expect(activity.phase).toBe("tool");
    expect(activity.label).toBe("正在执行 delegate");
    expect(activity.detail).toContain("explore auth");
  });

  it("prefers live events over stale timeline rows", () => {
    const activity = deriveAgentActivity(
      [
        {
          sequence: 1,
          type: "tool.started",
          payload: { tool_call_id: "a", tool_name: "grep" },
        },
      ] as never,
      {
        busy: true,
        awaitingApproval: false,
        displayStatus: "running",
        view: {
          tool_timeline: [
            { tool_call_id: "old", tool_name: "delegate", status: "running" },
          ],
        },
        pendingToolName: null,
      } as never,
    );

    expect(activity.label).toBe("正在执行 grep");
  });
});
