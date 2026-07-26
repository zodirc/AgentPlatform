import { describe, expect, it } from "vitest";
import { buildTimeline, messagesFromPayload, toolsFromPayload } from "./opsMessageParse";

describe("opsMessageParse", () => {
  it("keeps full text and tool call detail on timeline", () => {
    const long = "A".repeat(400);
    const rows = buildTimeline([
      { role: "system", content: [{ type: "text", text: long }] },
      {
        role: "user",
        content: [{ type: "text", text: "[runtime_context] scenario_id=agent step=1/50" }],
      },
      {
        role: "assistant",
        content: [
          { type: "text", text: "看一下" },
          { name: "list_dir", type: "tool_use", input: { path: "." } },
        ],
      },
      {
        role: "tool",
        content: [
          {
            type: "tool_result",
            tool_use_id: "call_1",
            content: "{\"entries\":[\"a\"]}",
          },
        ],
      },
    ]);
    expect(rows[0].segments[0]).toMatchObject({ kind: "text", text: long });
    expect(rows[1].isRuntimeContext).toBe(true);
    expect(rows[2].segments.some((s) => s.kind === "tool_call" && s.name === "list_dir")).toBe(
      true,
    );
    const call = rows[2].segments.find((s) => s.kind === "tool_call");
    expect(call && call.kind === "tool_call" && call.detail).toContain("path");
    expect(rows[3].segments[0]?.kind).toBe("tool_result");
  });

  it("reads envelope shape", () => {
    const payload = {
      tools: [{ name: "read_file" }],
      messages: [{ role: "user", content: "hi" }],
    };
    expect(messagesFromPayload(payload)).toHaveLength(1);
    expect(toolsFromPayload(payload)).toHaveLength(1);
  });
});
