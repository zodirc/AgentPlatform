import { describe, expect, it } from "vitest";
import {
  isSeedCorpusPath,
  isSeedRelUnderSources,
} from "./seedPath";

describe("seedPath", () => {
  it("detects sources/seed corpus paths", () => {
    expect(isSeedCorpusPath("sources/seed/writing/periods/periods1.md")).toBe(
      true,
    );
    expect(isSeedCorpusPath("sources/seed")).toBe(true);
    expect(isSeedCorpusPath("sources/note.md")).toBe(false);
    expect(isSeedCorpusPath(".")).toBe(false);
  });

  it("detects relative paths under sources/", () => {
    expect(isSeedRelUnderSources("seed/writing/dramas/drama8.md")).toBe(true);
    expect(isSeedRelUnderSources("paste-note.md")).toBe(false);
  });
});
