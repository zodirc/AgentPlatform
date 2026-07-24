import { describe, expect, it } from "vitest";
import type { TurnEvent } from "../api/client";
import {
  deriveSubagentsFromEvents,
  deriveSubagentsFromView,
  parentTimelineItems,
  resolveSubagents,
} from "./subagents";

function ev(
  type: string,
  payload: Record<string, unknown>,
  sequence: number,
): TurnEvent {
  return {
    event_id: `e-${sequence}`,
    turn_id: "t1",
    sequence,
    type,
    payload,
  } as TurnEvent;
}

describe("deriveSubagentsFromEvents", () => {
  it("builds a nested readonly transcript from stamped events", () => {
    const events = [
      ev(
        "subagent.started",
        {
          subagent_id: "sub-abc",
          agent_type: "explore",
          task: "scan auth",
        },
        1,
      ),
      ev(
        "turn.thinking.delta",
        { subagent_id: "sub-abc", delta: "looking…" },
        2,
      ),
      ev(
        "tool.started",
        {
          subagent_id: "sub-abc",
          tool_call_id: "t1",
          tool_name: "read_file",
          arguments: { path: "a.ts" },
        },
        3,
      ),
      ev(
        "tool.completed",
        {
          subagent_id: "sub-abc",
          tool_call_id: "t1",
          tool_name: "read_file",
          status: "ok",
          summary: "ok",
        },
        4,
      ),
      ev("turn.token", { subagent_id: "sub-abc", delta: "found login" }, 5),
      ev(
        "subagent.completed",
        {
          subagent_id: "sub-abc",
          agent_type: "explore",
          summary: "found login",
        },
        6,
      ),
    ];

    const subs = deriveSubagentsFromEvents(events);
    expect(subs).toHaveLength(1);
    expect(subs[0].agent_type).toBe("explore");
    expect(subs[0].task).toBe("scan auth");
    expect(subs[0].status).toBe("completed");
    expect(subs[0].thinkingText).toContain("looking");
    expect(subs[0].streamText).toBe("found login");
    expect(subs[0].tools).toHaveLength(1);
    expect(subs[0].tools[0].tool_name).toBe("read_file");
    expect(subs[0].tools[0].status).toBe("ok");
  });

  it("ignores parent events without subagent_id", () => {
    const events = [
      ev("turn.token", { delta: "parent only" }, 1),
      ev("tool.started", { tool_call_id: "p1", tool_name: "delegate" }, 2),
    ];
    expect(deriveSubagentsFromEvents(events)).toEqual([]);
  });
});

describe("deriveSubagentsFromView", () => {
  it("rebuilds tabs from artifacts and nested tool timeline", () => {
    const subs = deriveSubagentsFromView({
      artifacts: [
        {
          type: "subagent",
          event: "subagent.started",
          subagent_id: "sub-1",
          agent_type: "explore",
          task: "scan",
        },
        {
          type: "subagent",
          event: "subagent.completed",
          subagent_id: "sub-1",
          agent_type: "explore",
          summary: "done",
        },
      ],
      tool_timeline: [
        {
          tool_call_id: "t1",
          tool_name: "read_file",
          status: "ok",
          subagent_id: "sub-1",
          summary: "ok",
        },
      ],
    });
    expect(subs).toHaveLength(1);
    expect(subs[0].task).toBe("scan");
    expect(subs[0].summary).toBe("done");
    expect(subs[0].status).toBe("completed");
    expect(subs[0].tools).toHaveLength(1);
  });
});

describe("resolveSubagents", () => {
  it("prefers events over view fallback", () => {
    const fromEvents = resolveSubagents(
      [
        ev(
          "subagent.started",
          { subagent_id: "a", agent_type: "explore", task: "from events" },
          1,
        ),
      ],
      {
        artifacts: [
          {
            type: "subagent",
            event: "subagent.started",
            subagent_id: "b",
            agent_type: "explore",
            task: "from view",
          },
        ],
      },
    );
    expect(fromEvents).toHaveLength(1);
    expect(fromEvents[0].task).toBe("from events");
  });
});

describe("parentTimelineItems", () => {
  it("drops nested tools", () => {
    expect(
      parentTimelineItems([
        { tool_call_id: "1", tool_name: "delegate", status: "ok" },
        {
          tool_call_id: "2",
          tool_name: "read_file",
          status: "ok",
          subagent_id: "sub-1",
        },
      ]),
    ).toEqual([{ tool_call_id: "1", tool_name: "delegate", status: "ok" }]);
  });
});
