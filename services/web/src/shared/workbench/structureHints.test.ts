import { describe, expect, it } from "vitest";
import { structureHints } from "./structureHints";

describe("structureHints (docs/28 PX2)", () => {
  it("flags empty text", () => {
    expect(structureHints("   ").map((h) => h.code)).toContain("empty_document");
  });

  it("flags heading skip and placeholders", () => {
    const text = `# Title\n\n### Skipped\n\nTODO fix me\n`;
    const codes = structureHints(text).map((h) => h.code);
    expect(codes).toContain("heading_skip");
    expect(codes).toContain("placeholder");
  });

  it("flags empty section under ##", () => {
    const text = `## A\n\nbody\n\n## B\n\n`;
    expect(structureHints(text).map((h) => h.code)).toContain("empty_section");
  });

  it("returns empty for clean prose", () => {
    const text = `## 一\n\n正文一段。\n\n## 二\n\n另一段。\n`;
    expect(structureHints(text)).toEqual([]);
  });
});
