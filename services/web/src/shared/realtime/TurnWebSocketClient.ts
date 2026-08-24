/**
 * 回合 WebSocket 流客户端：订阅 `/turns/:id/ws`，语义与 TurnStreamClient 对齐。
 * 审批暂停点 socket 会关闭，批准/拒绝须走 HTTP API。
 */
import type { TurnEvent } from "../api/client";

/** TurnWebSocketClient 事件回调集合。 */
export type TurnStreamHandlers = {
  onEvent: (event: TurnEvent) => void;
  onError?: (error: Error) => void;
  onClose?: () => void;
};

/** 回合正常结束的事件类型。 */
const TERMINAL = new Set(["turn.completed", "turn.failed", "turn.cancelled"]);

/** Stop 后冻结本地增量渲染，终端/控制事件仍派发（ADR-015）。 */
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

/**
 * WebSocket 传输的回合事件订阅（`?transport=ws` 时由 useWorkbench 选用）。
 */
export class TurnWebSocketClient {
  private socket: WebSocket | null = null;
  private stopped = false;
  private renderPaused = false;
  private lastSequence = 0;
  private turnId: string | null = null;
  private handlers: TurnStreamHandlers | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  /**
   * 打开 WebSocket 并绑定消息处理。
   * @param turnId 回合 ID
   * @param handlers 事件/错误/关闭回调
   * @param sinceSequence 断点续传起始 sequence（不含）
   */
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

  /**
   * ADR-015：≤50ms 停止本地 token/thinking/tool 渲染；连接保持以接收 turn.cancelled。
   */
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

  /** 标记 stopped 并关闭 socket 与重连定时器。 */
  close() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopped = true;
    this.closeSocketOnly();
  }
}
