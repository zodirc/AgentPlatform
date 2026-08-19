import { describe, expect, it } from "vitest";
import {
  collectCachedDescendants,
  collectDescendantPaths,
  dropCheckedUnder,
  expandPathsForReveal,
  isPathChecked,
  parseWorkspaceListing,
  uncheckAncestors,
  uncheckFileKeepingSiblings,
  writtenWorkspacePathsFromTurn,
} from "./workspaceTreeSelect";

describe("parseWorkspaceListing", () => {
  it("drops harness internals and keeps nested files", () => {
    const children = parseWorkspaceListing(".", [
      "drafts/",
      ".agent/",
      "outline.md",
      "__pycache__/",
    ]);
    expect(children.map((c) => c.path)).toEqual(["drafts", "outline.md"]);
    expect(children.find((c) => c.path === "drafts")?.isDir).toBe(true);
  });
});

describe("collectDescendantPaths", () => {
  it("selects nested files when a directory is checked", async () => {
    const listing: Record<string, string[]> = {
      drafts: ["ch1.md", "notes/", "manuscript.md"],
      "drafts/notes": ["scratch.md"],
    };
    const { paths, dirs } = await collectDescendantPaths(
      async (path) => listing[path] ?? [],
      "drafts",
    );
    expect(dirs).toEqual(["drafts", "drafts/notes"]);
    expect(paths.sort()).toEqual([
      "drafts/ch1.md",
      "drafts/manuscript.md",
      "drafts/notes",
      "drafts/notes/scratch.md",
    ]);
  });

  it("skips seed corpus under a selected directory", async () => {
    const { paths } = await collectDescendantPaths(async (path) => {
      if (path === "sources") return ["seed/", "mine.md"];
      if (path === "sources/seed") return ["writing/"];
      return [];
    }, "sources");
    expect(paths).toEqual(["sources/mine.md"]);
  });
});

describe("dropCheckedUnder / uncheckAncestors / inherit", () => {
  it("treats files under a checked directory as checked immediately", () => {
    const checked = new Set(["drafts"]);
    expect(isPathChecked(checked, "drafts")).toBe(true);
    expect(isPathChecked(checked, "drafts/manuscript.md")).toBe(true);
    expect(isPathChecked(checked, "drafts/notes/a.md")).toBe(true);
    expect(isPathChecked(checked, "exports/out.md")).toBe(false);
  });

  it("selects already-listed children without waiting for a refetch", () => {
    const listing: Record<string, string[]> = {
      drafts: ["manuscript.md", "notes/"],
      "drafts/notes": ["scratch.md"],
    };
    const { paths } = collectCachedDescendants(
      (dir) => listing[dir],
      "drafts",
    );
    expect(paths.sort()).toEqual([
      "drafts/manuscript.md",
      "drafts/notes",
      "drafts/notes/scratch.md",
    ]);
  });

  it("unchecking a file keeps siblings when the parent directory was the only checked node", () => {
    const listing: Record<string, string[]> = {
      drafts: ["a.md", "b.md"],
    };
    const next = uncheckFileKeepingSiblings(
      new Set(["drafts"]),
      "drafts/a.md",
      (dir) => listing[dir],
    );
    expect(next.has("drafts")).toBe(false);
    expect(next.has("drafts/a.md")).toBe(false);
    expect(next.has("drafts/b.md")).toBe(true);
  });
  it("unchecking a directory drops every nested path", () => {
    const next = dropCheckedUnder(
      new Set(["drafts", "drafts/a.md", "drafts/notes", "exports/out.md"]),
      "drafts",
    );
    expect([...next]).toEqual(["exports/out.md"]);
  });

  it("unchecking a file drops ancestor directories so parent delete cannot swallow it", () => {
    const next = uncheckAncestors(
      new Set(["drafts", "drafts/notes", "drafts/notes/a.md", "drafts/b.md"]),
      "drafts/notes/a.md",
    );
    expect(next.has("drafts/notes/a.md")).toBe(false);
    expect(next.has("drafts/notes")).toBe(false);
    expect(next.has("drafts")).toBe(false);
    expect(next.has("drafts/b.md")).toBe(true);
  });
});

describe("writtenWorkspacePathsFromTurn", () => {
  it("picks up export and write paths without waiting for a manual refresh", () => {
    const paths = writtenWorkspacePathsFromTurn({
      artifacts: [
        { type: "file_write", path: "notes/idea.md" },
        { type: "outline", path: "outline.md" },
      ],
      events: [
        {
          type: "tool.started",
          payload: {
            tool_call_id: "c1",
            tool_name: "draft_section",
            arguments: { path: "drafts/manuscript.md" },
          },
        },
        {
          type: "tool.completed",
          payload: {
            tool_call_id: "c1",
            tool_name: "draft_section",
            status: "ok",
          },
        },
        {
          type: "tool.completed",
          payload: {
            tool_call_id: "c2",
            tool_name: "export_document",
            status: "ok",
            output_path: "exports/潮汐失物所.md",
          },
        },
        {
          type: "tool.completed",
          payload: {
            tool_call_id: "c3",
            tool_name: "read_file",
            status: "ok",
            path: "sources/seed/a.md",
          },
        },
      ],
    });
    expect(paths.sort()).toEqual([
      "drafts/manuscript.md",
      "exports/潮汐失物所.md",
      "notes/idea.md",
      "outline.md",
    ]);
  });
});

describe("expandPathsForReveal", () => {
  it("expands ancestors so a new export file is visible", () => {
    expect(expandPathsForReveal(["exports/潮汐失物所.md"])).toEqual(
      expect.arrayContaining([".", "exports", "exports/潮汐失物所.md"]),
    );
  });
});
