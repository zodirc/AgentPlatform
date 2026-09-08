import { describe, expect, it } from "vitest";

import {
  formatSelectPondMessage,
  latestOpeningPondsFromArtifacts,
  latestOpeningPondsFromEvents,
  normalizeOpeningPondsArtifact,
  pondContrastLine,
  pondPhysicsLine,
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
      start_kind: "granted_path",
      promise: "power_steps",
      opening: "早高峰闸机前，保安周石的班被一张看不懂的面板打断。",
      arc: "他先靠这面板把班撑住，后面才发现换班的代价会落到家里。",
      flavor: "白天写字楼里把班上完的升级日常",
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

  it("shows the book pitch before who/where on the card line", () => {
    expect(pondPhysicsLine(sample.items[0])).toBe(
      "早高峰系统 · 白天写字楼里把班上完的升级日常",
    );
    expect(pondPhysicsLine({ id: "x", title: "无轴" })).toBe("");
    expect(pondContrastLine(sample.items)).toBe(
      "早高峰系统·白天写字楼里把班上完的升级日常",
    );
    expect(
      pondContrastLine([
        sample.items[0],
        {
          id: "b",
          title: "窗口",
          flavor: "窗口里把日子过下去",
          start_kind: "no_extraordinary",
          promise: "survive_relation",
        },
      ]),
    ).toBe(
      "早高峰系统·白天写字楼里把班上完的升级日常 ｜ 窗口·窗口里把日子过下去",
    );
  });

  it("formats a select message with pond slots", () => {
    const msg = formatSelectPondMessage(sample.items[0]);
    expect(msg).toContain("按开篇候选「早高峰系统」写第一章");
    expect(msg).toContain("风格：白天写字楼里把班上完的升级日常");
    expect(msg).toContain("开篇：早高峰闸机前");
    expect(msg).toContain("走向：他先靠这面板把班撑住");
    expect(msg).toContain("跟着谁：保安周石");
    expect(msg).toContain("眼下要什么：系统换班");
  });
});
