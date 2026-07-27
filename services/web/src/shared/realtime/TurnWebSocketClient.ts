import type { TurnEvent } from "../api/client";

export type TurnStreamHandlers = {
  onEvent: (event: TurnEvent) => void;
  onError?: (error: Error) => void;
  onClose?: () => void;
};

const TERMINAL = new Set(["turn.completed", "turn.failed", "turn.cancelled"]);

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

function wsUrl(turnId: string, sinceSequence: number): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = `${proto}//${window.location.host}/api/v1/turns/${turnId}/ws`;
  return sinceSequence > 0 ? `${base}?since_sequence=${sinceSequence}` : base;
}

export class TurnWebSocketClient {
  private socket: WebSocket | null = null;
  private stopped = false;
  private renderPaused = false;
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
    this.openSocket(sinceSequence);
  }

  private openSocket(sinceSequence: number) {
    this.closeSocketOnly();
    this.stopped = false;
    this.renderPaused = false;
    if (!this.turnId || !this.handlers) return;

    this.socket = new WebSocket(wsUrl(this.turnId, sinceSequence));
    this.socket.onopen = () => {
      this.reconnectAttempts = 0;
    };
    this.socket.onmessage = (ev) => {
      if (this.stopped) return;
      let data: TurnEvent;
      try {
        data = JSON.parse(String(ev.data)) as TurnEvent;
      } catch {
        return;
      }
      if (
        typeof data.sequence === "number" &&
        data.sequence <= this.lastSequence
      ) {
        return;
      }
      if (typeof data.sequence === "number") {
        this.lastSequence = data.sequence;
      }
      if (this.renderPaused && RENDER_PAUSE_TYPES.has(data.type)) {
        return;
      }
      this.handlers?.onEvent(data);
      if (TERMINAL.has(data.type) || data.type === "approval.requested") {
        this.stopped = true;
        this.close();
        this.handlers?.onClose?.();
      }
    };
    // Transient errors are followed by onclose, which drives reconnect.
    // Do not surface onError here — that falsely clears busy mid-turn.
    this.socket.onerror = () => undefined;
    this.socket.onclose = () => {
      if (this.stopped) return;
      if (!this.turnId || !this.handlers) return;
      if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        this.handlers.onError?.(new Error("WebSocket connection lost"));
        return;
      }
      const delay = BASE_RECONNECT_MS * 2 ** this.reconnectAttempts;
      this.reconnectAttempts += 1;
      this.reconnectTimer = setTimeout(() => {
        this.openSocket(this.lastSequence);
      }, delay);
    };
  }

  // Approvals go over the HTTP API: the socket closes at the approval pause
  // point, so socket-based approve/deny would be a silent no-op.

  /** ADR-015: stop local render ≤50ms; keep listening for turn.cancelled. */
  stopRendering() {
    this.renderPaused = true;
  }

  /** Close socket without marking stopped — used when opening a replacement. */
  private closeSocketOnly() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.onmessage = null;
      this.socket.close();
      this.socket = null;
    }
  }

  close() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopped = true;
    this.closeSocketOnly();
  }
}
