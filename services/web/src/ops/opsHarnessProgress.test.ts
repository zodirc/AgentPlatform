import { describe, expect, it } from "vitest";
import { harnessProgressView } from "./opsHarnessProgress";

describe("harnessProgressView", () => {
  it("advances done to match outcome postfix when tqdm bar lags", () => {
    const v = harnessProgressView({
      phase: "running",
      done: 3,
      total: 5,
      n: 5,
      pct: 60,
      resolved: 2,
      unresolved: 2,
      error: 0,
    });
    expect(v.done).toBe(4);
    expect(v.total).toBe(5);
    expect(v.pct).toBe(80);
    expect(v.resolved).toBe(2);
    expect(v.unresolved).toBe(2);
    expect(v.error).toBe(0);
  });

  it("keeps bar ahead when outcomes have not caught up", () => {
    const v = harnessProgressView({
      phase: "running",
      done: 2,
      total: 5,
      n: 5,
      pct: 40,
      resolved: 1,
      unresolved: 0,
      error: 0,
    });
    expect(v.done).toBe(2);
    expect(v.pct).toBe(40);
  });

  it("caps at total", () => {
    const v = harnessProgressView({
      phase: "running",
      done: 5,
      total: 5,
      n: 5,
      pct: 100,
      resolved: 2,
      unresolved: 3,
      error: 0,
    });
    expect(v.done).toBe(5);
    expect(v.pct).toBe(100);
  });
});
