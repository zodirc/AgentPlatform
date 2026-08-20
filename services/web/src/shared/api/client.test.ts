import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, deleteSessionsBulk, sourceFilenameFromTitle } from "./client";

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses relative API base", () => {
    expect(API_BASE).toBe("/api/v1");
  });

  it("rejects bulk-delete HTML stand-ins", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<!doctype html>", { status: 200 })),
    );
    await expect(deleteSessionsBulk(["00000000-0000-0000-0000-000000000001"])).rejects.toThrow(
      /unexpected response/,
    );
  });

  it("returns deleted and missing ids from bulk-delete", async () => {
    const gone = "00000000-0000-0000-0000-000000000001";
    const miss = "00000000-0000-0000-0000-000000000002";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ deleted: [gone], missing: [miss] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(deleteSessionsBulk([gone, miss])).resolves.toEqual({
      deleted: [gone],
      missing: [miss],
    });
  });

  it("builds safe sources filenames from paste titles", () => {
    expect(sourceFilenameFromTitle("")).toBe("paste-note.md");
    expect(sourceFilenameFromTitle("  树状数组笔记  ")).toBe("树状数组笔记.md");
    expect(sourceFilenameFromTitle("ref a.md")).toBe("ref-a.md");
    expect(sourceFilenameFromTitle("../evil")).toBe("evil.md");
  });
});
