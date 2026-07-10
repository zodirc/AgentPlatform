import { describe, expect, it } from "vitest";
import {
  assessWritingRagEffect,
  extractCites,
  userNeedsSources,
} from "./writingRagEffect";

describe("userNeedsSources", () => {
  it("detects evidence-backed drafting intent", () => {
    expect(userNeedsSources("根据 sources 写一段")).toBe(true);
    expect(userNeedsSources("根据资料写开场并标注引用")).toBe(true);
    expect(userNeedsSources("引用资料写一节")).toBe(true);
    expect(userNeedsSources("请改第二节更简洁")).toBe(false);
  });

  it("does not treat library meta-questions as citation intent", () => {
    expect(userNeedsSources("你对我们的资料库有什么理解？")).toBe(false);
    expect(userNeedsSources("资料库里有什么")).toBe(false);
    expect(userNeedsSources("介绍一下 sources 目录")).toBe(false);
  });
});

describe("extractCites", () => {
  it("finds cite markers", () => {
    expect(extractCites("见 [cite:ref-a] 与 [cite:ref-b]")).toEqual([
      "[cite:ref-a]",
      "[cite:ref-b]",
    ]);
  });
});

describe("assessWritingRagEffect", () => {
  it("reports effective when hits and cites present", () => {
    const result = assessWritingRagEffect({
      view: {
        status: "completed",
        artifacts: [
          { type: "retrieval", query: "q", mode: "keyword", hit_count: 1 },
        ],
        latest_output: "内容 [cite:ref-a]",
      } as never,
      streamText: "",
      sectionDraft: "",
      userMessage: "引用资料写作",
      turnBusy: false,
    });
    expect(result.status).toBe("effective");
    expect(result.cites).toContain("[cite:ref-a]");
  });

  it("treats library understanding as not_needed without search", () => {
    const result = assessWritingRagEffect({
      view: { status: "completed", artifacts: [], tool_timeline: [] } as never,
      streamText: "资料库有亮剑素材",
      sectionDraft: "",
      userMessage: "你对我们的资料库有什么理解？",
      turnBusy: false,
    });
    expect(result.status).toBe("not_needed");
  });

  it("reports no_search when drafting intent but model did not search", () => {
    const result = assessWritingRagEffect({
      view: { status: "completed", artifacts: [], tool_timeline: [] } as never,
      streamText: "",
      sectionDraft: "",
      userMessage: "根据资料写",
      turnBusy: false,
    });
    expect(result.status).toBe("no_search");
  });

  it("reports no_cite when hits but no cite in output", () => {
    const result = assessWritingRagEffect({
      view: {
        status: "completed",
        artifacts: [
          { type: "retrieval", query: "q", mode: "keyword", hit_count: 2 },
        ],
        latest_output: "写了但没引用",
      } as never,
      streamText: "",
      sectionDraft: "",
      userMessage: "引用资料写一节",
      turnBusy: false,
    });
    expect(result.status).toBe("no_cite");
  });
});
