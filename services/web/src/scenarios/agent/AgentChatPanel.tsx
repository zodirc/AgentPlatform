import { useEffect, useRef } from "react";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import {
  approvalCopy,
  lastApprovalEvent,
} from "../../shared/workbench/toolApproval";
import { onChatEnterSend } from "../../shared/workbench/chatKeyboard";
import { placeholderForScenario } from "../../shared/workbench/useWorkbench";
import { scenarioMeta } from "../../shared/workbench/scenarioMeta";
import { PlanPanel } from "../../shared/workbench/PlanPanel";
import { livePlanStep } from "../../shared/workbench/plan";
import type { TurnHistoryItem, WorkbenchState } from "../../shared/workbench/types";

type Props = {
  wb: WorkbenchState;
};

/** Stay pinned to bottom unless the user scrolled up more than this (px). */
const STICK_THRESHOLD_PX = 80;

function assistantText(wb: WorkbenchState, turn: TurnHistoryItem): string {
  if (turn.id === wb.turnId) {
    return (
      wb.streamText ||
      wb.sectionDraft ||
      wb.view?.latest_output ||
      turn.latest_output ||
      ""
    );
  }
  return turn.latest_output ?? "";
}

export function AgentChatPanel({ wb }: Props) {
  const pendingApprovalEvent = lastApprovalEvent(wb.events);
  const pendingArgs = pendingApprovalEvent?.payload.arguments as
    | Record<string, unknown>
    | undefined;
  const approval = approvalCopy(wb.pendingToolName);
  const meta = scenarioMeta(wb.scenarioId);
  const turnScenario = wb.view?.scenario_id;
  const currentStep = livePlanStep(wb.plan, wb.displayStatus);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const endRef = useRef<HTMLDivElement>(null);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distance <= STICK_THRESHOLD_PX;
  };

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    endRef.current?.scrollIntoView({ block: "end" });
  }, [
    wb.turnHistory.length,
    wb.streamText,
    wb.sectionDraft,
    wb.view?.latest_output,
    wb.busy,
    wb.displayStatus,
    wb.awaitingApproval,
    wb.historyLoading,
    wb.plan?.items?.length,
  ]);

  useEffect(() => {
    if (!wb.busy) return;
    stickToBottomRef.current = true;
    endRef.current?.scrollIntoView({ block: "end" });
  }, [wb.turnId, wb.busy]);

  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-border bg-background">
      <header className="shrink-0 border-b border-border px-4 py-3">
        <p className="text-xs uppercase tracking-wide text-primary">
          {meta.chatEyebrow}
        </p>
        <h1 className="text-sm font-semibold text-foreground">{wb.title}</h1>
        <p className="text-xs text-muted-foreground">
          下一条 scenario_id={wb.scenarioId}
          {turnScenario && turnScenario !== wb.scenarioId
            ? ` · 当前轮=${turnScenario}`
            : ""}
          {wb.sessionId ? ` · session=${wb.sessionId.slice(0, 8)}` : ""}
          {wb.useWebSocket ? " · ws" : ""}
          {wb.planMode ? " · Plan" : ""}
          {wb.planPhase === "ready"
            ? " · 待同意"
            : wb.planPhase === "executing"
              ? " · 执行中"
              : wb.planPhase === "planning" && wb.busy
                ? " · 规划中"
                : ""}
        </p>
      </header>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4"
      >
        {wb.historyLoading ? (
          <p className="text-xs text-muted-foreground/80">正在加载会话历史…</p>
        ) : null}
        {wb.turnHistory.map((turn) => {
          const output = assistantText(wb, turn);
          return (
            <div key={turn.id} className="mb-4 space-y-2">
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  你
                  <span className="ml-2 text-muted-foreground/80">{turn.scenario_id}</span>
                </p>
                <p className="rounded-lg bg-card px-3 py-2 text-sm text-foreground">
                  {turn.user_input}
                </p>
              </div>
              {output ? (
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">助手</p>
                  <pre className="whitespace-pre-wrap rounded-lg bg-card/60 px-3 py-2 text-xs text-foreground/90">
                    {output}
                  </pre>
                </div>
              ) : turn.id === wb.turnId && wb.busy ? (
                <p className="text-xs text-muted-foreground">思考中…</p>
              ) : null}
            </div>
          );
        })}
        {!wb.historyLoading && wb.turnHistory.length === 0 ? (
          <p className="text-xs text-muted-foreground/80">发送消息开始任务…</p>
        ) : null}
        {(wb.view || wb.busy) && wb.turnId ? (
          <p className="mt-3 text-xs text-muted-foreground/80">
            status={wb.displayStatus}
            {wb.view ? ` · seq=${wb.view.last_event_sequence}` : ""}
            {` · turn=${wb.turnId.slice(0, 8)}`}
            {currentStep ? ` · 计划：${currentStep.title}` : ""}
          </p>
        ) : null}
        <div ref={endRef} aria-hidden className="h-px w-full" />
      </div>

      {wb.awaitingApproval ? (
        <div className="shrink-0 border-t border-primary/30 bg-primary/10 p-4">
          <p className="text-sm font-medium text-primary">
            {approval.title}
          </p>
          <p className="mb-2 text-xs text-muted-foreground">{approval.description}</p>
          {wb.pendingWriteFile ? (
            <div className="mb-2">
              <WriteFileDiffPanel
                preview={wb.pendingWriteFile}
                mode="approval"
              />
            </div>
          ) : null}
          {wb.pendingToolName === "run_command" && pendingArgs?.command ? (
            <pre className="mb-2 max-h-32 overflow-auto rounded bg-background p-2 text-xs text-warning">
              $ {String(pendingArgs.command)}
            </pre>
          ) : null}
          <div className="flex gap-2">
            <Button
              size="sm"
              className="bg-success text-success-foreground hover:bg-success/90"
              disabled={wb.actionBusy || !wb.pendingToolCallId}
              onClick={() => void wb.handleApprove()}
            >
              {approval.approveLabel}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={wb.actionBusy || !wb.pendingToolCallId}
              onClick={() => void wb.handleDeny()}
            >
              拒绝
            </Button>
          </div>
        </div>
      ) : null}

      <div className="shrink-0 space-y-2 border-t border-border p-4">
        {wb.plan?.items?.length ? (
          <PlanPanel
            plan={wb.plan}
            turnStatus={wb.displayStatus}
            planPhase={wb.planPhase}
            showExecute={wb.canExecutePlan}
            executeDisabled={wb.busy || wb.actionBusy}
            onExecute={() => void wb.handleExecutePlan()}
            compact
          />
        ) : null}
        {wb.showPlanSuggest ? (
          <div className="flex items-start justify-between gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-[11px] text-warning">
            <div className="min-w-0 space-y-0.5">
              <p>建议先切到 Plan，列出步骤再执行（可忽略）。</p>
              {wb.planSuggestReason ? (
                <p className="text-warning/80">{wb.planSuggestReason}</p>
              ) : null}
            </div>
            <div className="flex shrink-0 gap-1">
              <button
                type="button"
                className="rounded bg-warning px-2 py-0.5 text-warning-foreground hover:bg-warning/90"
                onClick={() => wb.setPlanMode(true)}
              >
                切换 Plan
              </button>
              <button
                type="button"
                className="rounded px-2 py-0.5 text-warning/80 hover:text-warning"
                onClick={() => wb.dismissPlanSuggest()}
              >
                忽略
              </button>
            </div>
          </div>
        ) : null}
        <Textarea
          className="min-h-[80px] resize-none text-sm"
          value={wb.message}
          onChange={(e) => wb.setMessage(e.target.value)}
          placeholder={placeholderForScenario(wb.scenarioId)}
          onKeyDown={(e) =>
            onChatEnterSend(
              e,
              () => void wb.handleSend(),
              !wb.busy && Boolean(wb.message.trim()),
            )
          }
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={wb.planMode ? "default" : "outline"}
            className={
              wb.planMode
                ? "bg-primary hover:bg-primary/90"
                : "border-primary/40 text-primary"
            }
            disabled={wb.busy}
            onClick={() => wb.setPlanMode(!wb.planMode)}
            title="Plan 模式：先规划，确认后再执行"
          >
            {wb.planMode ? "Plan · 开" : "Plan"}
          </Button>
          <Button
            size="sm"
            disabled={wb.busy || !wb.message.trim()}
            onClick={() => void wb.handleSend()}
          >
            发送
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-destructive/50 text-destructive"
            disabled={!wb.busy || wb.stopping}
            onClick={() => void wb.handleStop()}
          >
            {wb.stopping ? "停止中…" : "Stop"}
          </Button>
        </div>
      </div>
    </aside>
  );
}
