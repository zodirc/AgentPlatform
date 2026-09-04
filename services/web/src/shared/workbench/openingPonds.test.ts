import { describe, expect, it } from "vitest";

import {
  formatSelectPondMessage,
  latestOpeningPondsFromArtifacts,
  latestOpeningPondsFromEvents,
  normalizeOpeningPondsArtifact,
} from "./openingPonds";

const sample = {
  type: "opening_ponds",
  ponds_id: "ponds-1",
  summary: "三份",
  items: [
    {
      id: "a",
      title: "早高峰系统",
      who: "保安周石",
      where: "大堂闸机",
      want: "系统换班",
      chapter_job: "当场进场",
    },
    { id: "b", title: "午饭功法", who: "林浅", where: "食堂" },
  ],
};

describe("openingPonds", () => {
  it("normalizes artifacts and ignores a single item", () => {
    expect(normalizeOpeningPondsArtifact(sample)?.items).toHaveLength(2);
    expect(
      normalizeOpeningPondsArtifact({
        type: "opening_ponds",
        items: [{ id: "a", title: "only" }],
      }),
    ).toBeNull();
  });

  it("picks the latest opening_ponds artifact", () => {
    const found = latestOpeningPondsFromArtifacts([
      { type: "plan", items: [] },
      sample,
      {
        type: "opening_ponds",
        ponds_id: "ponds-2",
        items: [
          { id: "c", title: "第三份" },
          { id: "d", title: "第四份" },
        ],
      },
    ]);
    expect(found?.ponds_id).toBe("ponds-2");
    expect(found?.items?.[0]?.title).toBe("第三份");
  });

  it("picks opening.ponds from the event stream", () => {
    const found = latestOpeningPondsFromEvents([
      { type: "turn.token", payload: { delta: "x" } },
      { type: "opening.ponds", payload: sample },
    ]);
    expect(found?.items).toHaveLength(2);
    expect(found?.items?.[0]?.title).toBe("早高峰系统");
  });

  it("formats a select message with pond slots", () => {
    const msg = formatSelectPondMessage(sample.items[0]);
    expect(msg).toContain("按开篇候选「早高峰系统」写第一章");
    expect(msg).toContain("跟着谁：保安周石");
    expect(msg).toContain("眼下要什么：系统换班");
  });
});
