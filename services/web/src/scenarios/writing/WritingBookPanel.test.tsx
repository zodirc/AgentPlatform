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

  it("renders author notes, taste marks, and ledger", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryData(["writing-book", "1"], {
      title: "码头",
      empty: false,
      parts: [
        {
          key: "author_state",
          label: "作者手记",
          kind: "author_state",
          chars: 20,
          text: "# 作者态\n## 我现在怎么看这本书\n这本书更冷了。\n## 回读记\n第 5 章写歪了。",
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
    expect(html).toContain("作者手记");
    expect(html).toContain("这本书更冷了");
    expect(html).toContain("回读记");
    expect(html).toContain("口味标记");
    expect(html).toContain("秤砣放回去");
    expect(html).toContain("账本");
  });
});
