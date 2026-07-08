import type { TurnEvent } from "../api/client";

export type TurnStreamHandlers = {
  onEvent: (event: TurnEvent) => void;
  onError?: (error: Error) => void;
  onClose?: () => void;
};

const TERMINAL = new Set(["turn.completed", "turn.failed", "turn.cancelled"]);
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
    this.close();
    this.stopped = false;
    if (!this.turnId || !this.handlers) return;

    this.socket = new WebSocket(wsUrl(this.turnId, sinceSequence));
    this.socket.onopen = () => {
      this.reconnectAttempts = 0;
    };
    this.socket.onmessage = (ev) => {
      if (this.stopped) return;
      const data = JSON.parse(String(ev.data)) as TurnEvent;
      if (data.sequence > this.lastSequence) {
        this.lastSequence = data.sequence;
      }
      this.handlers?.onEvent(data);
      if (TERMINAL.has(data.type)) {
        this.close();
        this.handlers?.onClose?.();
      }
    };
    this.socket.onerror = () => {
      if (this.stopped) return;
      this.handlers?.onError?.(new Error("WebSocket connection error"));
    };
    this.socket.onclose = () => {
      if (this.stopped) return;
      if (this.lastSequence <= 0 || !this.turnId || !this.handlers) return;
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

  approveToolCall(toolCallId: string) {
    this.socket?.send(
      JSON.stringify({ action: "approve_tool_call", tool_call_id: toolCallId }),
    );
  }

  denyToolCall(toolCallId: string, reason = "user_denied") {
    this.socket?.send(
      JSON.stringify({
        action: "deny_tool_call",
        tool_call_id: toolCallId,
        reason,
      }),
    );
  }

  stopRendering() {
    this.stopped = true;
  }

  close() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }
}
