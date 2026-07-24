import type { TurnEvent } from "../api/client";
import type { TimelineItem } from "./types";

export type SubagentStatus = "running" | "completed" | "cancelled" | "failed";

export type SubagentLive = {
  subagent_id: string;
  agent_type: string;
  task: string;
  status: SubagentStatus;
  summary?: string;
  thinkingText: string;
  streamText: string;
  tools: TimelineItem[];
};

function emptySubagent(
  id: string,
  agentType: string,
  task: string,
): SubagentLive {
  return {
    subagent_id: id,
    agent_type: agentType,
    task,
    status: "running",
    thinkingText: "",
    streamText: "",
    tools: [],
  };
}

/** Build nested readonly subagent cards from the live event stream. */
export function deriveSubagentsFromEvents(events: TurnEvent[]): SubagentLive[] {
  const map = new Map<string, SubagentLive>();
  const order: string[] = [];

  const ensure = (id: string, agentType = "explore", task = "") => {
    let cur = map.get(id);
    if (!cur) {
      cur = emptySubagent(id, agentType, task);
      map.set(id, cur);
      order.push(id);
    }
    return cur;
  };

  for (const ev of events) {
    if (ev.type === "subagent.started") {
      const id = String(ev.payload.subagent_id ?? "");
      if (!id) continue;
      const agentType = String(ev.payload.agent_type ?? "explore");
      const task = String(ev.payload.task ?? "");
      const existing = map.get(id);
      if (existing) {
        existing.agent_type = agentType;
        existing.task = task || existing.task;
        existing.status = "running";
      } else {
        ensure(id, agentType, task);
      }
      continue;
    }

    if (ev.type === "subagent.completed") {
      const id = String(ev.payload.subagent_id ?? "");
      if (!id) continue;
      const cur = ensure(
        id,
        String(ev.payload.agent_type ?? "explore"),
        "",
      );
      cur.summary =
        typeof ev.payload.summary === "string" ? ev.payload.summary : cur.summary;
      const summaryLower = String(cur.summary ?? "").toLowerCase();
      if (summaryLower.includes("cancel")) {
        cur.status = "cancelled";
      } else {
        cur.status = "completed";
      }
      continue;
    }

    const sid =
      typeof ev.payload.subagent_id === "string"
        ? ev.payload.subagent_id
        : "";
    if (!sid) continue;
    const cur = ensure(sid);

    if (ev.type === "turn.thinking.delta") {
      const delta = String(ev.payload.delta ?? "");
      if (delta) cur.thinkingText += delta;
    } else if (ev.type === "turn.thinking") {
      if (cur.thinkingText.trim()) {
        cur.thinkingText = `${cur.thinkingText.trimEnd()}\n\n`;
      }
    } else if (ev.type === "turn.token") {
      cur.streamText += String(ev.payload.delta ?? "");
    } else if (ev.type === "tool.started") {
      const toolCallId = String(ev.payload.tool_call_id ?? "");
      const toolName = String(ev.payload.tool_name ?? "tool");
      if (!toolCallId) continue;
      if (cur.tools.some((t) => t.tool_call_id === toolCallId)) continue;
      cur.tools.push({
        tool_call_id: toolCallId,
        tool_name: toolName,
        status: "running",
        subagent_id: sid,
      });
    } else if (ev.type === "tool.completed") {
      const toolCallId = String(ev.payload.tool_call_id ?? "");
      const toolName = String(ev.payload.tool_name ?? "tool");
      const status = String(ev.payload.status ?? "ok");
      const summary =
        typeof ev.payload.summary === "string" ? ev.payload.summary : undefined;
      if (!toolCallId) continue;
      const idx = cur.tools.findIndex((t) => t.tool_call_id === toolCallId);
      if (idx < 0) {
        cur.tools.push({
          tool_call_id: toolCallId,
          tool_name: toolName,
          status,
          summary,
          subagent_id: sid,
        });
      } else {
        cur.tools[idx] = {
          ...cur.tools[idx],
          tool_name: toolName,
          status,
          summary,
          subagent_id: sid,
        };
      }
    } else if (ev.type === "tool.delta") {
      const toolCallId = String(ev.payload.tool_call_id ?? "");
      const delta = String(ev.payload.delta ?? "");
      if (!toolCallId || !delta) continue;
      const idx = cur.tools.findIndex((t) => t.tool_call_id === toolCallId);
      if (idx < 0) {
        cur.tools.push({
          tool_call_id: toolCallId,
          tool_name: String(ev.payload.tool_name ?? "tool"),
          status: "running",
          stream_output: delta,
          subagent_id: sid,
        });
      } else {
        cur.tools[idx] = {
          ...cur.tools[idx],
          stream_output: (cur.tools[idx].stream_output ?? "") + delta,
        };
      }
    }
  }

  return order.map((id) => map.get(id)!).filter(Boolean);
}

