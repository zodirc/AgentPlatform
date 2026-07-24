import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import {
  approvalCopy,
  lastApprovalEvent,
} from "../../shared/workbench/toolApproval";
import { onChatEnterSend } from "../../shared/workbench/chatKeyboard";
import { placeholderForScenario } from "../../shared/workbench/useWorkbench";
import { SCENARIO_META } from "../../shared/workbench/scenarioMeta";
import { PlanPanel } from "../../shared/workbench/PlanPanel";
import { livePlanStep } from "../../shared/workbench/plan";
import { pathWithSession } from "../../shared/workbench/sessionUrl";
import { statusLabel } from "../../shared/workbench/subagents";
import type { SubagentLive } from "../../shared/workbench/subagents";
import type {
  ScenarioId,
  TurnHistoryItem,
  WorkbenchState,
} from "../../shared/workbench/types";

type Props = {
  wb: WorkbenchState;
  /** Open a nested subagent chat tab (from timeline). */
  openSubagentRequest?: string | null;
  onOpenSubagentHandled?: () => void;
};

type ChatTab = "main" | string;

const STICK_THRESHOLD_PX = 80;
const MODE_OPTIONS: ScenarioId[] = ["writing", "agent", "interview"];

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

function ThinkingBlock({
  text,
  live,
  open,
}: {
  text: string;
  live: boolean;
  open: boolean;
}) {
  if (!text.trim()) return null;
  return (
    <details
      className="rounded-lg border border-border/80 bg-muted/30"
      open={open}
    >
      <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-muted-foreground">
        {live ? "思考中…" : "思考过程"}
        <span className="ml-2 font-normal text-muted-foreground/70">
          （本轮直播，刷新不保留）
        </span>
      </summary>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap border-t border-border/60 px-3 py-2 text-xs text-muted-foreground">
        {text.trim()}
      </pre>
    </details>
  );
}

function UserBubble({
  text,
  meta,
}: {
  text: string;
  meta?: string;
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        你
        {meta ? (
          <span className="ml-2 text-muted-foreground/80">{meta}</span>
        ) : null}
      </p>
      <p className="rounded-lg bg-card px-3 py-2 text-sm text-foreground">
        {text}
      </p>
    </div>
  );
}

function AssistantBubble({ text }: { text: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">助手</p>
      <pre className="whitespace-pre-wrap rounded-lg bg-card/60 px-3 py-2 text-xs text-foreground/90">
        {text}
      </pre>
    </div>
  );
}

