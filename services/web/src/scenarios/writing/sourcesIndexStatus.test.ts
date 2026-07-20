import { describe, expect, it } from "vitest";

import {
  libraryIndexStatusLabel,
  sourcesIndexStatusLabel,
} from "./sourcesIndexStatus";

const path = "sources/ref-a.md";

describe("sourcesIndexStatusLabel", () => {
  it("describes pending async index work", () => {
    expect(sourcesIndexStatusLabel(path, { status: "pending" }, true)).toEqual({
      text: `已保存 ${path} · 等待后台投影…`,
      tone: "pending",
    });
  });

  it("describes an index build in progress", () => {
    expect(sourcesIndexStatusLabel(path, { status: "building" }, true)).toEqual(
      {
        text: `已保存 ${path} · 索引投影中…`,
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
      text: `已保存 ${path} · 投影失败：embedding unavailable`,
      tone: "err",
    });
  });

  it("reports projection ready without claiming effect gate", () => {
    expect(
      sourcesIndexStatusLabel(
        path,
        { status: "ready", path_current: true, chunks: 3 },
        false,
      ),
    ).toEqual({
      text: `已保存 ${path} · 投影就绪（3 块，可被检索） · 效果闸仍看 prod-bench / 难句`,
      tone: "ok",
    });
  });
});

describe("libraryIndexStatusLabel", () => {
  it("describes library sync in progress", () => {
    expect(libraryIndexStatusLabel({ status: "building" }, true)).toEqual({
      text: "资料库索引投影中（不挡对话）…",
      tone: "pending",
    });
  });

  it("reports ready library index as ingestion-only", () => {
    expect(
      libraryIndexStatusLabel(
        {
          status: "ready",
          indexed_files: 5,
          chunks: 17,
          embedding_backend: "sentence_transformers",
        },
        false,
      ),
    ).toEqual({
      text: "资料库投影就绪（摄取面） · 5 文件 · 17 块 · sentence_transformers · 效果闸仍看 prod-bench / 难句",
      tone: "ok",
    });
  });
});
