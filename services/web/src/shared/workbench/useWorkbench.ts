import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  acceptPatch,
  approveToolCall,
  cancelTurn,
  denyToolCall,
  fetchSessionView,
  fetchTurnView,
  rejectPatch,
  startTurn,
  type TurnEvent,
  type TurnView,
} from "../api/client";
import { TurnStreamClient } from "../realtime/TurnStreamClient";
import { TurnWebSocketClient } from "../realtime/TurnWebSocketClient";
import type {
  ContextUsage,
  ScenarioId,
  TimelineItem,
  TokenUsage,
  WorkbenchState,
  WriteFilePreview,
} from "./types";
import { previewText } from "./filePreview";
import { scenarioMeta } from "./scenarioMeta";
import { useWorkbenchSession } from "./workbenchSession";

type StreamClient = TurnStreamClient | TurnWebSocketClient;

export function useWorkbenchImpl(): WorkbenchState {
  const [searchParams] = useSearchParams();
  const useWebSocket = searchParams.get("transport") === "ws";
  const [activeScenarioId, setActiveScenarioId] =
    useState<ScenarioId>("writing");
  const [message, setMessage] = useState("");
  const [submittedMessage, setSubmittedMessage] = useState<string | null>(null);
  const [turnId, setTurnId] = useState<string | null>(null);
  const [view, setView] = useState<TurnView | null>(null);
  const [events, setEvents] = useState<TurnEvent[]>([]);
  const [streamText, setStreamText] = useState("");
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
  const streamRef = useRef<StreamClient | null>(null);
  const lastSequenceRef = useRef(0);
  const resumingAfterApprovalRef = useRef(false);
  const sessionRestoredRef = useRef(false);
  const turnIdRef = useRef<string | null>(null);
  turnIdRef.current = turnId;

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

  const turnViewQuery = useQuery({
    queryKey: ["turn-view", turnId],
    queryFn: () => fetchTurnView(turnId!),
    enabled: Boolean(turnId) && !busy,
  });

  useEffect(() => {
    if (turnViewQuery.data) {
      setView(turnViewQuery.data);
      syncApprovalFromView(turnViewQuery.data);
      if (turnViewQuery.data.context_usage) {
        setLiveContextUsage(turnViewQuery.data.context_usage as ContextUsage);
      }
      if (turnViewQuery.data.token_usage) {
        setLiveTokenUsage(turnViewQuery.data.token_usage as TokenUsage);
      }
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
          if (ev.type === "usage.reported" || ev.type === "turn.completed") {
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
            const msg = String(
              ev.payload.message ?? ev.payload.termination_reason ?? "未知错误",
            );
            reportError("任务失败", msg);
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
            resumingAfterApprovalRef.current = false;
          }
        },
        onClose: async () => {
          const v = await fetchTurnView(id);
          setView(v);
          syncApprovalFromView(v);
          if (v.context_usage)
            setLiveContextUsage(v.context_usage as ContextUsage);
          if (v.token_usage) setLiveTokenUsage(v.token_usage as TokenUsage);
          setLiveToolTimeline([]);
          setBusy(false);
          setStopping(false);
          setActionBusy(false);
          resumingAfterApprovalRef.current = false;
        },
        onError: (err?: unknown) => {
          setBusy(false);
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

    void (async () => {
      try {
        const sessionView = await fetchSessionView(sessionId);
        if (cancelled || !sessionView.last_turn_id || turnIdRef.current) return;

        const lastTurnId = sessionView.last_turn_id;
        const v = await fetchTurnView(lastTurnId);
        if (cancelled) return;

        sessionRestoredRef.current = true;
        setTurnId(lastTurnId);
        setView(v);
        setSubmittedMessage(v.user_input ?? null);
        syncApprovalFromView(v);
        if (v.context_usage) {
          setLiveContextUsage(v.context_usage as ContextUsage);
        }
        if (v.token_usage) {
          setLiveTokenUsage(v.token_usage as TokenUsage);
        }
        lastSequenceRef.current = v.last_event_sequence ?? 0;

        const status = sessionView.last_turn_status ?? v.status;
        if (
          status === "running" ||
          status === "waiting_approval" ||
          v.status === "waiting_approval"
        ) {
          setBusy(true);
          connectStream(lastTurnId, lastSequenceRef.current);
        }
      } catch (err) {
        if (!cancelled) {
          reportError("恢复会话失败", err);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- restore once per session
  }, [sessionId]);

  const startTurnMut = useMutation({
    mutationFn: ({ sid, msg }: { sid: string; msg: string }) =>
      startTurn(sid, msg, activeScenarioId),
  });

  async function handleSend() {
    if (!sessionId || !message.trim() || busy) return;
    setBusy(true);
    setError(null);
    setEvents([]);
    setStreamText("");
    setSectionDraft("");
    setToolLiveStreams({});
    setLiveToolTimeline([]);
    setLiveContextUsage(null);
    setLiveTokenUsage(null);
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
      const text = message.trim();
      setSubmittedMessage(text);
      setMessage("");
      const turn = await startTurnMut.mutateAsync({
        sid: sessionId,
        msg: text,
      });
      setTurnId(turn.id);
      connectStream(turn.id);
    } catch (err) {
      setBusy(false);
      reportError("发送失败", err);
    }
  }

  async function handleStop() {
    if (!turnId) return;
    streamRef.current?.stopRendering();
    setStopping(true);
    try {
      await cancelTurn(turnId, false);
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
    setPendingApproval(false);
    setPendingToolCallId(null);
    setPendingToolName(null);
    resumingAfterApprovalRef.current = true;
    try {
      if (useWebSocket && streamRef.current instanceof TurnWebSocketClient) {
        streamRef.current.approveToolCall(toolCallId);
      } else {
        await approveToolCall(turnId, toolCallId);
      }
      setBusy(true);
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
    resumingAfterApprovalRef.current = true;
    try {
      if (useWebSocket && streamRef.current instanceof TurnWebSocketClient) {
        streamRef.current.denyToolCall(toolCallId);
      } else {
        await denyToolCall(turnId, toolCallId);
      }
      setBusy(true);
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
    pendingApproval || view?.status === "waiting_approval"
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
    (view?.token_usage as TokenUsage | null | undefined) ??
    null;

  const meta = scenarioMeta(activeScenarioId);

  return {
    scenarioId: activeScenarioId,
    title: meta.title,
    sessionId,
    setActiveScenario: setActiveScenarioId,
    message,
    setMessage,
    submittedMessage,
    turnId,
    view,
    events,
    streamText,
    sectionDraft,
    timelineItems,
    contextUsage,
    tokenUsage,
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
      (view?.status === "waiting_approval" || pendingApproval) &&
      view?.status !== "completed" &&
      view?.status !== "failed" &&
      view?.status !== "cancelled",
    handleSend,
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
    return "根据 sources 资料写一段并标注引用，或：请改第二节更简洁…";
  if (scenarioId === "interview") return "记录本次访谈要点…";
  return "读取 README.md 并总结…";
}
