import { describe, expect, it } from "vitest";

import { previewText } from "./filePreview";

describe("previewText", () => {
  it("truncates long content", () => {
    const long = "x".repeat(9000);
    const result = previewText(long, { charLimit: 8000, lineLimit: 500 });
    expect(result.truncated).toBe(true);
    expect(result.text.length).toBeLessThan(9000);
    expect(result.totalChars).toBe(9000);
  });

  it("keeps short content intact", () => {
    const result = previewText("hello\nworld");
    expect(result.truncated).toBe(false);
    expect(result.text).toBe("hello\nworld");
    expect(result.totalLines).toBe(2);
  });
});
