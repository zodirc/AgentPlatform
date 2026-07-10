import { describe, expect, it } from "vitest";

import { sourcesIndexStatusLabel } from "./sourcesIndexStatus";

const path = "sources/ref-a.md";

describe("sourcesIndexStatusLabel", () => {
  it("describes pending async index work", () => {
    expect(sourcesIndexStatusLabel(path, { status: "pending" }, true)).toEqual({
      text: `已保存 ${path} · 等待后台索引…`,
      tone: "pending",
    });
  });

  it("describes an index build in progress", () => {
    expect(sourcesIndexStatusLabel(path, { status: "building" }, true)).toEqual(
      {
        text: `已保存 ${path} · 索引重建中…`,
        tone: "pending",
      },
    );
  });

  it("surfaces index failures", () => {
    expect(
      sourcesIndexStatusLabel(
        path,
        { status: "error", error: "embedding unavailable" },
        false,
      ),
    ).toEqual({
      text: `已保存 ${path} · 索引失败：embedding unavailable`,
      tone: "err",
    });
  });

  it("reports a current index as searchable", () => {
    expect(
      sourcesIndexStatusLabel(
        path,
        { status: "ready", path_current: true, chunks: 3 },
        false,
      ),
    ).toEqual({
      text: `已保存 ${path} · 索引完成，可检索（3 块）`,
      tone: "ok",
    });
  });
});
