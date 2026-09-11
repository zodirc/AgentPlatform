import { describe, expect, it } from "vitest";
import { parsePrefs, serializePrefs } from "./writingPrefs";

describe("WritingSignalsModal prefs", () => {
  it("serializes a user-pinned author regime", () => {
    const raw = serializePrefs("auto", {}, "auto", "author");
    const parsed = parsePrefs(raw);
    expect(parsed.regime).toBe("author");
    expect(JSON.parse(raw).regime).toEqual({ value: "author", source: "user" });
  });

  it("keeps auto as default source so short works stay strict", () => {
    const raw = serializePrefs("auto", {}, "auto", "auto");
    expect(JSON.parse(raw).regime.source).toBe("default");
    expect(parsePrefs(raw).regime).toBe("auto");
  });
});
