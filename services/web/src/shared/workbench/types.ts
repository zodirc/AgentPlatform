/**
 * 工作台核心类型：场景、时间线、上下文用量、回合历史与 WorkbenchState 契约。
 */
import type { TurnEvent, TurnView } from "../api/client";
import type { PlanArtifact } from "./plan";
import type { OpeningPondsArtifact } from "./openingPonds";
import type { SubagentLive } from "./subagents";

/** 四种工作台场景标识，对应 URL 路径与 startTurn scenario_id。 */
export type ScenarioId = "writing" | "agent" | "intel" | "collab";

/** 工具时间线单项：含运行态、摘要与可选 live 流输出。 */
export type TimelineItem = {
  tool_call_id?: string;
  tool_name?: string;
  status?: string;
  stream_output?: string;
  summary?: string;
  /** 嵌套 delegate 子代理内执行时携带 subagent_id。 */
  subagent_id?: string;
};

/** 写文件/编辑文件审批预览：路径、前后文本与元数据。 */
export type WriteFilePreview = {
  path: string;
  old_text: string;
  new_text: string;
  status?: string;
  truncated?: boolean;
  new_size?: number;
  bytes_written?: number;
  /** write_file 整文件写入；edit_file 局部替换 */
  kind?: "write_file" | "edit_file";
};

/** 上下文窗口各分区 token 估算明细。 */
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

/** 单步或累计的上下文占用报告（来自 context.reported 或 TurnView）。 */
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

/** 输入/输出 token 计数及数据来源（provider 实测或估算）。 */
export type TokenUsage = {
  input_tokens?: number;
  output_tokens?: number;
  source?: "provider" | "estimated" | "mixed";
};

/** 会话历史列表中的一条回合摘要。 */
export type TurnHistoryItem = {
  id: string;
  scenario_id: ScenarioId;
  status: string;
  user_input: string;
  latest_output: string | null;
  created_at: string;
  /** 勾选开篇等 UI 动作：有 user_input 令牌，但对话框不当成「你」的输入。 */
  hideUserInput?: boolean;
  /** 该回合 plan 快照，供聊天流多 plan 历史展示（docs/25）。 */
  plan?: PlanArtifact | null;
  /** 该回合开篇近池候选（点选 / 我要其他的）。 */
  openingPonds?: OpeningPondsArtifact | null;
};

/**
 * 统一工作台 React 上下文状态：四场景共享同一会话、流式输出与审批态。
 * 由 useWorkbenchImpl 构造，WorkbenchProvider 注入。
 */
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
  /** 当前 live 回合的 ephemeral 推理文本，不入历史持久化。 */
  thinkingText: string;
  /** live 事件流中的嵌套子代理（只读迷你对话）。 */
  subagents: SubagentLive[];
  sectionDraft: string;
  timelineItems: TimelineItem[];
  contextUsage: ContextUsage | null;
  tokenUsage: TokenUsage | null;
  /** 最新 plan 制品（live 事件或 turn view）。 */
  plan: PlanArtifact | null;
  /** 最新开篇近池制品（live 事件或 turn view），聊天内点选像 Plan。 */
  openingPonds: OpeningPondsArtifact | null;
  /** 用户显式开启的 Plan 模式，下一次发送会带 plan_phase（docs/25）。 */
  planMode: boolean;
  setPlanMode: (value: boolean) => void;
  /** 派生的 Plan 阶段，驱动 UI：off | planning | ready | executing。 */
  planPhase: "off" | "planning" | "ready" | "executing";
  /** 多目标建议条是否可见。 */
  showPlanSuggest: boolean;
  /** 建议条下方可选的一行理由（docs/26）。 */
  planSuggestReason: string | null;
  dismissPlanSuggest: () => void;
  /** 仅 Plan 模式生成的「全 pending」清单且待用户确认时为 true。 */
  canExecutePlan: boolean;
  handleExecutePlan: () => Promise<void>;
  /** 回读 retcon 清单待用户按此执行。 */
  handleExecuteRetcon: () => Promise<void>;
  /** 最新一轮开篇候选仍待点选（或说「我要其他的」）。 */
  canChooseOpeningPonds: boolean;
  handleSelectOpeningPond: (item: import("./openingPonds").OpeningPondItem) => Promise<void>;
  handleMoreOpeningPonds: () => Promise<void>;
  busy: boolean;
  stopping: boolean;
  actionBusy: boolean;
  error: string | null;
  clearError: () => void;
  displayStatus: string;
  pendingToolCallId: string | null;
  pendingToolName: string | null;
  pendingWriteFile: WriteFilePreview | null;
  /** 写作场景：回合前后 manuscript 快照 diff。 */
  draftDiffPreview: WriteFilePreview | null;
  useWebSocket: boolean;
  awaitingApproval: boolean;
  /** 回合进行中排队待发消息，flush 时 mergeOutboundQueue 合并。 */
  outboundQueue: string[];
  clearOutboundQueue: () => void;
  handleSend: () => Promise<void>;
  handleVerify: () => Promise<void>;
  handleStop: () => Promise<void>;
  handleAcceptPatch: (patchId: string) => Promise<void>;
  handleRejectPatch: (patchId: string) => Promise<void>;
  handleApprove: (opts?: { allowPrefix?: string }) => Promise<void>;
  handleDeny: () => Promise<void>;
  refreshView: () => Promise<void>;
};
