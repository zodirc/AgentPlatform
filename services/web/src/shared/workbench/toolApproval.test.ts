import { describe, expect, it } from "vitest";

import { approvalCopy, approvalToolKind } from "./toolApproval";

describe("toolApproval", () => {
  it("labels run_command separately from write_file", () => {
    expect(approvalToolKind("run_command")).toBe("run_command");
    expect(approvalCopy("run_command").approveLabel).toBe("批准执行命令");
    expect(approvalCopy("write_file").approveLabel).toBe("批准写文件");
  });
});
