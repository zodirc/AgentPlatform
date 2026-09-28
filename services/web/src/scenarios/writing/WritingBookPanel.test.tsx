import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WritingBookPanel } from "./WritingBookPanel";

describe("WritingBookPanel", () => {
  it("renders the empty manuscript hint", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <WritingBookPanel revision="0" />
      </QueryClientProvider>,
    );
    expect(html).toContain("加载中");
  });

  it("renders manuscript, confirmed facts, and outline only", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryData(["writing-book", "1"], {
      title: "码头",
      empty: false,
      parts: [
        {
          key: "outline",
          label: "大纲",
          kind: "outline",
          chars: 8,
          text: "# 码头\n",
          path: "outline.md",
        },
        {
          key: "author_state",
          label: "作者手记",
          kind: "author_state",
          chars: 20,
          text: "这本书更冷了。",
        },
        {
          key: "canon",
          label: "已确认",
          kind: "canon",
          chars: 12,
          text: "- 规则（ch1）不许开车门",
          path: "confirmed.md",
        },
        {
          key: "manuscript",
          label: "正文",
          kind: "manuscript",
          chars: 40,
          text: "沈砚下了井。",
          path: "drafts/manuscript.md",
        },
      ],
      identity: { is: ["码头上的人"] },
      taste_marks: [{ kind: "yes", excerpt: "她没接话，把秤砣放回去。" }],
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <WritingBookPanel revision="1" />
      </QueryClientProvider>,
    );
    expect(html.indexOf("正文")).toBeLessThan(html.indexOf("已确认"));
    expect(html.indexOf("已确认")).toBeLessThan(html.indexOf("大纲"));
    expect(html).toContain("双击打开");
    expect(html).not.toContain("作者手记");
    expect(html).not.toContain("这本书更冷了");
    expect(html).not.toContain("口味标记");
    expect(html).not.toContain("秤砣放回去");
    expect(html).not.toContain("账本");
  });
});
