import {
  useCallback,
  useRef,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";

export type SubagentDeltaBuffer = {
  stream: string;
  thinking: string;
  tools: Record<string, string>;
};

type StreamDeltaBufferOptions = {
  streamTextRef: MutableRefObject<string>;
  sectionDraftRef: MutableRefObject<string>;
  setStreamText: Dispatch<SetStateAction<string>>;
  setThinkingText: Dispatch<SetStateAction<string>>;
  setSectionDraft: Dispatch<SetStateAction<string>>;
  setToolLiveStreams: Dispatch<SetStateAction<Record<string, string>>>;
  setSubagentLive: Dispatch<
    SetStateAction<Record<string, SubagentDeltaBuffer>>
  >;
};

type PendingDeltas = {
  streamText: string;
  thinkingText: string;
  sectionDraft: string;
  toolStreams: Record<string, string>;
  subagents: Record<string, SubagentDeltaBuffer>;
};

function emptyPendingDeltas(): PendingDeltas {
  return {
    streamText: "",
    thinkingText: "",
    sectionDraft: "",
    toolStreams: {},
    subagents: {},
  };
}

export function useStreamDeltaBuffer({
  streamTextRef,
  sectionDraftRef,
  setStreamText,
  setThinkingText,
  setSectionDraft,
  setToolLiveStreams,
  setSubagentLive,
}: StreamDeltaBufferOptions) {
  const deltaFrameRef = useRef<number | null>(null);
  const pendingDeltasRef = useRef<PendingDeltas>(emptyPendingDeltas());

  function flushPendingDeltas() {
    if (deltaFrameRef.current !== null) {
      cancelAnimationFrame(deltaFrameRef.current);
      deltaFrameRef.current = null;
    }
    const pending = pendingDeltasRef.current;
    pendingDeltasRef.current = emptyPendingDeltas();
    if (pending.streamText) {
      streamTextRef.current += pending.streamText;
      setStreamText((text) => text + pending.streamText);
    }
    if (pending.thinkingText) {
      setThinkingText((text) => text + pending.thinkingText);
    }
    if (pending.sectionDraft) {
      sectionDraftRef.current += pending.sectionDraft;
      setSectionDraft((text) => text + pending.sectionDraft);
    }
    if (Object.keys(pending.toolStreams).length > 0) {
      setToolLiveStreams((previous) => {
        const next = { ...previous };
        for (const [toolCallId, delta] of Object.entries(pending.toolStreams)) {
          next[toolCallId] = (next[toolCallId] ?? "") + delta;
        }
        return next;
      });
    }
    if (Object.keys(pending.subagents).length > 0) {
      setSubagentLive((previous) => {
        const next = { ...previous };
        for (const [sid, buf] of Object.entries(pending.subagents)) {
          const current = next[sid] ?? {
            stream: "",
            thinking: "",
            tools: {},
          };
          const tools = { ...current.tools };
          for (const [toolCallId, delta] of Object.entries(buf.tools)) {
            tools[toolCallId] = (tools[toolCallId] ?? "") + delta;
          }
          next[sid] = {
            stream: current.stream + buf.stream,
            thinking: current.thinking + buf.thinking,
            tools,
          };
        }
        return next;
      });
    }
  }

  function scheduleDeltaFlush() {
    if (deltaFrameRef.current !== null) return;
    deltaFrameRef.current = requestAnimationFrame(flushPendingDeltas);
  }

  function pendingSubagentBuffer(sid: string): SubagentDeltaBuffer {
    const buffers = pendingDeltasRef.current.subagents;
    let buffer = buffers[sid];
    if (!buffer) {
      buffer = { stream: "", thinking: "", tools: {} };
      buffers[sid] = buffer;
    }
    return buffer;
  }

  function appendStreamText(delta: string) {
    pendingDeltasRef.current.streamText += delta;
    scheduleDeltaFlush();
  }

  function appendThinkingText(delta: string) {
    pendingDeltasRef.current.thinkingText += delta;
    scheduleDeltaFlush();
  }

  function appendSectionDraft(delta: string) {
    pendingDeltasRef.current.sectionDraft += delta;
    scheduleDeltaFlush();
  }

  function appendToolStream(toolCallId: string, delta: string) {
    const pending = pendingDeltasRef.current.toolStreams;
    pending[toolCallId] = (pending[toolCallId] ?? "") + delta;
    scheduleDeltaFlush();
  }

  function appendSubagentStream(sid: string, delta: string) {
    pendingSubagentBuffer(sid).stream += delta;
    scheduleDeltaFlush();
  }

  function appendSubagentThinking(sid: string, delta: string) {
    pendingSubagentBuffer(sid).thinking += delta;
    scheduleDeltaFlush();
  }

  function appendSubagentTool(sid: string, toolCallId: string, delta: string) {
    const buffer = pendingSubagentBuffer(sid);
    buffer.tools[toolCallId] = (buffer.tools[toolCallId] ?? "") + delta;
    scheduleDeltaFlush();
  }

  const clearPendingDeltas = useCallback(() => {
    if (deltaFrameRef.current !== null) {
      cancelAnimationFrame(deltaFrameRef.current);
      deltaFrameRef.current = null;
    }
    pendingDeltasRef.current = emptyPendingDeltas();
  }, []);

  return {
    appendSectionDraft,
    appendStreamText,
    appendSubagentStream,
    appendSubagentThinking,
    appendSubagentTool,
    appendThinkingText,
    appendToolStream,
    clearPendingDeltas,
    flushPendingDeltas,
  };
}
