/** Frontend copy for pull-dispatch maturity errors. */

import { describe, expect, it } from "vitest";
import {
  ApiHttpError,
  formatSendFailure,
  turnFailureUserMessage,
} from "./httpErrors";

describe("turnFailureUserMessage", () => {
  it("maps start_timeout and runner_lost", () => {
    expect(turnFailureUserMessage("start_timeout")).toMatch(/执行器|重试/);
    expect(turnFailureUserMessage("runner_lost")).toMatch(/断开|重试/);
  });

  it("prefers mapped reason over raw message", () => {
    expect(turnFailureUserMessage("start_timeout", "no runtime claimed")).toMatch(
      /执行器/,
    );
  });
});

describe("formatSendFailure", () => {
  it("includes retry-after for 429", () => {
    const err = new ApiHttpError({
      status: 429,
      detail: "系统繁忙，排队已满，请稍后重试",
      retryAfterSeconds: 5,
    });
    expect(formatSendFailure(err)).toContain("5s");
  });
});
