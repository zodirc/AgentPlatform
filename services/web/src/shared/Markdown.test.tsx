import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renders plain text while streaming (no GFM heading)", () => {
    const { container } = render(
      <Markdown text={"# Title\n\nhello"} streaming />,
    );
    const root = container.querySelector("[data-streaming='true']");
    expect(root).not.toBeNull();
    expect(root?.textContent).toContain("# Title");
    expect(container.querySelector("h1")).toBeNull();
  });

  it("renders GFM when settled", () => {
    render(<Markdown text={"# Title"} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Title",
    );
  });
});
