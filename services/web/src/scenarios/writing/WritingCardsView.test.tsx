import { describe, expect, it } from "vitest";
import { WritingCardsView } from "./WritingCardsView";
import { renderToStaticMarkup } from "react-dom/server";

describe("WritingCardsView", () => {
  it("renders pinned character cards", () => {
    const html = renderToStaticMarkup(
      WritingCardsView({
        artifacts: [
          {
            type: "writing_cards",
            cards: [
              {
                path: "sources/cards/characters/张白鹿.md",
                kind: "character",
                title: "张白鹿",
              },
            ],
            chars: 120,
            available_count: 1,
          },
        ],
      }),
    );
    expect(html).toContain("本轮写定");
    expect(html).toContain("张白鹿");
    expect(html).toContain("人物");
  });
});