/** Fallback when events were not hydrated (older clients / partial views). */
export function deriveSubagentsFromView(
  view: {
    artifacts?: Array<Record<string, unknown>> | null;
    tool_timeline?: Array<Record<string, unknown>> | null;
  } | null,
): SubagentLive[] {
  if (!view) return [];
  const map = new Map<string, SubagentLive>();
  const order: string[] = [];

  const ensure = (id: string, agentType = "explore", task = "") => {
    let cur = map.get(id);
    if (!cur) {
      cur = emptySubagent(id, agentType, task);
      map.set(id, cur);
      order.push(id);
    }
    return cur;
  };

  for (const art of view.artifacts ?? []) {
    if (art.type !== "subagent") continue;
    const id = String(art.subagent_id ?? "");
    if (!id) continue;
    const agentType = String(art.agent_type ?? "explore");
    const event = String(art.event ?? "");
    if (event === "subagent.started" || art.task) {
      const cur = ensure(id, agentType, String(art.task ?? ""));
      if (art.task) cur.task = String(art.task);
      cur.agent_type = agentType;
    }
    if (event === "subagent.completed" || art.summary) {
      const cur = ensure(id, agentType, "");
      if (typeof art.summary === "string") cur.summary = art.summary;
      const summaryLower = String(cur.summary ?? "").toLowerCase();
      cur.status = summaryLower.includes("cancel") ? "cancelled" : "completed";
    }
  }

  for (const row of view.tool_timeline ?? []) {
    const sid = typeof row.subagent_id === "string" ? row.subagent_id : "";
    if (!sid) continue;
    const cur = ensure(sid);
    const toolCallId = String(row.tool_call_id ?? "");
    if (!toolCallId) continue;
    if (cur.tools.some((t) => t.tool_call_id === toolCallId)) continue;
    cur.tools.push({
      tool_call_id: toolCallId,
      tool_name: String(row.tool_name ?? "tool"),
      status: String(row.status ?? "ok"),
      summary: typeof row.summary === "string" ? row.summary : undefined,
      stream_output:
        typeof row.stream_output === "string" ? row.stream_output : undefined,
      subagent_id: sid,
    });
  }

  return order.map((id) => map.get(id)!).filter(Boolean);
}

export function resolveSubagents(
  events: TurnEvent[],
  view: {
    artifacts?: Array<Record<string, unknown>> | null;
    tool_timeline?: Array<Record<string, unknown>> | null;
  } | null,
): SubagentLive[] {
  const fromEvents = deriveSubagentsFromEvents(events);
  if (fromEvents.length > 0) return fromEvents;
  return deriveSubagentsFromView(view);
}

export function parentTimelineItems(items: TimelineItem[]): TimelineItem[] {
  return items.filter((t) => !t.subagent_id);
}

export function statusLabel(status: SubagentStatus): string {
  if (status === "running") return "进行中";
  if (status === "completed") return "完成";
  if (status === "cancelled") return "已取消";
  return "失败";
}
