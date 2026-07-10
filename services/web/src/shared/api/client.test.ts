import { describe, expect, it } from "vitest";

import { API_BASE, sourceFilenameFromTitle } from "./client";

describe("api client", () => {
  it("uses relative API base", () => {
    expect(API_BASE).toBe("/api/v1");
  });

  it("builds safe sources filenames from paste titles", () => {
    expect(sourceFilenameFromTitle("")).toBe("paste-note.md");
    expect(sourceFilenameFromTitle("  树状数组笔记  ")).toBe("树状数组笔记.md");
    expect(sourceFilenameFromTitle("ref a.md")).toBe("ref-a.md");
    expect(sourceFilenameFromTitle("../evil")).toBe("evil.md");
  });
});
