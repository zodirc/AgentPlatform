import { useEffect, useState } from "react";
import { ListTree } from "lucide-react";
import type { TurnEvent } from "../../shared/api/client";
import type { WorkbenchState } from "../../shared/workbench/types";
import {
  approvalCopy,
  lastApprovalEvent,
} from "../../shared/workbench/toolApproval";
import { UsageMeter } from "./UsageMeter";
import { livePlanStep } from "../../shared/workbench/plan";
import { formatTurnElapsed } from "./turnElapsed";

export type AgentPhase =
  | "idle"
  | "thinking"
  | "tool"
  | "approval"
  | "running"
  | "warning"
  | "completed"
  | "failed";

export type AgentActivity = {
  phase: AgentPhase;
  label: string;
  detail?: string;
};

function formatToolDetail(
  toolName: string,
  args: Record<string, unknown> | undefined,
): string {
  if (!args) return "";
  if (typeof args.path === "string") return args.path;
  if (typeof args.pattern === "string") return args.pattern;
  if (typeof args.command === "string") return args.command;
  if (typeof args.task === "string") return args.task.slice(0, 80);
  return "";
}

/** Refresh path: events may still be loading; tool_timeline already has status. */
function runningToolFromTimeline(
  view: WorkbenchState["view"],
): { toolName: string; detail?: string } | null {
  const timeline = view?.tool_timeline;
  if (!Array.isArray(timeline) || timeline.length === 0) return null;
  for (let i = timeline.length - 1; i >= 0; i -= 1) {
    const row = timeline[i] as Record<string, unknown>;
    if (String(row.status ?? "") !== "running") continue;
    const toolName = String(row.tool_name ?? "tool");
    const args = row.arguments as Record<string, unknown> | undefined;
    const detail = formatToolDetail(toolName, args);
    return { toolName, detail: detail || undefined };
  }
  return null;
}

export function deriveAgentActivity(
  events: TurnEvent[],
  wb: Pick<
    WorkbenchState,
    "busy" | "awaitingApproval" | "displayStatus" | "view" | "pendingToolName"
  >,
): AgentActivity {
  const last = events[events.length - 1];
  const runningTool = [...events].reverse().find((e) => {
    if (e.type !== "tool.started") return false;
    const id = String(e.payload.tool_call_id ?? "");
    const completed = events.some(
      (c) =>
        c.type === "tool.completed" &&
        String(c.payload.tool_call_id ?? "") === id &&
        c.sequence > e.sequence,
    );
    return !completed;
  });

  if (wb.displayStatus === "failed" || last?.type === "turn.failed") {
    const msg = String(
      last?.payload.message ?? wb.view?.latest_output ?? "任务失败",
    );
    return { phase: "failed", label: "任务失败", detail: msg };
  }
  if (wb.awaitingApproval) {
    const approvalEv = lastApprovalEvent(events);
    const tool = String(
      approvalEv?.payload.tool_name ?? wb.pendingToolName ?? "tool",
    );
    const args = approvalEv?.payload.arguments as
      | Record<string, unknown>
      | undefined;
    const copy = approvalCopy(tool);
    const path = String(
      (approvalEv?.payload.path as string | undefined) ?? args?.path ?? "",
    );
    const command = typeof args?.command === "string" ? args.command : "";
    const detail =
      tool === "run_command" && command
        ? command
        : path
          ? `${tool} → ${path}`
          : tool;
    return {
      phase: "approval",
      label: copy.title,
      detail,
    };
  }
  if (wb.displayStatus === "completed" || last?.type === "turn.completed") {
    const completed = [...events]
      .reverse()
      .find((event) => event.type === "turn.completed");
    const deliveryStatus = String(completed?.payload.delivery_status ?? "");
    if (deliveryStatus === "failed" || deliveryStatus === "warning") {
      const issues = completed?.payload.delivery_issues;
      const detail = Array.isArray(issues)
        ? issues.map(String).join("；")
        : undefined;
      return {
        phase: deliveryStatus === "failed" ? "failed" : "warning",
        label: "执行完成，交付异常",
        detail,
      };
    }
    return { phase: "completed", label: "任务已完成" };
  }
  if (runningTool) {
    const toolName = String(runningTool.payload.tool_name ?? "tool");
    const args = runningTool.payload.arguments as
      | Record<string, unknown>
      | undefined;
    const detail = formatToolDetail(toolName, args);
    return {
      phase: "tool",
      label: `正在执行 ${toolName}`,
      detail: detail || undefined,
    };
  }
  const fromTimeline = runningToolFromTimeline(wb.view);
  if (fromTimeline && (wb.busy || wb.displayStatus === "running")) {
    return {
      phase: "tool",
      label: `正在执行 ${fromTimeline.toolName}`,
      detail: fromTimeline.detail,
    };
  }
  const lastThinking = [...events]
    .reverse()
    .find((e) => e.type === "turn.thinking");
  if (wb.busy && lastThinking) {
    const step = lastThinking.payload.step_index;
    // Engine is 0-based; show 1-based rounds for humans.
    return {
      phase: "thinking",
      label: "模型思考中",
      detail:
        typeof step === "number" && Number.isFinite(step)
          ? `第 ${Number(step) + 1} 轮`
          : undefined,
    };
  }
  if (wb.busy) {
    return { phase: "running", label: "Agent 运行中" };
  }
  return { phase: "idle", label: "等待任务" };
}

