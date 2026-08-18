import { describe, expect, it } from "vitest";

import {
  approvalCopy,
  approvalDetailLine,
  approvalToolKind,
  defaultPrefixFromCommand,
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
});
