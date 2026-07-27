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

/** Deltas frozen on Stop (ADR-015); terminal / control events still dispatch. */
const RENDER_PAUSE_TYPES = new Set([
  "turn.token",
  "turn.thinking",
  "turn.thinking.delta",
  "tool.delta",
  "section.draft.delta",
]);

const MAX_RECONNECT_ATTEMPTS = 8;
const BASE_RECONNECT_MS = 300;
// I17: server pings every ~14s while idle; if nothing arrives for this long
// the proxy has silently hung the connection — drop it and reconnect.
const IDLE_WATCHDOG_MS = 45_000;

export class TurnStreamClient {
  private abort: AbortController | null = null;
  private stopped = false;
  private renderPaused = false;
  private lastSequence = 0;
  private turnId: string | null = null;
  private handlers: TurnStreamHandlers | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private onlineListener: (() => void) | null = null;

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

  private scheduleReconnect() {
    if (!this.turnId || !this.handlers || this.stopped) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      this.handlers.onError?.(new Error("SSE connection closed unexpectedly"));
      // I15: retries exhausted (likely offline). Re-attach automatically once
      // the browser reports connectivity instead of requiring a full reload.
      this.armOnlineReattach();
      return;
    }
    const delay = BASE_RECONNECT_MS * 2 ** this.reconnectAttempts;
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      void this.openStream(this.lastSequence);
    }, delay);
  }

  private armOnlineReattach() {
    if (this.onlineListener || typeof window === "undefined") return;
    this.onlineListener = () => {
      this.disarmOnlineReattach();
      if (this.stopped || !this.turnId) return;
      this.reconnectAttempts = 0;
      void this.openStream(this.lastSequence);
    };
    window.addEventListener("online", this.onlineListener);
  }

  private disarmOnlineReattach() {
    if (this.onlineListener && typeof window !== "undefined") {
      window.removeEventListener("online", this.onlineListener);
    }
    this.onlineListener = null;
  }

  private async openStream(sinceSequence: number) {
    this.abort?.abort();
    this.abort = new AbortController();
    this.stopped = false;
    this.renderPaused = false;
    if (!this.turnId || !this.handlers) return;

    try {
      const res = await fetch(this.streamUrl(sinceSequence), {
        credentials: "include",
        headers: apiAuthHeaders({ Accept: "text/event-stream" }),
        signal: this.abort.signal,
      });
      if (!res.ok) {
        throw new Error(`SSE connection failed: ${res.status}`);
      }
      this.reconnectAttempts = 0;
      this.disarmOnlineReattach();
      const reader = res.body?.getReader();
      if (!reader) {
        throw new Error("SSE response has no body");
      }

      // I17: reader.read() blocks forever if a proxy hangs the connection
      // without closing it; the server ping (~14s idle) makes silence a
      // reliable death signal.
      const readWithWatchdog = async () => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        const timeout = new Promise<never>((_, reject) => {
          timer = setTimeout(
            () => reject(new Error("SSE idle timeout")),
            IDLE_WATCHDOG_MS,
          );
        });
        try {
          return await Promise.race([reader.read(), timeout]);
        } finally {
          clearTimeout(timer);
        }
      };

      const decoder = new TextDecoder();
      let buffer = "";
      while (!this.stopped) {
        const { done, value } = await readWithWatchdog();
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
          let data: TurnEvent;
          try {
            data = JSON.parse(dataLine.slice(5).trim()) as TurnEvent;
          } catch {
            continue;
          }
          // Skip duplicates / replays; still advance only on newer sequences.
          if (
            typeof data.sequence === "number" &&
            data.sequence <= this.lastSequence
          ) {
            continue;
          }
          if (typeof data.sequence === "number") {
            this.lastSequence = data.sequence;
          }
          // Advance cursor even when paused so reconnect does not replay tokens.
          if (this.renderPaused && RENDER_PAUSE_TYPES.has(data.type)) {
            continue;
          }
          this.handlers?.onEvent(data);
          if (STREAM_END.has(data.type)) {
            this.stopped = true;
            this.close();
            this.handlers?.onClose?.();
            return;
          }
        }
      }
      // Clean disconnect without a terminal/pause event — treat as drop and reconnect.
      if (!this.stopped) {
        this.scheduleReconnect();
      }
    } catch (err) {
      if (
        this.stopped ||
        (err instanceof DOMException && err.name === "AbortError")
      ) {
        return;
      }
      this.scheduleReconnect();
    }
  }

  /** ADR-015: stop local render ≤50ms; keep listening for turn.cancelled. */
  stopRendering() {
    this.renderPaused = true;
  }

  close() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.disarmOnlineReattach();
    this.stopped = true;
    this.abort?.abort();
    this.abort = null;
  }
}
