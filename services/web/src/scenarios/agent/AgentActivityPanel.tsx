import type { TurnEvent } from "../../shared/api/client";
import type { WorkbenchState } from "../../shared/workbench/types";
import {
  approvalCopy,
  lastApprovalEvent,
} from "../../shared/workbench/toolApproval";
import { UsageMeter } from "./UsageMeter";
import { currentPlanStep } from "../../shared/workbench/plan";

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
  if (wb.awaitingApproval || last?.type === "approval.requested") {
    const approvalEv = lastApprovalEvent(events);
    const tool = String(
      approvalEv?.payload.tool_name ?? wb.pendingToolName ?? "tool",
    );
    const args = approvalEv?.payload.arguments as
      Record<string, unknown> | undefined;
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
      Record<string, unknown> | undefined;
    const detail = formatToolDetail(toolName, args);
    return {
      phase: "tool",
      label: `正在执行 ${toolName}`,
      detail: detail || undefined,
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
  idle: "border-slate-700 bg-slate-900/50 text-slate-300",
  thinking: "border-sky-800/60 bg-sky-950/30 text-sky-200",
  tool: "border-emerald-800/60 bg-emerald-950/30 text-emerald-200",
  approval: "border-violet-800/60 bg-violet-950/30 text-violet-200",
  running: "border-amber-800/60 bg-amber-950/30 text-amber-200",
  warning: "border-amber-800/60 bg-amber-950/30 text-amber-200",
  completed: "border-emerald-800/60 bg-emerald-950/20 text-emerald-200",
  failed: "border-rose-800/60 bg-rose-950/30 text-rose-200",
};

type Props = {
  wb: WorkbenchState;
  compact?: boolean;
};

export function AgentActivityPanel({ wb, compact = false }: Props) {
  const activity = deriveAgentActivity(wb.events, wb);
  const style = PHASE_STYLES[activity.phase];
  const planStep = currentPlanStep(wb.plan);
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

  return (
    <section className={`shrink-0 rounded-lg border px-4 py-3 ${style}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-wide opacity-70">当前状态</p>
          <p
            className={
              compact ? "text-base font-medium" : "text-lg font-medium"
            }
          >
            {activity.label}
          </p>
          {activity.detail ? (
            <p className="mt-0.5 truncate text-sm opacity-80">
              {activity.detail}
            </p>
          ) : null}
          {planStep ? (
            <p className="mt-0.5 truncate text-sm text-violet-200/90">
              计划进行中：{planStep.title}
            </p>
          ) : null}
          {cardTitles.length > 0 ? (
            <p className="mt-1 truncate text-xs text-teal-300/90">
              本轮写定：{cardTitles.join(" · ")}
            </p>
          ) : null}
        </div>
        <div className="text-right text-xs opacity-60">
          <p>status={wb.displayStatus}</p>
          {wb.view?.last_event_sequence != null ? (
            <p>seq={wb.view.last_event_sequence}</p>
          ) : null}
        </div>
      </div>
      <UsageMeter contextUsage={wb.contextUsage} tokenUsage={wb.tokenUsage} />
    </section>
  );
}
