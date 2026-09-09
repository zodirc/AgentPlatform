import { describe, expect, it } from "vitest";

import {
  MORE_PONDS_MESSAGE,
  formatSelectPondMessage,
  isOpeningChoiceMessage,
  latestOpeningPondsFromArtifacts,
  latestOpeningPondsFromEvents,
  normalizeOpeningPondsArtifact,
  openingChoiceFromUserInput,
  pondContrastLine,
  pondItemSelected,
  pondPhysicsLine,
  turnHidesUserInput,
  visibleChatUserInputs,
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

  it("formats a select message as a short choice, not the card", () => {
    const msg = formatSelectPondMessage(sample.items[0]);
    expect(msg).toBe("采用此开篇「早高峰系统」");
    expect(msg).not.toContain("跟着谁");
    expect(msg).not.toContain("开篇：");
  });

  it("sends 我要其他的 as a short choice, not a worksheet", () => {
    expect(MORE_PONDS_MESSAGE).toBe("我要其他的");
    expect(MORE_PONDS_MESSAGE).not.toContain("start_kind");
    expect(MORE_PONDS_MESSAGE).not.toContain("这几个都不合适");
  });

  it("treats pond checks as hidden chat tokens", () => {
    expect(openingChoiceFromUserInput("采用此开篇「早高峰系统」")).toEqual({
      kind: "commit",
      title: "早高峰系统",
    });
    expect(
      openingChoiceFromUserInput("按开篇候选「早高峰系统」写第一章。"),
    ).toEqual({ kind: "commit", title: "早高峰系统" });
    expect(openingChoiceFromUserInput("我要其他的")).toEqual({ kind: "more" });
    expect(
      openingChoiceFromUserInput("这几个都不合适。再给 2～3 个开篇候选。"),
    ).toEqual({ kind: "more" });
    expect(openingChoiceFromUserInput("采用此开篇「《借来的灵根》」")).toEqual({
      kind: "commit",
      title: "《借来的灵根》",
    });
    expect(turnHidesUserInput({ user_input: "采用此开篇「《借来的灵根》」" })).toBe(
      true,
    );
    expect(
      turnHidesUserInput({ user_input: "写修真", hideUserInput: true }),
    ).toBe(true);
    expect(isOpeningChoiceMessage("写一章长篇修真，我看看")).toBe(false);
    expect(pondItemSelected(sample.items[0], "早高峰系统")).toBe(true);
    expect(
      visibleChatUserInputs([
        "写修真",
        "采用此开篇「早高峰系统」",
        "我要其他的",
      ]),
    ).toEqual(["写修真"]);
  });
});
