import { apiAuthHeaders, type TurnEvent } from "../api/client";

export type TurnStreamHandlers = {
  onEvent: (event: TurnEvent) => void;
  onError?: (error: Error) => void;
  onClose?: () => void;
};

const STREAM_END = new Set([
  "turn.completed",
  "turn.failed",
  "turn.cancelled",
  "approval.requested",
]);
const MAX_RECONNECT_ATTEMPTS = 8;
const BASE_RECONNECT_MS = 300;

export class TurnStreamClient {
  private abort: AbortController | null = null;
  private stopped = false;
  private lastSequence = 0;
  private turnId: string | null = null;
  private handlers: TurnStreamHandlers | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  connect(turnId: string, handlers: TurnStreamHandlers, sinceSequence = 0) {
    this.turnId = turnId;
    this.handlers = handlers;
    this.lastSequence = sinceSequence;
    this.reconnectAttempts = 0;
    void this.openStream(sinceSequence);
  }

  private streamUrl(sinceSequence: number): string {
    if (!this.turnId) return "";
    return sinceSequence > 0
      ? `/api/v1/turns/${this.turnId}/stream?since_sequence=${sinceSequence}`
      : `/api/v1/turns/${this.turnId}/stream`;
  }

  private async openStream(sinceSequence: number) {
    this.abort?.abort();
    this.abort = new AbortController();
    this.stopped = false;
    if (!this.turnId || !this.handlers) return;

    try {
      const res = await fetch(this.streamUrl(sinceSequence), {
        headers: apiAuthHeaders({ Accept: "text/event-stream" }),
        signal: this.abort.signal,
      });
      if (!res.ok) {
        throw new Error(`SSE connection failed: ${res.status}`);
      }
      this.reconnectAttempts = 0;
      const reader = res.body?.getReader();
      if (!reader) {
        throw new Error("SSE response has no body");
      }

      const decoder = new TextDecoder();
      let buffer = "";
      while (!this.stopped) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          if (this.stopped) break;
          const dataLine = frame
            .split("\n")
            .find((line) => line.startsWith("data:"));
          if (!dataLine) continue;
          const data = JSON.parse(dataLine.slice(5).trim()) as TurnEvent;
          if (data.sequence > this.lastSequence) {
            this.lastSequence = data.sequence;
          }
          this.handlers?.onEvent(data);
          if (STREAM_END.has(data.type)) {
            this.close();
            this.handlers?.onClose?.();
            return;
          }
        }
      }
      if (!this.stopped) {
        this.handlers?.onClose?.();
      }
    } catch (err) {
      if (
        this.stopped ||
        (err instanceof DOMException && err.name === "AbortError")
      ) {
        return;
      }
      if (!this.turnId || !this.handlers) return;
      if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        this.handlers.onError?.(
          err instanceof Error ? err : new Error("SSE connection error"),
        );
        return;
      }
      const delay = BASE_RECONNECT_MS * 2 ** this.reconnectAttempts;
      this.reconnectAttempts += 1;
      this.reconnectTimer = setTimeout(() => {
        void this.openStream(this.lastSequence);
      }, delay);
    }
  }

  stopRendering() {
    this.stopped = true;
  }

  close() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.abort?.abort();
    this.abort = null;
  }
}
