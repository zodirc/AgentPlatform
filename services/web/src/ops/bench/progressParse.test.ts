import { describe, expect, it } from "vitest";

import { parseCodingLiveLine, parseProgressLine } from "./progressParse";

describe("parseProgressLine", () => {
  it("parses an L1 context plan", () => {
    expect(parseProgressLine("[L1] context plan n=20 parallel=2")).toEqual({
      kind: "eval",
      suite: "context",
      label: "L1 上下文计划 20 题 · 并行2",
      pct: 0,
      done: 0,
      total: 20,
      unit: "题",
    });
  });

  it("parses retrieval query progress with its dataset bucket", () => {
    expect(parseProgressLine("[L1] scifact queries 7/20")).toEqual({
      kind: "eval",
      suite: "retrieval",
      label: "L1 检索 scifact · 查询 7/20",
      pct: 35,
      done: 7,
      total: 20,
      unit: "查询",
      partKey: "scifact",
      parts: { scifact: { done: 7, total: 20 } },
      pipelineGap: false,
    });
  });

  it("ignores unrelated log lines", () => {
    expect(parseProgressLine("[ops] heartbeat")).toBeNull();
  });
});

describe("parseCodingLiveLine", () => {
  it("parses a completed coding case", () => {
    expect(
      parseCodingLiveLine(
        "[L1] coding 2/5 swebench__django-11039 status=pass bucket=patched patch_source=final",
      ),
    ).toEqual({
      kind: "case",
      case: {
        iid: "swebench__django-11039",
        status: "pass",
        bucket: "patched",
        patchSource: "final",
        steps: null,
        elapsedSec: null,
      },
    });
  });

  it("parses harness progress", () => {
    expect(
      parseCodingLiveLine(
        "[L1] coding harness progress done=3/5 pct=60 resolved=2 unresolved=1 error=0",
      ),
    ).toEqual({
      kind: "harness",
      harness: {
        phase: "running",
        done: 3,
        total: 5,
        n: 5,
        pct: 60,
        resolved: 2,
        unresolved: 1,
        error: 0,
        stage: "evaluating",
      },
    });
  });
});
