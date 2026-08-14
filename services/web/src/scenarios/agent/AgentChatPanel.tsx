import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Plus, X } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import { Markdown } from "../../shared/Markdown";
import {
  approvalCopy,
  lastApprovalEvent,
} from "../../shared/workbench/toolApproval";
import { onChatEnterSend } from "../../shared/workbench/chatKeyboard";
import { useChatInputHistory } from "../../shared/workbench/useChatInputHistory";
import {
  placeholderForScenario,
  SCENARIO_META,
} from "../../shared/workbench/scenarioMeta";
import { PlanPanel } from "../../shared/workbench/PlanPanel";
import { livePlanStep } from "../../shared/workbench/plan";
import { pathWithSession } from "../../shared/workbench/sessionUrl";
import { statusLabel } from "../../shared/workbench/subagents";
import type { SubagentLive } from "../../shared/workbench/subagents";
import { useAgentPanel } from "../../shared/workbench/agentPanel";
import type {
  ScenarioId,
  TurnHistoryItem,
  WorkbenchState,
} from "../../shared/workbench/types";
import {
  filterSlashCommands,
  slashQueryFromInput,
  type SlashCommand,
} from "../../shared/workbench/slashCommands";
import { SlashCommandMenu } from "../../shared/workbench/SlashCommandMenu";

type Props = {
  wb: WorkbenchState;
  /** Open a nested subagent chat tab (from timeline). */
  openSubagentRequest?: string | null;
  onOpenSubagentHandled?: () => void;
};

type ChatTab = "main" | string;

const STICK_THRESHOLD_PX = 80;
const MODE_OPTIONS: ScenarioId[] = ["writing", "agent", "intel", "collab"];

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

function UserBubble({ text, meta }: { text: string; meta?: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[min(100%,42rem)]">
        <p className="mb-1 text-right text-[11px] font-medium text-muted-foreground">
          你
          {meta ? (
            <span className="ml-2 text-muted-foreground/80">{meta}</span>
          ) : null}
        </p>
        <p className="rounded-2xl rounded-br-md bg-primary/15 px-3.5 py-2.5 text-sm leading-relaxed text-foreground">
          {text}
        </p>
      </div>
    </div>
  );
}

