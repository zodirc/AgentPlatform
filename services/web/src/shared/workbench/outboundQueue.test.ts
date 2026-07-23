import { describe, expect, it } from "vitest";
import { mergeOutboundQueue } from "./outboundQueue";

describe("mergeOutboundQueue", () => {
  it("joins trimmed messages with blank lines", () => {
    expect(mergeOutboundQueue(["a", "  b  ", "c"])).toBe("a\n\nb\n\nc");
  });

  it("drops empty entries", () => {
    expect(mergeOutboundQueue(["", " hi ", "  "])).toBe("hi");
  });

  it("returns empty string for empty queue", () => {
    expect(mergeOutboundQueue([])).toBe("");
  });
});
