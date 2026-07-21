import { describe, expect, it, vi } from "vitest";
import { listSourcesLibraryFiles } from "./listSourcesLibraryFiles";

describe("listSourcesLibraryFiles", () => {
  it("recurses into subdirectories and skips .gitkeep", async () => {
    const listEntries = vi.fn(async (path: string) => {
      if (path === "sources") {
        return { entries: ["writing/", "seed/", "readme-top.md"] };
      }
      if (path === "sources/writing") {
        return { entries: ["liangjian.md", ".gitkeep"] };
      }
      if (path === "sources/seed") {
        return { entries: ["writing/"] };
      }
      if (path === "sources/seed/writing") {
        return { entries: ["dramas/"] };
      }
      if (path === "sources/seed/writing/dramas") {
        return { entries: ["drama1.md", ".gitkeep"] };
      }
      return { entries: [] };
    });

    const files = await listSourcesLibraryFiles(listEntries);
    expect(files).toEqual([
      "readme-top.md",
      "seed/writing/dramas/drama1.md",
      "writing/liangjian.md",
    ]);
  });
});
