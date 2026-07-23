import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  acceptPatch,
  approveToolCall,
  cancelTurn,
  denyToolCall,
  fetchSessionTurns,
  fetchTurnView,
  rejectPatch,
  startTurn,
  warmupRetrieval,
  type TurnEvent,
  type TurnSummary,
  type TurnView,
} from "../api/client";
import { TurnStreamClient } from "../realtime/TurnStreamClient";
import { TurnWebSocketClient } from "../realtime/TurnWebSocketClient";
import type {
  ContextUsage,
  ScenarioId,
  TimelineItem,
  TokenUsage,
  TurnHistoryItem,
  WorkbenchState,
  WriteFilePreview,
} from "./types";
import { previewText } from "./filePreview";
import {
  executePlanMessage,
  isPlanSuggestCooldownActive,
  latestPlanFromArtifacts,
  planFromEventPayload,
  planIsProposedOnly,
  planSuggestPrimaryReason,
  readPlanSuggestDismissedAt,
  shouldSuggestPlanMode,
  writePlanSuggestDismissedAt,
  type PlanArtifact,
  type PlanPhase,
  type PlanPhaseWire,
} from "./plan";
import { scenarioMeta } from "./scenarioMeta";
import { tokenUsageFromEvents } from "./tokenUsage";
import { useWorkbenchSession } from "./workbenchSession";

type StreamClient = TurnStreamClient | TurnWebSocketClient;

const ACTIVE_TURN_STATUSES = new Set([
  "pending",
  "running",
  "waiting_approval",
]);

function toHistoryItem(turn: TurnSummary): TurnHistoryItem {
  return {
    id: turn.id,
    scenario_id: turn.scenario_id as ScenarioId,
    status: turn.status,
    user_input: turn.user_input ?? "",
    latest_output: turn.latest_output,
    created_at: turn.created_at,
  };
}

function upsertHistoryItem(
  items: TurnHistoryItem[],
  item: TurnHistoryItem,
): TurnHistoryItem[] {
  const idx = items.findIndex((row) => row.id === item.id);
  if (idx < 0) return [...items, item];
  const next = [...items];
  next[idx] = { ...next[idx], ...item };
  return next;
}

function historyItemFromView(v: TurnView): TurnHistoryItem {
  return {
    id: v.turn_id,
    scenario_id: v.scenario_id as ScenarioId,
    status: v.status,
    user_input: v.user_input,
    latest_output: v.latest_output ?? null,
    created_at: v.updated_at,
  };
}

