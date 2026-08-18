import { describe, expect, it } from "vitest";

import {
  approvalCopy,
  approvalDetailLine,
  approvalToolKind,
  defaultPrefixFromCommand,
  lastApprovalEvent,
} from "./toolApproval";

describe("toolApproval", () => {
  it("labels run_command separately from write_file", () => {
    expect(approvalToolKind("run_command")).toBe("run_command");
    expect(approvalCopy("run_command").approveLabel).toBe("批准这次");
    expect(approvalCopy("write_file").approveLabel).toContain("批准写文件");
    expect(approvalCopy("edit_file").description).toContain("后续");
  });

  it("summarizes path or command for the sticky bar", () => {
    expect(
      approvalDetailLine("write_file", { path: "src/a.py" }, "src/a.py"),
    ).toBe("src/a.py");
    expect(
      approvalDetailLine("run_command", { command: "pytest -q" }),
    ).toBe("pytest -q");
    expect(approvalDetailLine("run_tests", {})).toBe("run_tests");
  });

  it("takes the first token as the default allow-list prefix", () => {
    expect(defaultPrefixFromCommand("pytest -q tests/")).toBe("pytest");
    expect(defaultPrefixFromCommand("")).toBe("");
  });

  it("ignores approval.requested after a matching approval.resolved", () => {
    expect(
      lastApprovalEvent([
        {
          type: "approval.requested",
          payload: { tool_call_id: "cmd-1", tool_name: "run_command" },
        },
        {
          type: "approval.resolved",
          payload: { tool_call_id: "cmd-1", decision: "approved" },
        },
      ]),
    ).toBeUndefined();
  });

  it("keeps a later unresolved approval after an earlier one was resolved", () => {
    const next = lastApprovalEvent([
      {
        type: "approval.requested",
        payload: { tool_call_id: "cmd-1" },
      },
      {
        type: "approval.resolved",
        payload: { tool_call_id: "cmd-1", decision: "approved" },
      },
      {
        type: "approval.requested",
        payload: { tool_call_id: "cmd-2", arguments: { command: "ls" } },
      },
    ]);
    expect(next?.payload?.tool_call_id).toBe("cmd-2");
  });
});
