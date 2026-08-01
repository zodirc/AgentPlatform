import { beforeEach, describe, expect, it } from "vitest";
import { readSettingsReturn, rememberSettingsReturn } from "./settingsReturn";

describe("settingsReturn", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("remembers agent workbench and reads it back", () => {
    rememberSettingsReturn("/agent?session=11111111-1111-1111-1111-111111111111");
    expect(readSettingsReturn()).toBe(
      "/agent?session=11111111-1111-1111-1111-111111111111",
    );
  });

  it("ignores settings paths and falls back", () => {
    rememberSettingsReturn("/settings/model");
    expect(readSettingsReturn("/writing")).toBe("/writing");
  });
});
