import { describe, expect, it } from "vitest";
import {
  filterSlashCommands,
  slashQueryFromInput,
} from "./slashCommands";

describe("slashQueryFromInput", () => {
  it("opens on bare slash", () => {
    expect(slashQueryFromInput("/")).toBe("");
    expect(slashQueryFromInput("  /")).toBe("");
  });

  it("captures partial command names", () => {
    expect(slashQueryFromInput("/hel")).toBe("hel");
    expect(slashQueryFromInput("/compact")).toBe("compact");
  });

  it("closes after whitespace (args / normal prose)", () => {
    expect(slashQueryFromInput("/polish ")).toBeNull();
    expect(slashQueryFromInput("/polish now")).toBeNull();
    expect(slashQueryFromInput("hello")).toBeNull();
    expect(slashQueryFromInput("say /help")).toBeNull();
  });
});

describe("filterSlashCommands", () => {
  it("filters by scenario", () => {
    const writing = filterSlashCommands("", "writing").map((c) => c.id);
    expect(writing).toContain("polish");
    expect(writing).toContain("outline");
    expect(writing).not.toContain("test");

    const agent = filterSlashCommands("", "agent").map((c) => c.id);
    expect(agent).toContain("test");
    expect(agent).toContain("lint");
    expect(agent).not.toContain("polish");
  });

  it("filters by prefix query", () => {
    const hits = filterSlashCommands("ver", "writing").map((c) => c.id);
    expect(hits).toEqual(["version", "verify"]);
  });
});
