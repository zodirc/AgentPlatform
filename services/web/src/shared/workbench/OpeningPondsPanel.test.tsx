import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OpeningPondsPanel } from "./OpeningPondsPanel";
import type { OpeningPondsArtifact } from "./openingPonds";

afterEach(cleanup);

const ponds: OpeningPondsArtifact = {
  type: "opening_ponds",
  items: [
    { id: "a", title: "早高峰系统", flavor: "白天把班上完" },
    { id: "b", title: "窗口人情", flavor: "窗口里把日子过下去" },
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
});
