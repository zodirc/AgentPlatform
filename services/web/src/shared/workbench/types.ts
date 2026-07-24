import type { TurnEvent, TurnView } from "../api/client";
import type { PlanArtifact } from "./plan";

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

export type ContextWindowBreakdown = {
  system?: number;
  tools?: number;
  session?: number;
  user?: number;
  assistant?: number;
  tool_results?: number;
  compaction?: number;
  project?: number;
  runtime?: number;
  volatile?: number;
};

export type ContextUsage = {
  tokens_before?: number;
  tokens_after?: number;
  token_budget?: number;
  reserve_tokens?: number;
  fill_ratio?: number;
  strategies?: string[];
  step_index?: number;
  system_tokens?: number;
  tools_tokens?: number;
  messages_tokens?: number;
  breakdown?: ContextWindowBreakdown;
  source?: "estimated" | "provider";
};

export type TokenUsage = {
  input_tokens?: number;
  output_tokens?: number;
  source?: "provider" | "estimated" | "mixed";
};

export type TurnHistoryItem = {
  id: string;
  scenario_id: ScenarioId;
  status: string;
  user_input: string;
  latest_output: string | null;
  created_at: string;
};

export type WorkbenchState = {
  scenarioId: ScenarioId;
  title: string;
  sessionId: string | null;
  setActiveScenario: (id: ScenarioId) => void;
  turnHistory: TurnHistoryItem[];
  historyLoading: boolean;
  message: string;
  setMessage: (value: string) => void;
  submittedMessage: string | null;
  turnId: string | null;
  view: TurnView | null;
  events: TurnEvent[];
  streamText: string;
  /** Ephemeral reasoning stream for the live turn; not in history/views. */
  thinkingText: string;
  sectionDraft: string;
  timelineItems: TimelineItem[];
  contextUsage: ContextUsage | null;
  tokenUsage: TokenUsage | null;
  /** Latest plan artifact (live event or turn view). */
  plan: PlanArtifact | null;
  /** Explicit Plan mode (docs/25) — user toggled; wraps next send. */
  planMode: boolean;
  setPlanMode: (value: boolean) => void;
  /** Derived Plan phase for UI (off | planning | ready | executing). */
  planPhase: "off" | "planning" | "ready" | "executing";
  /** Multi-goal suggest bar visible. */
  showPlanSuggest: boolean;
  /** Optional one-line reason under the suggest banner (docs/26). */
  planSuggestReason: string | null;
  dismissPlanSuggest: () => void;
  /** True only for Plan-mode proposed checklists awaiting user confirm. */
  canExecutePlan: boolean;
  handleExecutePlan: () => Promise<void>;
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
  /** Composer messages waiting for the live turn to finish (merged on flush). */
  outboundQueue: string[];
  clearOutboundQueue: () => void;
  handleSend: () => Promise<void>;
  handleVerify: () => Promise<void>;
  handleStop: () => Promise<void>;
  handleAcceptPatch: (patchId: string) => Promise<void>;
  handleRejectPatch: (patchId: string) => Promise<void>;
  handleApprove: () => Promise<void>;
  handleDeny: () => Promise<void>;
  refreshView: () => Promise<void>;
};
