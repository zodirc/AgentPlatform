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
});
