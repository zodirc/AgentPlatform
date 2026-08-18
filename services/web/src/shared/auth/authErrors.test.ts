import { describe, expect, it } from "vitest";
import { ApiHttpError } from "../api/httpErrors";
import { messageForAuthFailure } from "./authErrors";

describe("messageForAuthFailure", () => {
  it("does not call a 502 a bad password", () => {
    const err = new ApiHttpError({ status: 502, detail: "bad gateway" });
    expect(messageForAuthFailure(err, "login")).toMatch(/服务暂时不可用/);
  });

  it("maps 401 to credentials", () => {
    const err = new ApiHttpError({ status: 401, detail: "Invalid credentials" });
    expect(messageForAuthFailure(err, "login")).toMatch(/用户名或密码/);
  });

  it("maps 429 to rate limit", () => {
    const err = new ApiHttpError({ status: 429, detail: "请求过多，请稍后重试" });
    expect(messageForAuthFailure(err, "login")).toMatch(/过多|频繁/);
  });

  it("maps a dropped connection", () => {
    expect(messageForAuthFailure(new TypeError("Failed to fetch"), "login")).toMatch(
      /无法连接/,
    );
  });
});