export function useWorkbenchImpl(): WorkbenchState {
  const [searchParams] = useSearchParams();
  const useWebSocket = searchParams.get("transport") === "ws";
  const [activeScenarioId, setActiveScenarioId] =
    useState<ScenarioId>("writing");
  const [turnHistory, setTurnHistory] = useState<TurnHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [message, setMessageState] = useState("");
  const warmupTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const setMessage = useCallback((value: string) => {
    setMessageState(value);
    if (warmupTimerRef.current) clearTimeout(warmupTimerRef.current);
    if (!value.trim()) return;
    warmupTimerRef.current = setTimeout(() => {
      void warmupRetrieval(value);
    }, 300);
  }, []);
  const [submittedMessage, setSubmittedMessage] = useState<string | null>(null);
  const [turnId, setTurnId] = useState<string | null>(null);
  const [view, setView] = useState<TurnView | null>(null);
  const [events, setEvents] = useState<TurnEvent[]>([]);
  const [streamText, setStreamText] = useState("");
  const [thinkingText, setThinkingText] = useState("");
  const [sectionDraft, setSectionDraft] = useState("");
  const [toolLiveStreams, setToolLiveStreams] = useState<
    Record<string, string>
  >({});
  const [stopping, setStopping] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingApproval, setPendingApproval] = useState(false);
  const [pendingToolCallId, setPendingToolCallId] = useState<string | null>(
    null,
  );
  const [pendingToolName, setPendingToolName] = useState<string | null>(null);
  const [pendingWriteFile, setPendingWriteFile] =
    useState<WriteFilePreview | null>(null);
  const [liveToolTimeline, setLiveToolTimeline] = useState<TimelineItem[]>([]);
  const [liveContextUsage, setLiveContextUsage] = useState<ContextUsage | null>(
    null,
  );
  const [liveTokenUsage, setLiveTokenUsage] = useState<TokenUsage | null>(null);
  const [livePlan, setLivePlan] = useState<PlanArtifact | null>(null);
  const [planMode, setPlanMode] = useState(false);
  /** Epoch ms when user dismissed suggest; drives cooldown (docs/26 PS3). */
  const [planSuggestDismissedAt, setPlanSuggestDismissedAt] = useState<
    number | null
  >(null);
  /** Only true after a Plan-mode turn posted an all-pending checklist. */
  const [planAwaitingConfirm, setPlanAwaitingConfirm] = useState(false);
  /** Last StartTurn plan_phase sent (drives live planning/executing UI). */
  const [activePlanPhase, setActivePlanPhase] = useState<PlanPhaseWire | null>(
    null,
  );
  const planWrapSentRef = useRef(false);
  const streamRef = useRef<StreamClient | null>(null);
  const lastSequenceRef = useRef(0);
  const resumingAfterApprovalRef = useRef(false);
  const sessionRestoredRef = useRef(false);
  const turnIdRef = useRef<string | null>(null);
  const streamTextRef = useRef("");
  const sectionDraftRef = useRef("");
  turnIdRef.current = turnId;
  streamTextRef.current = streamText;
  sectionDraftRef.current = sectionDraft;

  function syncHistoryFromView(v: TurnView) {
    setTurnHistory((prev) =>
      upsertHistoryItem(prev, historyItemFromView(v)),
    );
  }

  function extractWriteFilePreview(
    payload: Record<string, unknown>,
  ): WriteFilePreview | null {
    if (String(payload.tool_name ?? "") !== "write_file") return null;
    const args = (payload.arguments ?? {}) as Record<string, unknown>;
    const path = String(payload.path ?? args.path ?? "");
    const newRaw = String(payload.new_text ?? args.content ?? "");
    const oldRaw = String(payload.old_text ?? "");
    if (!path && !newRaw) return null;
    const newPreview = previewText(newRaw);
    const oldPreview = previewText(oldRaw);
    return {
      path,
      old_text: oldPreview.text,
      new_text: newPreview.text,
      status: "pending",
      truncated: newPreview.truncated || oldPreview.truncated,
      new_size: newRaw.length,
    };
  }

  function syncApprovalFromView(v: TurnView) {
    const waiting = v.status === "waiting_approval";
    setPendingApproval(waiting);
    if (waiting && v.interrupt?.tool_call_id) {
      setPendingToolCallId(String(v.interrupt.tool_call_id));
      const interrupt = v.interrupt as Record<string, string>;
      if (interrupt.tool_name) setPendingToolName(interrupt.tool_name);
    } else {
      setPendingToolCallId(null);
      setPendingToolName(null);
      setPendingWriteFile(null);
    }
    const fileArtifact = [...(v.artifacts ?? [])]
      .reverse()
      .find(
        (a) => a.type === "file_write" && (a.status === "pending" || !a.status),
      );
    if (waiting && fileArtifact) {
      setPendingWriteFile({
        path: String(fileArtifact.path ?? ""),
        old_text: String(fileArtifact.old_text ?? ""),
        new_text: String(fileArtifact.new_text ?? ""),
        status: String(fileArtifact.status ?? "pending"),
        truncated: Boolean(fileArtifact.truncated),
        new_size:
          typeof fileArtifact.new_size === "number"
            ? fileArtifact.new_size
            : undefined,
        bytes_written:
          typeof fileArtifact.bytes_written === "number"
            ? fileArtifact.bytes_written
            : undefined,
      });
    }
  }

  function reportError(context: string, err: unknown) {
    const detail = err instanceof Error ? err.message : String(err);
    setError(`${context}：${detail}`);
  }

  const { sessionId } = useWorkbenchSession();

  useEffect(() => {
    const stored = readPlanSuggestDismissedAt(sessionId);
    setPlanSuggestDismissedAt(
      isPlanSuggestCooldownActive(stored) ? stored : null,
    );
  }, [sessionId]);

  const turnViewQuery = useQuery({
    queryKey: ["turn-view", turnId],
    queryFn: () => fetchTurnView(turnId!),
    enabled: Boolean(turnId) && !busy,
  });

  useEffect(() => {
    if (turnViewQuery.data) {
      setView(turnViewQuery.data);
      syncApprovalFromView(turnViewQuery.data);
      syncHistoryFromView(turnViewQuery.data);
      if (turnViewQuery.data.context_usage) {
        setLiveContextUsage(turnViewQuery.data.context_usage as ContextUsage);
      }
      if (turnViewQuery.data.token_usage) {
        setLiveTokenUsage(turnViewQuery.data.token_usage as TokenUsage);
      }
      const viewPlan = latestPlanFromArtifacts(
        turnViewQuery.data.artifacts as Record<string, unknown>[] | undefined,
      );
      if (viewPlan) setLivePlan(viewPlan);
    }
  }, [turnViewQuery.data]);

  useEffect(() => () => streamRef.current?.close(), []);

  function connectStream(id: string, sinceSequence = lastSequenceRef.current) {
    streamRef.current?.close();
    const client: StreamClient = useWebSocket
      ? new TurnWebSocketClient()
      : new TurnStreamClient();
    streamRef.current = client;
    client.connect(
      id,
      {
        onEvent: (ev) => {
          if (ev.sequence > lastSequenceRef.current) {
            lastSequenceRef.current = ev.sequence;
          }
          setEvents((prev) => [...prev, ev]);
          if (ev.type === "turn.token") {
            const delta = String(ev.payload.delta ?? "");
            setStreamText((t) => t + delta);
          }
          if (ev.type === "turn.thinking.delta") {
            const delta = String(ev.payload.delta ?? "");
            if (delta) setThinkingText((t) => t + delta);
          }
          if (ev.type === "turn.thinking") {
            // New model step — separate rounds visually; still ephemeral.
            setThinkingText((t) => (t.trim() ? `${t.trimEnd()}\n\n` : t));
          }
          if (ev.type === "section.draft.delta") {
            const delta = String(ev.payload.delta ?? "");
            setSectionDraft((t) => t + delta);
          }
          if (ev.type === "tool.delta") {
            const toolCallId = String(ev.payload.tool_call_id ?? "");
            const delta = String(ev.payload.delta ?? "");
            if (toolCallId) {
              setToolLiveStreams((prev) => ({
                ...prev,
                [toolCallId]: (prev[toolCallId] ?? "") + delta,
              }));
            }
          }
          if (ev.type === "tool.started") {
            const toolCallId = String(ev.payload.tool_call_id ?? "");
            const toolName = String(ev.payload.tool_name ?? "tool");
            if (toolCallId) {
              setLiveToolTimeline((prev) => {
                if (prev.some((t) => t.tool_call_id === toolCallId))
                  return prev;
                return [
                  ...prev,
                  {
                    tool_call_id: toolCallId,
                    tool_name: toolName,
                    status: "running",
                  },
                ];
              });
            }
          }
          if (ev.type === "tool.completed") {
            const toolCallId = String(ev.payload.tool_call_id ?? "");
            const toolName = String(ev.payload.tool_name ?? "tool");
            const status = String(ev.payload.status ?? "ok");
            const summary =
              typeof ev.payload.summary === "string"
                ? ev.payload.summary
                : undefined;
            if (toolCallId) {
              setLiveToolTimeline((prev) => {
                const idx = prev.findIndex(
                  (t) => t.tool_call_id === toolCallId,
                );
                if (idx < 0) {
                  return [
                    ...prev,
                    {
                      tool_call_id: toolCallId,
                      tool_name: toolName,
                      status,
                      summary,
                    },
                  ];
                }
                const next = [...prev];
                next[idx] = {
                  ...next[idx],
                  tool_name: toolName,
                  status,
                  summary,
                };
                return next;
              });
            }
          }
          if (ev.type === "context.reported") {
            setLiveContextUsage({
              tokens_before: Number(ev.payload.tokens_before ?? 0),
              tokens_after: Number(ev.payload.tokens_after ?? 0),
              token_budget: Number(ev.payload.token_budget ?? 0),
              reserve_tokens: Number(ev.payload.reserve_tokens ?? 0),
              fill_ratio: Number(ev.payload.fill_ratio ?? 0),
              strategies: Array.isArray(ev.payload.strategies)
                ? (ev.payload.strategies as string[])
                : [],
              step_index: Number(ev.payload.step_index ?? 0),
              system_tokens: Number(ev.payload.system_tokens ?? 0),
              tools_tokens: Number(ev.payload.tools_tokens ?? 0),
              messages_tokens: Number(ev.payload.messages_tokens ?? 0),
              breakdown:
                ev.payload.breakdown && typeof ev.payload.breakdown === "object"
                  ? (ev.payload.breakdown as ContextUsage["breakdown"])
                  : undefined,
              source:
                (ev.payload.source as ContextUsage["source"]) ?? "estimated",
            });
          }
          if (ev.type === "turn.plan") {
            const nextPlan = planFromEventPayload(
              ev.payload as Record<string, unknown>,
            );
            setLivePlan(nextPlan);
            if (planIsProposedOnly(nextPlan) && planWrapSentRef.current) {
              setPlanAwaitingConfirm(true);
            } else if (!planIsProposedOnly(nextPlan)) {
              // Already executing / partially done — never offer 「按此执行」.
              setPlanAwaitingConfirm(false);
              planWrapSentRef.current = false;
            }
          }
          if (ev.type === "usage.reported" || ev.type === "turn.completed") {
            // Backend payload.input/output_tokens are turn cumulatives;
            // step_* fields are per-step deltas (used only when rebuilding from events).
            const usage = (
              ev.type === "usage.reported" ? ev.payload : ev.payload.token_usage
            ) as TokenUsage | undefined;
            if (usage && typeof usage === "object") {
              setLiveTokenUsage({
                input_tokens: Number(usage.input_tokens ?? 0),
                output_tokens: Number(usage.output_tokens ?? 0),
                source: usage.source,
              });
            }
          }
          if (ev.type === "turn.failed") {
            setBusy(false);
            setActivePlanPhase(null);
            const msg = String(
              ev.payload.message ?? ev.payload.termination_reason ?? "未知错误",
            );
            reportError("任务失败", msg);
          }
          if (ev.type === "turn.completed" || ev.type === "turn.cancelled") {
            // Clear busy immediately — do not wait for onClose's fetchTurnView
            // (refresh 可恢复；否则会卡在「只能 Stop」且 activity 已显示完成).
            setBusy(false);
            setActivePlanPhase(null);
            setStopping(false);
            setActionBusy(false);
            setView((prev) =>
              prev
                ? {
                    ...prev,
                    status:
                      ev.type === "turn.completed" ? "completed" : "cancelled",
                  }
                : prev,
            );
          }
          if (ev.type === "approval.requested") {
            if (resumingAfterApprovalRef.current) return;
            setBusy(false);
            setPendingApproval(true);
            setPendingToolCallId(String(ev.payload.tool_call_id ?? ""));
            setPendingToolName(String(ev.payload.tool_name ?? "tool"));
            const preview = extractWriteFilePreview(ev.payload);
            if (preview) setPendingWriteFile(preview);
            void fetchTurnView(id)
              .then((v) => {
                setView(v);
                syncApprovalFromView(v);
              })
              .catch((err) => reportError("刷新审批状态失败", err));
          }
          if (ev.type === "approval.resolved") {
            setPendingApproval(false);
            setPendingToolCallId(null);
            setPendingToolName(null);
            setPendingWriteFile(null);
            setActionBusy(false);
            setView((prev) =>
              prev && prev.status === "waiting_approval"
                ? { ...prev, status: "running", interrupt: null }
                : prev,
            );
            resumingAfterApprovalRef.current = false;
          }
        },
        onClose: async () => {
          try {
            const v = await fetchTurnView(id);
            setView(v);
            syncApprovalFromView(v);
            const merged: TurnHistoryItem = {
              ...historyItemFromView(v),
              latest_output:
                streamTextRef.current ||
                sectionDraftRef.current ||
                v.latest_output ||
                null,
            };
            setTurnHistory((prev) => upsertHistoryItem(prev, merged));
            if (v.context_usage)
              setLiveContextUsage(v.context_usage as ContextUsage);
            if (v.token_usage) setLiveTokenUsage(v.token_usage as TokenUsage);
            const closedPlan = latestPlanFromArtifacts(
              v.artifacts as Record<string, unknown>[] | undefined,
            );
            if (closedPlan) setLivePlan(closedPlan);
            setLiveToolTimeline([]);
          } catch (err) {
            reportError("刷新回合视图失败", err);
          } finally {
            setBusy(false);
            setActivePlanPhase(null);
            setStopping(false);
            setActionBusy(false);
            resumingAfterApprovalRef.current = false;
          }
        },
        onError: (err?: unknown) => {
          setBusy(false);
          setActivePlanPhase(null);
          setStopping(false);
          setActionBusy(false);
          reportError("事件流连接中断", err ?? "stream error");
        },
      },
      sinceSequence,
    );
  }

  useEffect(() => {
    if (!sessionId || sessionRestoredRef.current) return;
    let cancelled = false;
    setHistoryLoading(true);

    void (async () => {
      try {
        const turns = await fetchSessionTurns(sessionId);
        if (cancelled) return;

        const history = turns.map(toHistoryItem);
        setTurnHistory(history);
        setHistoryLoading(false);
        sessionRestoredRef.current = true;

        const last = history[history.length - 1];
        if (!last || turnIdRef.current) return;

        const v = await fetchTurnView(last.id);
        if (cancelled) return;

        if (ACTIVE_TURN_STATUSES.has(last.status)) {
          setTurnId(last.id);
          setView(v);
          setSubmittedMessage(v.user_input ?? null);
          syncApprovalFromView(v);
          if (v.context_usage) {
            setLiveContextUsage(v.context_usage as ContextUsage);
          }
          if (v.token_usage) {
            setLiveTokenUsage(v.token_usage as TokenUsage);
          }
          const activePlan = latestPlanFromArtifacts(
            v.artifacts as Record<string, unknown>[] | undefined,
          );
          if (activePlan) setLivePlan(activePlan);
          setPlanAwaitingConfirm(false);
          planWrapSentRef.current = false;
          lastSequenceRef.current = v.last_event_sequence ?? 0;
          setBusy(true);
          connectStream(last.id, lastSequenceRef.current);
          return;
        }

        // Idle: still surface the last turn's plan checklist if present.
        setView(v);
        const idlePlan = latestPlanFromArtifacts(
          v.artifacts as Record<string, unknown>[] | undefined,
        );
        if (idlePlan) setLivePlan(idlePlan);
        // Never resurrect 「按此执行」 from a historical mid-flight plan.
        setPlanAwaitingConfirm(false);
        planWrapSentRef.current = false;
      } catch (err) {
        if (!cancelled) {
          setHistoryLoading(false);
          reportError("加载会话历史失败", err);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const startTurnMut = useMutation({
    mutationFn: ({
      sid,
      msg,
      planPhase,
    }: {
      sid: string;
      msg: string;
      planPhase?: PlanPhaseWire | null;
    }) => startTurn(sid, msg, activeScenarioId, { plan_phase: planPhase }),
  });

  async function handleSendText(
    textRaw: string,
    opts?: { planModeSend?: boolean; planPhase?: PlanPhaseWire | null },
  ) {
    const text = textRaw.trim();
    if (!sessionId || !text || busy) return;
    // Never rewrite the user's message. Plan discipline is plan_phase + runtime system prompt.
    const usePlan =
      opts?.planModeSend ?? (planMode && opts?.planPhase !== "executing");
    let wirePhase: PlanPhaseWire | null = opts?.planPhase ?? null;
    if (usePlan && wirePhase == null) {
      wirePhase = "planning";
    }
    if (wirePhase === "planning") {
      planWrapSentRef.current = true;
      setPlanAwaitingConfirm(false);
    } else if (wirePhase === "executing" || opts?.planModeSend === false) {
      planWrapSentRef.current = false;
      setPlanAwaitingConfirm(false);
    }
    setActivePlanPhase(wirePhase);
    setBusy(true);
    setError(null);
    setEvents([]);
    setStreamText("");
    setThinkingText("");
    setSectionDraft("");
    setToolLiveStreams({});
    setLiveToolTimeline([]);
    setLiveContextUsage(null);
    setLiveTokenUsage(null);
    setLivePlan(null);
    setView(null);
    setStopping(false);
    setPendingApproval(false);
    setPendingToolCallId(null);
    setPendingToolName(null);
    setPendingWriteFile(null);
    lastSequenceRef.current = 0;
    resumingAfterApprovalRef.current = false;
    streamRef.current?.close();

    try {
      setSubmittedMessage(text);
      setMessage("");
      const turn = await startTurnMut.mutateAsync({
        sid: sessionId,
        msg: text,
        planPhase: wirePhase,
      });
      setTurnId(turn.id);
      setTurnHistory((prev) =>
        upsertHistoryItem(prev, {
          id: turn.id,
          scenario_id: activeScenarioId,
          status: turn.status,
          user_input: text,
          latest_output: null,
          created_at: turn.created_at,
        }),
      );
      connectStream(turn.id);
    } catch (err) {
      setBusy(false);
      setActivePlanPhase(null);
      reportError("发送失败", err);
    }
  }

  async function handleSend() {
    await handleSendText(message);
  }

  async function handleExecutePlan() {
    const snapshot =
      livePlan ??
      latestPlanFromArtifacts(
        view?.artifacts as Record<string, unknown>[] | undefined,
      );
    // Only allow the CTA path for proposed-only checklists from Plan mode.
    if (!planAwaitingConfirm || !planIsProposedOnly(snapshot)) {
      return;
    }
    planWrapSentRef.current = false;
    setPlanAwaitingConfirm(false);
    await handleSendText(executePlanMessage(), {
      planModeSend: false,
      planPhase: "executing",
    });
  }

  function dismissPlanSuggest() {
    const at = Date.now();
    setPlanSuggestDismissedAt(at);
    writePlanSuggestDismissedAt(sessionId, at);
  }

  function setPlanModeAndClearSuggest(value: boolean) {
    setPlanMode(value);
    if (value) {
      const at = Date.now();
      setPlanSuggestDismissedAt(at);
      writePlanSuggestDismissedAt(sessionId, at);
    }
  }

  async function handleVerify() {
    await handleSendText("/verify", { planModeSend: false });
  }
  async function handleStop() {
    if (!turnId) return;
    streamRef.current?.stopRendering();
    setStopping(true);
    try {
      await cancelTurn(turnId, false);
      // Soft cancel may wait for the worker; if the worker already died, force
      // finalize so we do not stick on「停止中」forever.
      window.setTimeout(() => {
        void (async () => {
          if (!turnIdRef.current) return;
          try {
            const v = await fetchTurnView(turnIdRef.current);
            if (
              v.status === "running" ||
              v.status === "pending" ||
              v.status === "waiting_approval"
            ) {
              await cancelTurn(turnIdRef.current, true);
            }
          } catch {
            /* ignore — terminal stream handler still owns cleanup */
          }
        })();
      }, 2500);
      window.setTimeout(() => {
        setStopping((prev) => {
          if (!prev) return prev;
          return false;
        });
        setBusy(false);
      }, 6000);
    } catch (err) {
      setStopping(false);
      reportError("停止失败", err);
    }
  }

  async function refreshView() {
    if (!turnId) return;
    try {
      const v = await fetchTurnView(turnId);
      setView(v);
      syncApprovalFromView(v);
      syncHistoryFromView(v);
    } catch (err) {
      reportError("刷新视图失败", err);
    }
  }

  async function handleAcceptPatch(patchId: string) {
    if (!turnId) return;
    setActionBusy(true);
    setError(null);
    try {
      await acceptPatch(turnId, patchId);
      setBusy(true);
      connectStream(turnId, lastSequenceRef.current);
    } catch (err) {
      setActionBusy(false);
      reportError("接受补丁失败", err);
      await refreshView();
    }
  }

  async function handleRejectPatch(patchId: string) {
    if (!turnId) return;
    setActionBusy(true);
    setError(null);
    try {
      await rejectPatch(turnId, patchId);
      setBusy(true);
      connectStream(turnId, lastSequenceRef.current);
    } catch (err) {
      setActionBusy(false);
      reportError("拒绝补丁失败", err);
      await refreshView();
    }
  }

  async function handleApprove() {
    const toolCallId = view?.interrupt?.tool_call_id ?? pendingToolCallId;
    if (!turnId || !toolCallId) return;
    setActionBusy(true);
    // Optimistic dismiss — do not wait for projection/SSE or the banner sticks
    // with grayed buttons while view.status is still waiting_approval.
    setPendingApproval(false);
    setPendingToolCallId(null);
    setPendingToolName(null);
    setPendingWriteFile(null);
    setView((prev) =>
      prev && prev.status === "waiting_approval"
        ? { ...prev, status: "running", interrupt: null }
        : prev,
    );
    resumingAfterApprovalRef.current = true;
    try {
      if (useWebSocket && streamRef.current instanceof TurnWebSocketClient) {
        streamRef.current.approveToolCall(toolCallId);
      } else {
        await approveToolCall(turnId, toolCallId);
      }
      setBusy(true);
      setActionBusy(false);
      connectStream(turnId, lastSequenceRef.current);
    } catch (err) {
      resumingAfterApprovalRef.current = false;
      setActionBusy(false);
      reportError("批准失败", err);
      await refreshView();
    }
  }

  async function handleDeny() {
    const toolCallId = view?.interrupt?.tool_call_id ?? pendingToolCallId;
    if (!turnId || !toolCallId) return;
    setActionBusy(true);
    setPendingApproval(false);
    setPendingToolCallId(null);
    setPendingToolName(null);
    setPendingWriteFile(null);
    setView((prev) =>
      prev && prev.status === "waiting_approval"
        ? { ...prev, status: "running", interrupt: null }
        : prev,
    );
    resumingAfterApprovalRef.current = true;
    try {
      if (useWebSocket && streamRef.current instanceof TurnWebSocketClient) {
        streamRef.current.denyToolCall(toolCallId);
      } else {
        await denyToolCall(turnId, toolCallId);
      }
      setBusy(true);
      setActionBusy(false);
      connectStream(turnId, lastSequenceRef.current);
    } catch (err) {
      resumingAfterApprovalRef.current = false;
      setActionBusy(false);
      reportError("拒绝失败", err);
      await refreshView();
    }
  }

  const projectedTimeline: TimelineItem[] = (view?.tool_timeline ?? []).map(
    (item) => {
      const row = item as TimelineItem;
      const id = String(row.tool_call_id ?? "");
      const live = id ? toolLiveStreams[id] : undefined;
      return live ? { ...row, stream_output: live } : row;
    },
  );
  const timelineItems: TimelineItem[] =
    liveToolTimeline.length > 0 ? liveToolTimeline : projectedTimeline;
  for (const [toolCallId, stream] of Object.entries(toolLiveStreams)) {
    if (timelineItems.some((t) => String(t.tool_call_id) === toolCallId))
      continue;
    timelineItems.push({
      tool_call_id: toolCallId,
      tool_name: "…",
      status: "running",
      stream_output: stream,
    });
  }

  const displayStatus =
    pendingApproval ||
    (view?.status === "waiting_approval" && Boolean(view?.interrupt?.tool_call_id))
      ? "waiting_approval"
      : busy
        ? "running"
        : (view?.status ?? "idle");

  const contextUsage =
    liveContextUsage ??
    (view?.context_usage as ContextUsage | null | undefined) ??
    null;
  const tokenUsage =
    liveTokenUsage ??
    tokenUsageFromEvents(events) ??
    (view?.token_usage as TokenUsage | null | undefined) ??
    null;
  const plan =
    livePlan ??
    latestPlanFromArtifacts(
      view?.artifacts as Record<string, unknown>[] | undefined,
    );

  const canExecutePlan =
    planAwaitingConfirm &&
    planIsProposedOnly(plan) &&
    !busy &&
    !pendingApproval &&
    view?.status !== "waiting_approval";

  const planPhase: PlanPhase = (() => {
    if (busy && activePlanPhase === "executing") return "executing";
    if (busy && activePlanPhase === "planning") return "planning";
    if (canExecutePlan || planAwaitingConfirm) return "ready";
    if (planMode) return "planning";
    return "off";
  })();

  const suggestOpts = {
    scenarioId: activeScenarioId,
    cooldownActive: isPlanSuggestCooldownActive(planSuggestDismissedAt),
  };
  const planSuggestDecision = shouldSuggestPlanMode(message, suggestOpts);
  const planSuggestReason = planSuggestDecision
    ? planSuggestPrimaryReason(message, suggestOpts)
    : null;

  const showPlanSuggest =
    !planMode && !busy && planSuggestDecision;

  const meta = scenarioMeta(activeScenarioId);

  return {
    scenarioId: activeScenarioId,
    title: meta.title,
    sessionId,
    setActiveScenario: setActiveScenarioId,
    turnHistory,
    historyLoading,
    message,
    setMessage: (value: string) => {
      setMessage(value);
    },
    submittedMessage,
    turnId,
    view,
    events,
    streamText,
    thinkingText,
    sectionDraft,
    timelineItems,
    contextUsage,
    tokenUsage,
    plan,
    planMode,
    setPlanMode: setPlanModeAndClearSuggest,
    planPhase,
    showPlanSuggest,
    planSuggestReason,
    dismissPlanSuggest,
    canExecutePlan,
    handleExecutePlan,
    busy,
    stopping,
    actionBusy,
    error,
    clearError: () => setError(null),
    displayStatus,
    pendingToolCallId: view?.interrupt?.tool_call_id ?? pendingToolCallId,
    pendingToolName:
      String(
        (view?.interrupt as Record<string, string> | undefined)?.tool_name ??
          "",
      ) || pendingToolName,
    pendingWriteFile,
    useWebSocket,
    awaitingApproval:
      (pendingApproval ||
        (view?.status === "waiting_approval" &&
          Boolean(view?.interrupt?.tool_call_id))) &&
      view?.status !== "completed" &&
      view?.status !== "failed" &&
      view?.status !== "cancelled",
    handleSend,
    handleVerify,
    handleStop,
    handleAcceptPatch,
    handleRejectPatch,
    handleApprove,
    handleDeny,
    refreshView,
  };
}

export function placeholderForScenario(scenarioId: ScenarioId): string {
  if (scenarioId === "writing")
    return "依资料写一段并标注引用，或：请改第二节更简洁…";
  if (scenarioId === "interview") return "记录本次访谈要点…";
  return "读取 README.md 并总结…";
}
