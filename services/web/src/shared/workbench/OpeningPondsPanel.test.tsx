import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OpeningPondsPanel } from "./OpeningPondsPanel";
import type { OpeningPondsArtifact } from "./openingPonds";

afterEach(cleanup);

const ponds: OpeningPondsArtifact = {
  type: "opening_ponds",
  items: [
    {
      id: "a",
      title: "早高峰系统",
      flavor: "白天把班上完",
      price: "换班一次扣一夜睡眠",
      opening: "闸机面板亮了，班被一张任务打断。",
      source_trust: "dubious",
      first_conflict_at: "first_300",
    },
    {
      id: "b",
      title: "窗口人情",
      flavor: "窗口里把日子过下去",
      price: "窗口人情少一顿",
    },
  ],
};

describe("OpeningPondsPanel", () => {
  it("lets the user check a card instead of sending a chat worksheet", () => {
    const onSelect = vi.fn();
    render(
      <OpeningPondsPanel
        ponds={ponds}
        interactive
        onSelect={onSelect}
        onMore={() => {}}
      />,
    );
    expect(screen.getByText("勾选一本要连载的书")).toBeTruthy();
    expect(screen.queryByText(/在玩什么/)).toBeNull();
    expect(screen.queryByText(/开篇怎么进/)).toBeNull();
    expect(screen.queryByText("对照轴不同的近池")).toBeNull();
    expect(screen.queryByRole("button", { name: "采用" })).toBeNull();
    const radio = screen.getByRole("radio", { name: "采用「早高峰系统」" });
    expect(radio.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(radio);
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("keeps the check on the chosen card after the picker settles", () => {
    render(<OpeningPondsPanel ponds={ponds} selectedTitle="窗口人情" />);
    expect(screen.getByText("窗口人情").closest("li")?.textContent).toContain(
      "✓",
    );
  });

  it("shows the book pitch and opening, not a bill/arc/flavor worksheet", () => {
    render(<OpeningPondsPanel ponds={ponds} />);
    expect(screen.getByText(/白天把班上完/)).toBeTruthy();
    expect(screen.queryByText("dubious")).toBeNull();
    expect(screen.queryByText("first_300")).toBeNull();
    const card = screen.getByText("早高峰系统").closest("li");
    expect(card).toBeTruthy();
    const text = card?.textContent ?? "";
    expect(text.indexOf("这本书")).toBeGreaterThan(-1);
    expect(text.indexOf("这本书")).toBeLessThan(text.indexOf("开篇"));
    expect(text).not.toContain("账单");
    expect(text).not.toContain("走向");
    expect(text).not.toContain("气味");
    expect(text).not.toContain("换班一次扣一夜睡眠");
  });

    it("keeps tonight's errand and job-bio who off the picker card", () => {
    render(
      <OpeningPondsPanel
        ponds={{
          ...ponds,
          items: [
            {
              ...ponds.items[0],
              want: "保住母亲的手术押金",
              who: "沈青禾",
              where: "冷链仓库",
            },
            ponds.items[1],
          ],
        }}
      />,
    );
    expect(screen.queryByText(/手术押金/)).toBeNull();
    expect(screen.queryByText("眼下要什么")).toBeNull();
    expect(screen.queryByText("沈青禾")).toBeNull();
    expect(screen.queryByText("跟着谁")).toBeNull();
    expect(screen.queryByText("冷链仓库")).toBeNull();
    expect(screen.queryByText("站在哪")).toBeNull();
  });
});
