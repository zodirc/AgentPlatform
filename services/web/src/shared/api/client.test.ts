import { describe, expect, it } from "vitest";

import { API_BASE } from "./client";

describe("api client", () => {
  it("uses relative API base", () => {
    expect(API_BASE).toBe("/api/v1");
  });
});
