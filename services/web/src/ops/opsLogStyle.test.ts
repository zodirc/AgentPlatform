import { describe, expect, it } from "vitest";
import { isOpsErrorLogLine } from "./opsLogStyle";

describe("isOpsErrorLogLine", () => {
  it("does not flag harness progress when error counter is zero", () => {
    expect(
      isOpsErrorLogLine(
        "[L1] coding harness progress done=0/5 pct=0 resolved=1 unresolved=0 error=0",
      ),
    ).toBe(false);
    expect(
      isOpsErrorLogLine(
        "[L1] coding harness done resolved=1/5 unresolved=4 error=0 rate=0.200",
      ),
    ).toBe(false);
  });

  it("flags non-zero harness error counts and real failures", () => {
    expect(
      isOpsErrorLogLine(
        "[L1] coding harness progress done=2/5 pct=40 resolved=1 unresolved=0 error=1",
      ),
    ).toBe(true);
    expect(
      isOpsErrorLogLine(
        "[L1] coding harness done status=failed error=docker pull hung",
      ),
    ).toBe(true);
    expect(isOpsErrorLogLine("turn.failed termination_reason=fatal_error")).toBe(
      true,
    );
  });
});
