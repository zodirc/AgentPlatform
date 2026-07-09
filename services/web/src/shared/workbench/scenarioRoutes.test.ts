import { describe, expect, it } from "vitest";
import { isScenarioId, scenarioFromPathname } from "./scenarioRoutes";

describe("scenarioRoutes", () => {
  it("parses scenario paths", () => {
    expect(scenarioFromPathname("/writing")).toBe("writing");
    expect(scenarioFromPathname("/agent")).toBe("agent");
    expect(scenarioFromPathname("/interview")).toBe("interview");
    expect(scenarioFromPathname("/settings")).toBeNull();
  });

  it("validates scenario ids", () => {
    expect(isScenarioId("writing")).toBe(true);
    expect(isScenarioId("settings")).toBe(false);
  });
});
