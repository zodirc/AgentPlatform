import { describe, expect, it } from "vitest";
import { tabFromPath } from "./settingsTabs";

describe("tabFromPath", () => {
  it("maps settings subpaths", () => {
    expect(tabFromPath("/settings")).toBe("account");
    expect(tabFromPath("/settings/model")).toBe("model");
    expect(tabFromPath("/settings/index")).toBe("index");
    expect(tabFromPath("/settings/allowlist")).toBe("allowlist");
    // Writing style sliders removed; legacy paths fall back to account.
    expect(tabFromPath("/settings/signals")).toBe("account");
    expect(tabFromPath("/settings/writing")).toBe("account");
  });
});
