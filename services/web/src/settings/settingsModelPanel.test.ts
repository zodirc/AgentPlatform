import { describe, expect, it } from "vitest";
import { nextModelPanelAfterListChange } from "./settingsModelPanel";

describe("nextModelPanelAfterListChange", () => {
  const ids = ["a", "b"];

  it("does not overwrite create after +添加 clears selectedId", () => {
    expect(
      nextModelPanelAfterListChange({
        isLoading: false,
        panelMode: "create",
        selectedId: null,
        providerIds: ids,
        activeId: "a",
      }),
    ).toBeNull();
  });

  it("selects the active profile on first load", () => {
    expect(
      nextModelPanelAfterListChange({
        isLoading: false,
        panelMode: "view",
        selectedId: null,
        providerIds: ids,
        activeId: "b",
      }),
    ).toEqual({ selectedId: "b", panelMode: "view" });
  });

  it("picks another profile after delete", () => {
    expect(
      nextModelPanelAfterListChange({
        isLoading: false,
        panelMode: "view",
        selectedId: null,
        providerIds: ["b"],
        activeId: null,
      }),
    ).toEqual({ selectedId: "b", panelMode: "view" });
  });
});
