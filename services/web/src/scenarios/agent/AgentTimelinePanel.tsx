import type { TurnEvent } from "../../shared/api/client";
import type { TimelineItem } from "../../shared/workbench/types";

type Props = {
  items: TimelineItem[];
  events?: TurnEvent[];
  selectedIndex?: number | null;
  onSelectItem?: (item: TimelineItem, index: number) => void;
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
      Record<string, unknown> | undefined;
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
  }
  const summary = item.summary ?? "";
  const pathMatch = summary.match(/"path":\s*"([^"]+)"/);
  if (pathMatch) return `${name}(${pathMatch[1]})`;
  if (summary.startsWith("Wrote ")) return `${name} → ${summary.slice(6)}`;
  return name;
}

export function AgentTimelinePanel({
  items,
  events = [],
  selectedIndex = null,
  onSelectItem,
}: Props) {
  return (
    <section className="flex h-full flex-col rounded-lg border border-slate-800 bg-slate-900/40">
      <h2 className="shrink-0 border-b border-slate-800 px-4 py-3 text-sm font-medium text-slate-300">
        工具时间线
        {items.length > 0 ? (
          <span className="ml-2 text-xs font-normal text-slate-500">
            {items.length} 步
          </span>
        ) : null}
      </h2>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4">
        {items.length === 0 ? (
          <p className="text-xs text-slate-500">暂无工具调用</p>
        ) : (
          <ol className="space-y-2">
            {items.map((item, idx) => {
              const status = String(item.status ?? "pending");
              const isRunning = status === "running";
              const isSelected = selectedIndex === idx;
              const clickable = Boolean(onSelectItem);
              return (
                <li key={String(item.tool_call_id ?? idx)}>
                  <button
                    type="button"
                    disabled={!clickable}
                    className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                      isSelected
                        ? "border-sky-700/60 bg-sky-950/30"
                        : isRunning
                          ? "border-amber-700/50 bg-amber-950/20"
                          : status === "error" || status === "denied"
                            ? "border-rose-800/50 bg-rose-950/20"
                            : "border-slate-800 bg-slate-950"
                    } ${clickable ? "cursor-pointer hover:border-slate-600" : "cursor-default"}`}
                    onClick={() => onSelectItem?.(item, idx)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-slate-200">
                        {toolLabel(item, events)}
                      </span>
                      <span className="text-slate-500">{status}</span>
                    </div>
                    {item.stream_output ? (
                      <pre className="mt-2 max-h-20 overflow-auto whitespace-pre-wrap text-slate-400">
                        {item.stream_output}
                      </pre>
                    ) : null}
                    {item.summary && !item.stream_output ? (
                      <p className="mt-1 line-clamp-2 text-slate-500">
                        {String(item.summary)}
                      </p>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}