function ScenarioModeSwitch({
  scenarioId,
  sessionId,
  disabled,
}: {
  scenarioId: ScenarioId;
  sessionId: string | null;
  disabled?: boolean;
}) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        disabled={disabled}
        className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs text-foreground/90 hover:bg-muted disabled:opacity-50"
        aria-haspopup="menu"
        aria-expanded={open}
        title="切换场景模式"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="font-medium">{SCENARIO_META[scenarioId].navLabel}</span>
        <span className="text-muted-foreground">▾</span>
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute bottom-full right-0 z-50 mb-1 min-w-[120px] rounded-md border border-border bg-popover py-1 shadow-lg"
        >
          {MODE_OPTIONS.map((id) => (
            <button
              key={id}
              type="button"
              role="menuitem"
              className={`block w-full px-3 py-1.5 text-left text-xs hover:bg-muted ${
                id === scenarioId
                  ? "bg-muted/60 font-medium text-foreground"
                  : "text-foreground/90"
              }`}
              onClick={() => {
                setOpen(false);
                if (id === scenarioId) return;
                const base = `/${id}`;
                if (pathname.startsWith(base)) return;
                navigate(pathWithSession(base, sessionId));
              }}
            >
              {SCENARIO_META[id].navLabel}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ChatTabBar({
  active,
  onSelect,
  subagents,
  onCloseSub,
}: {
  active: ChatTab;
  onSelect: (tab: ChatTab) => void;
  subagents: SubagentLive[];
  onCloseSub: (id: string) => void;
}) {
  return (
    <div className="flex min-h-9 shrink-0 items-stretch gap-0 overflow-x-auto border-b border-border bg-muted/20">
      <button
        type="button"
        className={`shrink-0 border-r border-border px-3 py-2 text-xs ${
          active === "main"
            ? "bg-background font-medium text-foreground"
            : "text-muted-foreground hover:bg-background/60 hover:text-foreground"
        }`}
        onClick={() => onSelect("main")}
      >
        主会话
      </button>
      {subagents.map((sub) => {
        const selected = active === sub.subagent_id;
        const running = sub.status === "running";
        return (
          <div
            key={sub.subagent_id}
            className={`group flex shrink-0 items-stretch border-r border-border ${
              selected
                ? "bg-background text-foreground"
                : "text-muted-foreground hover:bg-background/60 hover:text-foreground"
            }`}
          >
            <button
              type="button"
              className="px-3 py-2 text-xs"
              title={sub.task || sub.subagent_id}
              onClick={() => onSelect(sub.subagent_id)}
            >
              <span className={selected ? "font-medium" : undefined}>
                {sub.agent_type}
              </span>
              <span className="ml-1.5 text-[10px] text-muted-foreground/80">
                {statusLabel(sub.status)}
              </span>
              {running ? (
                <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-warning align-middle" />
              ) : null}
            </button>
            {!running ? (
              <button
                type="button"
                className="px-1.5 text-muted-foreground/70 opacity-0 hover:text-foreground group-hover:opacity-100"
                title="关闭标签"
                aria-label="关闭子任务标签"
                onClick={(e) => {
                  e.stopPropagation();
                  onCloseSub(sub.subagent_id);
                }}
              >
                ×
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function SubagentSessionView({
  sub,
  busy,
}: {
  sub: SubagentLive;
  busy: boolean;
}) {
  const thinking = sub.thinkingText.trim();
  const output = (sub.streamText || sub.summary || "").trim();
  const liveThinking = busy && sub.status === "running" && !output;

  return (
    <div className="mb-4 space-y-2">
      <UserBubble text={sub.task || "(无任务描述)"} meta={sub.agent_type} />
      <ThinkingBlock text={thinking} live={liveThinking} open={liveThinking} />
      {sub.tools.length > 0 ? (
        <ul className="space-y-1.5">
          {sub.tools.map((tool) => (
            <li
              key={String(tool.tool_call_id)}
              className="rounded-lg border border-border/70 bg-background/80 px-3 py-2 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">
                  {String(tool.tool_name ?? "tool")}
                </span>
                <span className="text-muted-foreground">
                  {String(tool.status ?? "")}
                </span>
              </div>
              {tool.stream_output ? (
                <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap text-muted-foreground">
                  {tool.stream_output}
                </pre>
              ) : null}
              {tool.summary && !tool.stream_output ? (
                <p className="mt-1 line-clamp-3 text-muted-foreground">
                  {tool.summary}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {output ? (
        <AssistantBubble text={output} />
      ) : sub.status === "running" && !thinking ? (
        <p className="text-xs text-muted-foreground">思考中…</p>
      ) : null}
    </div>
  );
}

export function AgentChatPanel({
  wb,
  openSubagentRequest = null,
  onOpenSubagentHandled,
}: Props) {
  const pendingApprovalEvent = lastApprovalEvent(wb.events);
  const pendingArgs = pendingApprovalEvent?.payload.arguments as
    | Record<string, unknown>
    | undefined;
  const approval = approvalCopy(wb.pendingToolName);
  const currentStep = livePlanStep(wb.plan, wb.displayStatus);
  const approvalSubagentId =
    typeof pendingApprovalEvent?.payload.subagent_id === "string"
      ? pendingApprovalEvent.payload.subagent_id
      : "";

  const [activeTab, setActiveTab] = useState<ChatTab>("main");
  const [closedTabs, setClosedTabs] = useState<Set<string>>(() => new Set());
  const seenRunningRef = useRef<Set<string>>(new Set());

  const visibleSubs = wb.subagents.filter(
    (s) => !closedTabs.has(s.subagent_id),
  );
  const activeSub =
    activeTab === "main"
      ? null
      : (visibleSubs.find((s) => s.subagent_id === activeTab) ?? null);
  const onMain = activeTab === "main" || !activeSub;

  // Auto-open a tab when a new subagent starts running.
  useEffect(() => {
    for (const sub of wb.subagents) {
      if (sub.status !== "running") continue;
      if (seenRunningRef.current.has(sub.subagent_id)) continue;
      seenRunningRef.current.add(sub.subagent_id);
      setClosedTabs((prev) => {
        if (!prev.has(sub.subagent_id)) return prev;
        const next = new Set(prev);
        next.delete(sub.subagent_id);
        return next;
      });
      setActiveTab(sub.subagent_id);
    }
  }, [wb.subagents]);

  // External request (e.g. timeline click).
  useEffect(() => {
    if (!openSubagentRequest) return;
    setClosedTabs((prev) => {
      if (!prev.has(openSubagentRequest)) return prev;
      const next = new Set(prev);
      next.delete(openSubagentRequest);
      return next;
    });
    setActiveTab(openSubagentRequest);
    onOpenSubagentHandled?.();
  }, [openSubagentRequest, onOpenSubagentHandled]);

  // If active sub tab disappeared, fall back to main.
  useEffect(() => {
    if (activeTab === "main") return;
    if (!visibleSubs.some((s) => s.subagent_id === activeTab)) {
      setActiveTab("main");
    }
  }, [activeTab, visibleSubs]);

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
    wb.thinkingText,
    wb.sectionDraft,
    wb.view?.latest_output,
    wb.busy,
    wb.displayStatus,
    wb.awaitingApproval,
    wb.historyLoading,
    wb.plan?.items?.length,
    activeTab,
    activeSub?.streamText,
    activeSub?.thinkingText,
    activeSub?.tools.length,
  ]);

  useEffect(() => {
    if (!wb.busy) return;
    stickToBottomRef.current = true;
    endRef.current?.scrollIntoView({ block: "end" });
  }, [wb.turnId, wb.busy, activeTab]);

  const closeSubTab = (id: string) => {
    setClosedTabs((prev) => new Set(prev).add(id));
    if (activeTab === id) setActiveTab("main");
  };

  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-border bg-background">
      <ChatTabBar
        active={onMain ? "main" : activeTab}
        onSelect={setActiveTab}
        subagents={visibleSubs}
        onCloseSub={closeSubTab}
      />

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4"
      >
        {onMain ? (
          <>
            {wb.historyLoading ? (
              <p className="text-xs text-muted-foreground/80">
                正在加载会话历史…
              </p>
            ) : null}
            {wb.turnHistory.map((turn) => {
              const output = assistantText(wb, turn);
              const isLive = turn.id === wb.turnId;
              const thinking =
                isLive && wb.thinkingText.trim()
                  ? wb.thinkingText.trim()
                  : "";
              const liveOpen = Boolean(
                isLive && wb.busy && !wb.stopping && !output,
              );
              return (
                <div key={turn.id} className="mb-4 space-y-2">
                  <UserBubble text={turn.user_input} />
                  <ThinkingBlock
                    text={thinking}
                    live={liveOpen}
                    open={liveOpen}
                  />
                  {output ? (
                    <AssistantBubble text={output} />
                  ) : isLive && wb.busy && !thinking ? (
                    <p className="text-xs text-muted-foreground">思考中…</p>
                  ) : null}
                </div>
              );
            })}
            {!wb.historyLoading && wb.turnHistory.length === 0 ? (
              <p className="text-xs text-muted-foreground/80">
                发送消息开始任务…
              </p>
            ) : null}
            {(wb.view || wb.busy) && wb.turnId && currentStep ? (
              <p className="mt-3 text-xs text-muted-foreground/80">
                计划：{currentStep.title}
              </p>
            ) : null}
          </>
        ) : activeSub ? (
          <SubagentSessionView sub={activeSub} busy={wb.busy} />
        ) : null}
        <div ref={endRef} aria-hidden className="h-px w-full" />
      </div>

      {wb.awaitingApproval && onMain ? (
        <div className="shrink-0 border-t border-primary/30 bg-primary/10 p-4">
          <p className="text-sm font-medium text-primary">
            {approval.title}
            {approvalSubagentId ? (
              <span className="ml-2 text-xs font-normal text-primary/80">
                · 子任务
              </span>
            ) : null}
          </p>
          <p className="mb-2 text-xs text-muted-foreground">
            {approval.description}
          </p>
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

      {onMain ? (
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
          {wb.outboundQueue.length > 0 ? (
            <div className="space-y-1 rounded-md border border-border/80 bg-muted/30 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] text-muted-foreground">
                  已排队 {wb.outboundQueue.length}{" "}
                  条，本轮结束后将合并为一条发送
                </p>
                <button
                  type="button"
                  className="shrink-0 text-[11px] text-muted-foreground hover:text-foreground"
                  onClick={() => wb.clearOutboundQueue()}
                >
                  清空
                </button>
              </div>
              <ul className="max-h-24 space-y-1 overflow-y-auto">
                {wb.outboundQueue.map((item, index) => (
                  <li
                    key={`${index}-${item.slice(0, 24)}`}
                    className="truncate text-[11px] text-muted-foreground/90"
                    title={item}
                  >
                    {index + 1}. {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <Textarea
            className="min-h-[80px] resize-none text-sm"
            value={wb.message}
            onChange={(e) => wb.setMessage(e.target.value)}
            placeholder={
              wb.busy || wb.awaitingApproval
                ? "本轮进行中也可输入，发送后排队…"
                : placeholderForScenario(wb.scenarioId)
            }
            onKeyDown={(e) =>
              onChatEnterSend(
                e,
                () => void wb.handleSend(),
                Boolean(wb.message.trim()),
              )
            }
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={wb.planMode ? "default" : "outline"}
              className={
                wb.planMode
                  ? "bg-primary hover:bg-primary/90"
                  : "border-primary/40 text-primary"
              }
              disabled={wb.busy || wb.awaitingApproval}
              onClick={() => wb.setPlanMode(!wb.planMode)}
              title="Plan 模式：先规划，确认后再执行"
            >
              {wb.planMode ? "Plan · 开" : "Plan"}
            </Button>
            <Button
              size="sm"
              disabled={!wb.message.trim()}
              onClick={() => void wb.handleSend()}
              title={
                wb.busy || wb.awaitingApproval
                  ? "加入队列，本轮结束后合并发送"
                  : "发送"
              }
            >
              {wb.busy || wb.awaitingApproval ? "排队" : "发送"}
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
            <ScenarioModeSwitch
              scenarioId={wb.scenarioId}
              sessionId={wb.sessionId}
              disabled={wb.busy || wb.awaitingApproval}
            />
          </div>
        </div>
      ) : null}
    </aside>
  );
}
