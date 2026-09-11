import { describe, expect, it } from "vitest";

import { isStaleChunkError } from "./staleChunkReload";

describe("isStaleChunkError", () => {
  it("matches Chrome's dynamic import miss", () => {
    expect(
      isStaleChunkError(
        new TypeError(
          "Failed to fetch dynamically imported module: http://192.168.25.139/assets/index-BR6KSmze.js",
        ),
      ),
    ).toBe(true);
  });

  it("ignores unrelated errors", () => {
    expect(isStaleChunkError(new Error("Network Error"))).toBe(false);
  });
});
