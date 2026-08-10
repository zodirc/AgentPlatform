import { describe, expect, it } from "vitest";
import { opsApiErrorText, opsDisplayText } from "./opsDisplayText";

describe("opsDisplayText", () => {
  it("passes through strings", () => {
    expect(opsDisplayText("boom")).toBe("boom");
    expect(opsDisplayText("")).toBe("");
    expect(opsDisplayText("", "fb")).toBe("fb");
  });

  it("formats ErrorBody objects", () => {
    expect(
      opsDisplayText({
        code: "VALIDATION_ERROR",
        message: "Invalid request",
        details: { errors: [] },
      }),
    ).toBe("VALIDATION_ERROR: Invalid request");
  });

  it("unwraps nested error fields", () => {
    expect(
      opsDisplayText({
        error: { code: "X", message: "nope", details: {} },
      }),
    ).toBe("X: nope");
  });
});

describe("opsApiErrorText", () => {
  it("reads ErrorResponse envelope", () => {
    expect(
      opsApiErrorText(
        {
          data: null,
          error: {
            code: "HTTP_401",
            message: "Unauthorized",
            details: {},
          },
          meta: { request_id: "x" },
        },
        "fallback",
      ),
    ).toBe("HTTP_401: Unauthorized");
  });

  it("parses JSON text bodies", () => {
    expect(
      opsApiErrorText(
        JSON.stringify({
          error: { code: "E", message: "bad", details: {} },
        }),
        "fb",
      ),
    ).toBe("E: bad");
  });
});