const PHASE_STYLES: Record<AgentPhase, string> = {
  idle: "border-border/70 bg-card/40 text-foreground",
  thinking: "border-primary/30 bg-primary/8 text-foreground",
  tool: "border-success/30 bg-success-muted/80 text-foreground",
  approval: "border-primary/35 bg-primary/10 text-foreground",
  running: "border-warning/30 bg-warning-muted/80 text-foreground",
  warning: "border-warning/35 bg-warning-muted text-foreground",
  completed: "border-success/30 bg-success-muted/70 text-foreground",
  failed: "border-destructive/35 bg-destructive/10 text-foreground",
};

const PHASE_DOT: Record<AgentPhase, string> = {
  idle: "bg-muted-foreground/50",
  thinking: "bg-primary animate-pulse",
  tool: "bg-success",
  approval: "bg-primary animate-pulse",
  running: "bg-warning animate-pulse",
  warning: "bg-warning",
  completed: "bg-success",
  failed: "bg-destructive",
};

type Props = {
  wb: WorkbenchState;
  compact?: boolean;
  /** Open / toggle the tools timeline overlay drawer. */
  onOpenTools?: () => void;
  toolsOpen?: boolean;
  toolsCount?: number;
};

export function AgentActivityPanel({
  wb,
  compact = false,
  onOpenTools,
  toolsOpen = false,
  toolsCount = 0,
}: Props) {
  const activity = deriveAgentActivity(wb.events, wb);
  const live =
    wb.busy ||
    wb.awaitingApproval ||
    wb.displayStatus === "running" ||
    wb.displayStatus === "waiting_approval" ||
    wb.displayStatus === "pending";
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [live]);
  const startedAt = wb.turnHistory.find((t) => t.id === wb.turnId)?.created_at;
  const elapsedLabel =
    startedAt && (live || activity.phase === "completed" || activity.phase === "failed")
      ? `${live ? "已运行" : "用时"} ${formatTurnElapsed(
          (nowMs - Date.parse(startedAt)) / 1000,
        )}`
      : null;
  const style = PHASE_STYLES[activity.phase];
  const planStep = livePlanStep(wb.plan, wb.displayStatus);
  const pinnedCards = [...(wb.view?.artifacts ?? [])]
    .reverse()
    .find((a) => a.type === "writing_cards") as
    | {
        cards?: Array<{ title?: string; kind?: string }>;
      }
    | undefined;
  const cardTitles = Array.isArray(pinnedCards?.cards)
    ? pinnedCards.cards
        .map((c) => String(c.title ?? "").trim())
        .filter(Boolean)
        .slice(0, 4)
    : [];
  const debugTitle = [
    `status=${wb.displayStatus}`,
    wb.view?.last_event_sequence != null
      ? `seq=${wb.view.last_event_sequence}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section
      className={`min-w-0 shrink-0 overflow-hidden rounded-xl border px-3.5 py-2.5 ${style}`}
      title={debugTitle}
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0 flex-1 overflow-hidden">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${PHASE_DOT[activity.phase]}`}
              aria-hidden
            />
            <p
              className={
                compact
                  ? "truncate text-sm font-medium tracking-tight"
                  : "text-lg font-medium"
              }
            >
              {activity.label}
            </p>
            {elapsedLabel ? (
              <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
                {elapsedLabel}
              </span>
            ) : null}
          </div>
          {activity.detail ? (
            <p
              className="mt-0.5 truncate pl-3.5 text-xs text-muted-foreground"
              title={activity.detail}
            >
              {activity.detail}
            </p>
          ) : null}
          {planStep ? (
            <p
              className="mt-0.5 truncate pl-3.5 text-xs text-primary/90"
              title={planStep.title}
            >
              计划进行中：{planStep.title}
            </p>
          ) : null}
          {cardTitles.length > 0 ? (
            <p
              className="mt-1 truncate pl-3.5 text-xs text-primary/90"
              title={cardTitles.join(" · ")}
            >
              本轮写定：{cardTitles.join(" · ")}
            </p>
          ) : null}
        </div>
        {onOpenTools ? (
          <button
            type="button"
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors ${
              toolsOpen
                ? "border-primary/40 bg-primary/10 text-foreground"
                : "border-border/70 bg-background/50 text-muted-foreground hover:border-border hover:bg-muted hover:text-foreground"
            }`}
            onClick={onOpenTools}
            title={toolsOpen ? "收起工具时间线" : "打开工具时间线"}
            aria-pressed={toolsOpen}
          >
            <ListTree className="h-3.5 w-3.5" />
            工具
            {toolsCount > 0 ? (
              <span className="min-w-[1rem] rounded-md bg-primary/15 px-1 text-center tabular-nums text-primary">
                {toolsCount > 99 ? "99+" : toolsCount}
              </span>
            ) : null}
          </button>
        ) : null}
      </div>
      <UsageMeter
        contextUsage={wb.contextUsage}
        tokenUsage={wb.tokenUsage}
        compact={compact}
      />
    </section>
  );
}
