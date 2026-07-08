import type { TurnEvent, TurnView } from "../api/client";

export type ScenarioId = "writing" | "agent" | "interview";

export type TimelineItem = {
  tool_call_id?: string;
  tool_name?: string;
  status?: string;
  stream_output?: string;
  summary?: string;
};

export type WriteFilePreview = {
  path: string;
  old_text: string;
  new_text: string;
  status?: string;
  truncated?: boolean;
  new_size?: number;
  bytes_written?: number;
};

export type ContextUsage = {
  tokens_before?: number;
  tokens_after?: number;
  token_budget?: number;
  strategies?: string[];
  step_index?: number;
  system_tokens?: number;
  tools_tokens?: number;
  messages_tokens?: number;
  source?: "estimated" | "provider";
};

export type TokenUsage = {
  input_tokens?: number;
  output_tokens?: number;
  source?: "provider" | "estimated" | "mixed";
};

export type WorkbenchState = {
  scenarioId: ScenarioId;
  title: string;
  message: string;
  setMessage: (value: string) => void;
  submittedMessage: string | null;
  turnId: string | null;
  view: TurnView | null;
  events: TurnEvent[];
  streamText: string;
  sectionDraft: string;
  timelineItems: TimelineItem[];
  contextUsage: ContextUsage | null;
  tokenUsage: TokenUsage | null;
  busy: boolean;
  stopping: boolean;
  actionBusy: boolean;
  error: string | null;
  clearError: () => void;
  displayStatus: string;
  pendingToolCallId: string | null;
  pendingToolName: string | null;
  pendingWriteFile: WriteFilePreview | null;
  useWebSocket: boolean;
  awaitingApproval: boolean;
  handleSend: () => Promise<void>;
  handleStop: () => Promise<void>;
  handleAcceptPatch: (patchId: string) => Promise<void>;
  handleRejectPatch: (patchId: string) => Promise<void>;
  handleApprove: () => Promise<void>;
  handleDeny: () => Promise<void>;
  refreshView: () => Promise<void>;
};
