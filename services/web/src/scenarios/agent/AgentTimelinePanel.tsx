import type { TurnEvent } from "../../shared/api/client";
import type { SubagentLive } from "../../shared/workbench/subagents";
import { statusLabel } from "../../shared/workbench/subagents";
import type { TimelineItem } from "../../shared/workbench/types";

type Props = {
  items: TimelineItem[];
  events?: TurnEvent[];
  subagents?: SubagentLive[];
  selectedIndex?: number | null;
  onSelectItem?: (item: TimelineItem, index: number) => void;
  onOpenSubagent?: (subagentId: string) => void;
};

function toolLabel(item: TimelineItem, events: TurnEvent[] = []): string {
  const name = String(item.tool_name ?? "tool");
  const toolCallId = String(item.tool_call_id ?? "");
  if (toolCallId) {
    const started = events.find(
      (e) =>
        e.type === "tool.started" &&
        String(e.payload.tool_call_id ?? "") === toolCallId,
    );
    const args = started?.payload.arguments as
      | Record<string, unknown>
      | undefined;
    if (typeof args?.path === "string") return `${name}(${args.path})`;
    if (typeof args?.pattern === "string") return `${name}(${args.pattern})`;
    if (typeof args?.command === "string") {
      const cmd = args.command.slice(0, 40);
      return `${name}(${cmd}${args.command.length > 40 ? "…" : ""})`;
    }
    if (typeof args?.query === "string") {
      const q = args.query.slice(0, 48);
      return `${name}(${q}${args.query.length > 48 ? "…" : ""})`;
    }
    if (typeof args?.task === "string") {
      const t = args.task.slice(0, 40);
      return `${name}(${t}${args.task.length > 40 ? "…" : ""})`;
    }
  }
  const summary = item.summary ?? "";
  const pathMatch = summary.match(/"path":\s*"([^"]+)"/);
  if (pathMatch) return `${name}(${pathMatch[1]})`;
  if (summary.startsWith("Wrote ")) return `${name} → ${summary.slice(6)}`;
  return name;
}

function ToolRow({
  item,
  events,
  index,
  selected,
  onSelect,
  nested,
}: {
  item: TimelineItem;
  events: TurnEvent[];
  index: number | null;
  selected: boolean;
  onSelect?: (item: TimelineItem, index: number) => void;
  nested?: boolean;
}) {
  const status = String(item.status ?? "pending");
  const isRunning = status === "running";
  const clickable = Boolean(onSelect) && index != null;
  return (
    <li>
      <button
        type="button"
        disabled={!clickable}
        className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
          nested ? "ml-2 border-dashed" : ""
        } ${
          selected
            ? "border-primary/40 bg-primary/10"
            : isRunning
              ? "border-warning/40 bg-warning-muted"
              : status === "error" || status === "denied"
                ? "border-destructive/40 bg-destructive/10"
                : "border-border bg-background"
        } ${clickable ? "cursor-pointer hover:border-input" : "cursor-default"}`}
        onClick={() => {
          if (index != null) onSelect?.(item, index);
        }}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium text-foreground">
            {toolLabel(item, events)}
          </span>
          <span className="text-muted-foreground">{status}</span>
        </div>
        {item.stream_output ? (
          <pre className="mt-2 max-h-20 overflow-auto whitespace-pre-wrap text-muted-foreground">
            {item.stream_output}
          </pre>
        ) : null}
        {item.summary && !item.stream_output ? (
          <p className="mt-1 line-clamp-2 text-muted-foreground">
            {String(item.summary)}
          </p>
        ) : null}
      </button>
    </li>
  );
}

export function AgentTimelinePanel({
  items,
  events = [],
  subagents = [],
  selectedIndex = null,
  onSelectItem,
  onOpenSubagent,
}: Props) {
  const stepCount =
    items.length + subagents.reduce((n, s) => n + s.tools.length, 0);

  return (
    <section className="flex h-full flex-col rounded-lg border border-border bg-card/40">
      <h2 className="shrink-0 border-b border-border px-4 py-3 text-sm font-medium text-foreground/90">
        工具时间线
        {stepCount > 0 ? (
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {stepCount} 步
          </span>
        ) : null}
      </h2>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4">
        {stepCount === 0 ? (
          <p className="text-xs text-muted-foreground">暂无工具调用</p>
        ) : (
          <ol className="space-y-2">
            {items.map((item, idx) => (
              <ToolRow
                key={String(item.tool_call_id ?? idx)}
                item={item}
                events={events}
                index={idx}
                selected={selectedIndex === idx}
                onSelect={onSelectItem}
              />
            ))}
            {subagents.map((sub) => (
              <li key={sub.subagent_id} className="space-y-2">
                <button
                  type="button"
                  className="w-full rounded-lg border border-primary/25 bg-primary/5 px-3 py-2 text-left text-xs hover:border-primary/50"
                  onClick={() => onOpenSubagent?.(sub.subagent_id)}
                  disabled={!onOpenSubagent}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground">
                      子任务 · {sub.agent_type}
                    </span>
                    <span className="text-muted-foreground">
                      {statusLabel(sub.status)}
                    </span>
                  </div>
                  {sub.task ? (
                    <p className="mt-1 line-clamp-2 text-muted-foreground">
                      {sub.task}
                    </p>
                  ) : null}
                  {onOpenSubagent ? (
                    <p className="mt-1 text-[10px] text-primary/80">
                      在聊天标签中打开
                    </p>
                  ) : null}
                </button>
                {sub.tools.length > 0 ? (
                  <ol className="space-y-2">
                    {sub.tools.map((tool) => (
                      <ToolRow
                        key={String(tool.tool_call_id)}
                        item={tool}
                        events={events}
                        index={null}
                        selected={false}
                        nested
                      />
                    ))}
                  </ol>
                ) : (
                  <p className="ml-2 text-[11px] text-muted-foreground">
                    {sub.status === "running"
                      ? "子任务工具进行中…"
                      : "无工具步骤"}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
