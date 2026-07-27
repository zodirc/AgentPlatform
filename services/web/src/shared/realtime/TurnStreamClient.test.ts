import { describe, expect, it, vi } from "vitest";
import { TurnStreamClient } from "./TurnStreamClient";

function sseFrame(event: Record<string, unknown>): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

describe("TurnStreamClient", () => {
  it("supports optimistic stop without throwing", () => {
    const client = new TurnStreamClient();
    expect(() => client.stopRendering()).not.toThrow();
    client.close();
  });

  it("clears reconnect timer on close", () => {
    const client = new TurnStreamClient();
    (
      client as unknown as {
        reconnectTimer: ReturnType<typeof setTimeout> | null;
      }
    ).reconnectTimer = setTimeout(() => undefined, 10_000);
    client.close();
    expect(
      (client as unknown as { reconnectTimer: unknown }).reconnectTimer,
    ).toBeNull();
  });

  it("stopRendering freezes deltas but still dispatches turn.cancelled", async () => {
    const encoder = new TextEncoder();
    let pullCount = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pullCount += 1;
        if (pullCount === 1) {
          controller.enqueue(
            encoder.encode(
              sseFrame({
                type: "turn.token",
                sequence: 1,
                payload: { delta: "hello" },
              }),
            ),
          );
          return;
        }
        if (pullCount === 2) {
          controller.enqueue(
            encoder.encode(
              sseFrame({
                type: "turn.thinking.delta",
                sequence: 2,
                payload: { delta: "think" },
              }) +
                sseFrame({
                  type: "turn.cancelled",
                  sequence: 3,
                  payload: { reason: "user_requested" },
                }),
            ),
          );
          return;
        }
        controller.close();
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        body: stream,
      }),
    );

    const client = new TurnStreamClient();
    const events: string[] = [];
    const closed = new Promise<void>((resolve) => {
      client.connect("turn-1", {
        onEvent: (ev) => {
          events.push(ev.type);
          if (ev.type === "turn.token") {
            client.stopRendering();
          }
        },
        onClose: () => resolve(),
      });
    });

    await closed;
    expect(events).toEqual(["turn.token", "turn.cancelled"]);
    client.close();
    vi.unstubAllGlobals();
  });

  it("skips duplicate sequences on reconnect replay", async () => {
    const encoder = new TextEncoder();
    let pullCount = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pullCount += 1;
        if (pullCount === 1) {
          controller.enqueue(
            encoder.encode(
              sseFrame({
                type: "turn.token",
                sequence: 1,
                payload: { delta: "a" },
              }) +
                sseFrame({
                  type: "turn.token",
                  sequence: 1,
                  payload: { delta: "dup" },
                }) +
                sseFrame({
                  type: "turn.completed",
                  sequence: 2,
                  payload: {},
                }),
            ),
          );
          return;
        }
        controller.close();
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        body: stream,
      }),
    );

    const client = new TurnStreamClient();
    const events: Array<{ type: string; sequence: number }> = [];
    const closed = new Promise<void>((resolve) => {
      client.connect("turn-dup", {
        onEvent: (ev) => {
          events.push({ type: ev.type, sequence: ev.sequence });
        },
        onClose: () => resolve(),
      });
    });

    await closed;
    expect(events).toEqual([
      { type: "turn.token", sequence: 1 },
      { type: "turn.completed", sequence: 2 },
    ]);
    client.close();
    vi.unstubAllGlobals();
  });

  it("reconnects after clean disconnect without terminal event", async () => {
    vi.useFakeTimers();
    const encoder = new TextEncoder();
    let fetchCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () => {
        fetchCount += 1;
        if (fetchCount === 1) {
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(
                encoder.encode(
                  sseFrame({
                    type: "turn.token",
                    sequence: 1,
                    payload: { delta: "hi" },
                  }),
                ),
              );
              controller.close();
            },
          });
          return { ok: true, body: stream };
        }
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                sseFrame({
                  type: "turn.completed",
                  sequence: 2,
                  payload: {},
                }),
              ),
            );
            controller.close();
          },
        });
        return { ok: true, body: stream };
      }),
    );

    const client = new TurnStreamClient();
    const events: string[] = [];
    const closed = new Promise<void>((resolve) => {
      client.connect("turn-reconnect", {
        onEvent: (ev) => events.push(ev.type),
        onClose: () => resolve(),
      });
    });

    await vi.advanceTimersByTimeAsync(0);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(300);
    await closed;

    expect(fetchCount).toBeGreaterThanOrEqual(2);
    expect(events).toEqual(["turn.token", "turn.completed"]);
    client.close();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});
