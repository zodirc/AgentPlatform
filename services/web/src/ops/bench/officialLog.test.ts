import { describe, expect, it } from "vitest";
import { isOpsKeyLogItem } from "./officialLog";

describe("isOpsKeyLogItem", () => {
  it("keeps coding harness progress and stage lines", () => {
    expect(
      isOpsKeyLogItem({
        kind: "log",
        message:
          "[L1] coding harness progress done=2/5 pct=40 resolved=1 unresolved=1 error=0",
      }),
    ).toBe(true);
    expect(
      isOpsKeyLogItem({
        kind: "log",
        message:
          "[L1] coding harness stage evaluating n=5 detail=Running 5 instances...",
      }),
    ).toBe(true);
    expect(
      isOpsKeyLogItem({
        kind: "log",
        message: "[L1] coding harness start n=5",
      }),
    ).toBe(true);
  });

  it("still drops noisy non-milestone chatter", () => {
    expect(
      isOpsKeyLogItem({
        kind: "log",
        message: "[L1] · turn.thinking.delta n=12",
      }),
    ).toBe(false);
  });
});
