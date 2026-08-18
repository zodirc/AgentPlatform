import { useEffect, useState } from "react";

export function formatTurnElapsed(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

export type TimedEvent = {
  type: string;
  sequence?: number;
  ts?: string;
  payload: Record<string, unknown>;
};

export function parseEventTsMs(event: TimedEvent | undefined): number | null {
  if (!event?.ts) return null;
  const ms = Date.parse(event.ts);
  return Number.isFinite(ms) ? ms : null;
}

function toolCallIdOf(event: TimedEvent): string {
  return String(event.payload.tool_call_id ?? "");
}

export function findToolStarted(
  events: TimedEvent[],
  toolCallId: string,
): TimedEvent | undefined {
  if (!toolCallId) return undefined;
  return events.find(
    (event) => event.type === "tool.started" && toolCallIdOf(event) === toolCallId,
  );
}

export function findToolCompleted(
  events: TimedEvent[],
  toolCallId: string,
  startedSequence?: number,
): TimedEvent | undefined {
  if (!toolCallId) return undefined;
  return events.find((event) => {
    if (event.type !== "tool.completed") return false;
    if (toolCallIdOf(event) !== toolCallId) return false;
    if (typeof startedSequence !== "number") return true;
    return typeof event.sequence === "number" && event.sequence > startedSequence;
  });
}

/** Seconds this tool call has been (or was) running. Null when start ts is unknown. */
export function toolCallElapsedSeconds(
  events: TimedEvent[],
  toolCallId: string,
  nowMs: number,
): number | null {
  const started = findToolStarted(events, toolCallId);
  const startedMs = parseEventTsMs(started);
  if (startedMs == null) return null;
  const completed = findToolCompleted(events, toolCallId, started?.sequence);
  const endedMs = parseEventTsMs(completed) ?? nowMs;
  return (endedMs - startedMs) / 1000;
}

export type LiveRunningTool = {
  toolCallId: string;
  toolName: string;
  detail: string;
  startedMs: number | null;
};

function formatToolDetail(args: Record<string, unknown> | undefined): string {
  if (!args) return "";
  if (typeof args.command === "string") return args.command;
  if (typeof args.path === "string") return args.path;
  if (typeof args.pattern === "string") return args.pattern;
  if (typeof args.query === "string") return args.query;
  if (typeof args.task === "string") return args.task;
  return "";
}

/** Latest tool.started that still has no later tool.completed. */
export function liveRunningTool(events: TimedEvent[]): LiveRunningTool | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (event?.type !== "tool.started") continue;
    const toolCallId = toolCallIdOf(event);
    if (!toolCallId) continue;
    const completed = findToolCompleted(events, toolCallId, event.sequence);
    if (completed) continue;
    const args = event.payload.arguments as Record<string, unknown> | undefined;
    return {
      toolCallId,
      toolName: String(event.payload.tool_name ?? "tool"),
      detail: formatToolDetail(args),
      startedMs: parseEventTsMs(event),
    };
  }
  return null;
}

const localStarts = new Map<string, number>();

/** Prefer event ts; if missing (live stream without ts), start from first sight. */
export function resolveStartedMs(
  toolCallId: string,
  eventTsMs: number | null,
  nowMs: number,
): number {
  if (eventTsMs != null) {
    if (toolCallId) localStarts.delete(toolCallId);
    return eventTsMs;
  }
  if (!toolCallId) return nowMs;
  const prev = localStarts.get(toolCallId);
  if (prev != null) return prev;
  localStarts.set(toolCallId, nowMs);
  return nowMs;
}

export function useTickingNow(enabled: boolean): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [enabled]);
  return nowMs;
}
