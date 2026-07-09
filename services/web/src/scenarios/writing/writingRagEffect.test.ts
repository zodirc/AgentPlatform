import { describe, expect, it } from "vitest";
import {
  assessWritingRagEffect,
  extractCites,
  userNeedsSources,
} from "./writingRagEffect";

describe("userNeedsSources", () => {
  it("detects citation intent", () => {
    expect(userNeedsSources("根据 sources 写一段")).toBe(true);
    expect(userNeedsSources("请改第二节更简洁")).toBe(false);
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

  it("reports no_search when user asked but model did not search", () => {
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
      userMessage: "引用资料",
      turnBusy: false,
    });
    expect(result.status).toBe("no_cite");
  });
});
