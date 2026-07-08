import { describe, expect, it } from "vitest";
import { TurnStreamClient } from "./TurnStreamClient";

describe("TurnStreamClient", () => {
  it("supports optimistic stop without throwing", () => {
    const client = new TurnStreamClient();
    expect(() => client.stopRendering()).not.toThrow();
    client.close();
  });

  it("clears reconnect timer on close", () => {
    const client = new TurnStreamClient();
    (client as unknown as { reconnectTimer: ReturnType<typeof setTimeout> | null }).reconnectTimer =
      setTimeout(() => undefined, 10_000);
    client.close();
    expect((client as unknown as { reconnectTimer: unknown }).reconnectTimer).toBeNull();
  });
});
