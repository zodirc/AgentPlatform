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

  it("includes embed progress detail when present", () => {
    expect(
      libraryIndexStatusLabel(
        {
          status: "building",
          progress: {
            phase: "embed",
            chunks_embedded: 519,
            chunks_total: 10674,
            rate_chunks_per_s: 8.2,
            eta_s: 1200,
          },
        },
        true,
      ),
    ).toEqual({
      text: "资料库投影中（不挡对话）· 嵌入向量 · 块 519/10674 · 8.2/s · 剩余 约 20 min",
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