function AssistantBubble({
  text,
  streaming = false,
}: {
  text: string;
  /** Live turn: plain text; settled turn: GFM (avoid per-frame remark parse). */
  streaming?: boolean;
}) {
  return (
    <div className="max-w-[min(100%,48rem)]">
      <p className="mb-1 text-[11px] font-medium text-muted-foreground">助手</p>
      {/* aria-live lets screen readers follow streaming output (I23). */}
      <div
        aria-live="polite"
        className="rounded-2xl rounded-tl-md border border-border/60 bg-card/50 px-3.5 py-2.5"
      >
        <Markdown text={text} streaming={streaming} />
      </div>
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
        className="inline-flex h-8 items-center gap-1 rounded-md border border-transparent px-2 text-xs text-muted-foreground transition-colors hover:border-border hover:bg-muted hover:text-foreground disabled:opacity-50"
        aria-haspopup="menu"
        aria-expanded={open}
        title="切换场景模式"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="font-medium">
          {SCENARIO_META[scenarioId].navLabel}
        </span>
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

function chatTabTitle(wb: WorkbenchState): string {
  const latest = wb.turnHistory[wb.turnHistory.length - 1];
  const text = (wb.submittedMessage || latest?.user_input || "").trim();
  if (!text) return "新对话";
  const oneLine = text.replace(/\s+/g, " ");
  return oneLine.length > 20 ? `${oneLine.slice(0, 20)}…` : oneLine;
}

function ChatTabBar({
  active,
  onSelect,
  subagents,
  onCloseSub,
  onNewSession,
  chatTitle,
}: {
  active: ChatTab;
  onSelect: (tab: ChatTab) => void;
  subagents: SubagentLive[];
  onCloseSub: (id: string) => void;
  onNewSession: () => void;
  chatTitle: string;
}) {
  return (
    <div className="flex min-h-9 shrink-0 items-stretch gap-0 overflow-x-auto border-b border-border/80 bg-muted/15">
      <div
        className={`flex max-w-[220px] shrink-0 items-stretch border-r border-border/80 ${
          active === "main"
            ? "bg-background text-foreground"
            : "text-muted-foreground hover:bg-background/60 hover:text-foreground"
        }`}
      >
        <button
          type="button"
          className={`truncate px-3.5 py-2 text-xs ${
            active === "main" ? "font-medium" : ""
          }`}
          title={chatTitle}
          onClick={() => onSelect("main")}
        >
          {chatTitle}
        </button>
      </div>
      <button
        type="button"
        className="flex shrink-0 items-center border-r border-border/80 px-2.5 text-muted-foreground transition-colors hover:bg-background/60 hover:text-foreground"
        title="新建会话"
        aria-label="新建会话"
        onClick={() => onNewSession()}
      >
        <Plus className="h-3.5 w-3.5" />
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
            <button
              type="button"
              className="px-1.5 text-muted-foreground/80 hover:bg-muted hover:text-foreground"
              title={running ? "关闭标签（后台仍继续，不取消）" : "关闭标签"}
              aria-label="关闭子任务标签"
              onClick={(e) => {
                e.stopPropagation();
                onCloseSub(sub.subagent_id);
              }}
            >
              <X className="h-3.5 w-3.5" />
            </button>
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
                  {String(tool.status ?? "") === "skipped"
                    ? "已跳过"
                    : String(tool.status ?? "")}
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
        <AssistantBubble
          text={output}
          streaming={busy && sub.status === "running"}
        />
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
  const { createAgent } = useAgentPanel();
  const inputHistory = useChatInputHistory({
    sessionKey: wb.sessionId,
    seedInputs: wb.turnHistory.map((t) => t.user_input),
  });
  const pendingApprovalEvent = lastApprovalEvent(wb.events);
  const pendingArgs = pendingApprovalEvent?.payload.arguments as
    Record<string, unknown> | undefined;
  const approval = approvalCopy(wb.pendingToolName);
  const currentStep = livePlanStep(wb.plan, wb.displayStatus);
  const approvalSubagentId =
    typeof pendingApprovalEvent?.payload.subagent_id === "string"
      ? pendingApprovalEvent.payload.subagent_id
      : "";

  const [activeTab, setActiveTab] = useState<ChatTab>("main");
  const [closedTabs, setClosedTabs] = useState<Set<string>>(() => new Set());
  const [slashActiveIndex, setSlashActiveIndex] = useState(0);
  const [slashDismissed, setSlashDismissed] = useState(false);
  const seenRunningRef = useRef<Set<string>>(new Set());

  const slashQuery = slashQueryFromInput(wb.message);
  const slashItems =
    slashQuery != null && !slashDismissed
      ? filterSlashCommands(slashQuery, wb.scenarioId)
      : [];
  const slashMenuOpen = slashQuery != null && !slashDismissed;

  useEffect(() => {
    if (slashQuery == null) setSlashDismissed(false);
  }, [slashQuery]);

  useEffect(() => {
    setSlashActiveIndex(0);
  }, [slashQuery, wb.scenarioId]);

  useEffect(() => {
    if (slashActiveIndex >= slashItems.length && slashItems.length > 0) {
      setSlashActiveIndex(slashItems.length - 1);
    }
  }, [slashActiveIndex, slashItems.length]);

  const applySlashCommand = (cmd: SlashCommand) => {
    inputHistory.onEdit(cmd.insert);
    wb.setMessage(cmd.insert);
    setSlashDismissed(true);
    setSlashActiveIndex(0);
  };

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

  // If active sub tab disappeared, fall back to the chat tab.
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

  const planItemsKey =
    wb.plan?.items?.map((i) => `${i.id}:${i.status}`).join("|") ?? "";

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
    planItemsKey,
    wb.canExecutePlan,
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

  const handleNewSession = () => {
    void createAgent();
  };

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border/80 bg-background shadow-sm">
      <ChatTabBar
        active={onMain ? "main" : activeTab}
        onSelect={setActiveTab}
        subagents={visibleSubs}
        onCloseSub={closeSubTab}
        onNewSession={handleNewSession}
        chatTitle={chatTabTitle(wb)}
      />

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6"
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
                isLive && wb.thinkingText.trim() ? wb.thinkingText.trim() : "";
              const liveOpen = Boolean(
                isLive && wb.busy && !wb.stopping && !output,
              );
              // Live turn prefers streaming plan; settled turns keep their snapshot.
              const turnPlan = isLive ? (wb.plan ?? turn.plan) : turn.plan;
              const turnPlanPhase = isLive ? wb.planPhase : "off";
              const turnStatus = isLive ? wb.displayStatus : turn.status;
              const hasAssistantBody = Boolean(
                turnPlan?.items?.length ||
                thinking ||
                output ||
                (isLive && wb.busy),
              );
              return (
                <div key={turn.id} className="mb-6 space-y-3">
                  <UserBubble text={turn.user_input} />
                  {hasAssistantBody ? (
                    <div className="max-w-[min(100%,48rem)] space-y-2">
                      <p className="text-[11px] font-medium text-muted-foreground">
                        助手
                      </p>
                      {turnPlan?.items?.length ? (
                        <PlanPanel
                          plan={turnPlan}
                          turnStatus={turnStatus}
                          planPhase={turnPlanPhase}
                          showExecute={Boolean(isLive && wb.canExecutePlan)}
                          executeDisabled={wb.busy || wb.actionBusy}
                          onExecute={
                            isLive
                              ? () => void wb.handleExecutePlan()
                              : undefined
                          }
                          variant="chat"
                        />
                      ) : null}
                      <ThinkingBlock
                        text={thinking}
                        live={liveOpen}
                        open={liveOpen}
                      />
                      {output ? (
                        <div
                          aria-live="polite"
                          className="rounded-2xl rounded-tl-md border border-border/60 bg-card/50 px-3.5 py-2.5"
                        >
                          <Markdown
                            text={output}
                            streaming={Boolean(isLive && wb.busy)}
                          />
                        </div>
                      ) : isLive && wb.busy && !thinking ? (
                        <p className="px-1 text-xs text-muted-foreground">
                          思考中…
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
            {!wb.historyLoading && wb.turnHistory.length === 0 ? (
              <div className="flex h-full min-h-[12rem] flex-col items-center justify-center text-center">
                <p className="text-sm text-muted-foreground">
                  发送消息开始任务
                </p>
                <p className="mt-1 max-w-sm text-xs text-muted-foreground/70">
                  Enter 发送 · Shift+Enter 换行 · 输入 / 唤起命令 · 空框 ↑
                  回忆历史
                </p>
              </div>
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
        <div className="shrink-0 space-y-2.5 border-t border-border/80 bg-muted/10 px-4 py-3">
          {/* Plan lives in the scrollback; keep only a thin consent / live-step strip. */}
          {wb.canExecutePlan ? (
            <p className="truncate text-[11px] font-medium text-warning">
              计划待确认
              {wb.plan?.items?.length ? ` · ${wb.plan.items.length} 项` : ""}·
              在上方清单点「按此执行」
            </p>
          ) : currentStep && wb.busy ? (
            <p className="truncate text-[11px] text-primary/90">
              计划进行中 · {currentStep.title}
            </p>
          ) : null}
          {wb.showPlanSuggest ? (
            <div className="flex items-start justify-between gap-2 rounded-lg border border-warning/40 bg-warning-muted px-3 py-2 text-[11px] text-warning">
              <div className="min-w-0 space-y-0.5">
                <p>建议先切到 Plan，列出步骤再执行（可忽略）。</p>
                {wb.planSuggestReason ? (
                  <p className="text-warning/80">{wb.planSuggestReason}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  className="rounded-md bg-warning px-2 py-0.5 text-warning-foreground hover:bg-warning/90"
                  onClick={() => wb.setPlanMode(true)}
                >
                  切换 Plan
                </button>
                <button
                  type="button"
                  className="rounded-md px-2 py-0.5 text-warning/80 hover:text-warning"
                  onClick={() => wb.dismissPlanSuggest()}
                >
                  忽略
                </button>
              </div>
            </div>
          ) : null}
          {wb.outboundQueue.length > 0 ? (
            <div className="space-y-1 rounded-lg border border-border/70 bg-background/60 px-3 py-2">
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
          <div className="relative rounded-xl border border-border/80 bg-background focus-within:border-ring/50 focus-within:ring-1 focus-within:ring-ring/30">
            {slashMenuOpen ? (
              <SlashCommandMenu
                items={slashItems}
                activeIndex={slashActiveIndex}
                onActiveIndexChange={setSlashActiveIndex}
                onSelect={applySlashCommand}
                onDismiss={() => setSlashDismissed(true)}
              />
            ) : null}
            <Textarea
              className="min-h-[88px] resize-none border-0 bg-transparent text-sm shadow-none focus-visible:ring-0"
              value={wb.message}
              onChange={(e) => {
                setSlashDismissed(false);
                inputHistory.onEdit(e.target.value);
                wb.setMessage(e.target.value);
              }}
              placeholder={
                wb.busy || wb.awaitingApproval
                  ? "本轮进行中也可输入，发送后排队…"
                  : placeholderForScenario(wb.scenarioId)
              }
              title="输入 / 唤起命令；空框时 ↑ 回忆历史"
              onKeyDown={(e) => {
                if (slashMenuOpen) {
                  if (e.key === "Escape") {
                    e.preventDefault();
                    setSlashDismissed(true);
                    return;
                  }
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    if (slashItems.length === 0) return;
                    setSlashActiveIndex((i) => (i + 1) % slashItems.length);
                    return;
                  }
                  if (e.key === "ArrowUp") {
                    e.preventDefault();
                    if (slashItems.length === 0) return;
                    setSlashActiveIndex(
                      (i) => (i - 1 + slashItems.length) % slashItems.length,
                    );
                    return;
                  }
                  if (
                    (e.key === "Enter" || e.key === "Tab") &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    const cmd = slashItems[slashActiveIndex];
                    if (cmd) {
                      e.preventDefault();
                      applySlashCommand(cmd);
                      return;
                    }
                  }
                }
                inputHistory.onKeyDown(e, wb.message, wb.setMessage);
                onChatEnterSend(
                  e,
                  () => {
                    inputHistory.remember(wb.message);
                    void wb.handleSend();
                  },
                  Boolean(wb.message.trim()),
                );
              }}
            />
            <div className="flex flex-wrap items-center gap-2 border-t border-border/60 px-2.5 py-2">
              <Button
                size="sm"
                variant={wb.planMode ? "default" : "ghost"}
                className={
                  wb.planMode
                    ? undefined
                    : "text-muted-foreground hover:text-foreground"
                }
                disabled={wb.busy || wb.awaitingApproval}
                onClick={() => wb.setPlanMode(!wb.planMode)}
                title="Plan 模式：先规划，确认后再执行"
              >
                {wb.planMode ? "Plan · 开" : "Plan"}
              </Button>
              <ScenarioModeSwitch
                scenarioId={wb.scenarioId}
                sessionId={wb.sessionId}
                disabled={wb.busy || wb.awaitingApproval}
              />
              <div className="ml-auto flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="border-destructive/40 text-destructive hover:bg-destructive/10"
                  disabled={!wb.busy || wb.stopping}
                  onClick={() => void wb.handleStop()}
                >
                  {wb.stopping ? "停止中…" : "Stop"}
                </Button>
                <Button
                  size="sm"
                  disabled={!wb.message.trim()}
                  onClick={() => {
                    inputHistory.remember(wb.message);
                    void wb.handleSend();
                  }}
                  title={
                    wb.busy || wb.awaitingApproval
                      ? "加入队列，本轮结束后合并发送"
                      : "发送"
                  }
                >
                  {wb.busy || wb.awaitingApproval ? "排队" : "发送"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
