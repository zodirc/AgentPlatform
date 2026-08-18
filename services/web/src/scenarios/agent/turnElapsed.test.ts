import { describe, expect, it } from "vitest";
import { formatTurnElapsed } from "./turnElapsed";

describe("formatTurnElapsed", () => {
  it("formats minutes and seconds", () => {
    expect(formatTurnElapsed(5)).toBe("0:05");
    expect(formatTurnElapsed(65)).toBe("1:05");
    expect(formatTurnElapsed(3605)).toBe("1:00:05");
  });
});
