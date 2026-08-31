/**
 * 前端 HTTP API 客户端：/api/v1 下认证、会话、回合、工作区与管理端接口。
 * 终端用户路由使用 cookie（credentials: include）；管理端 Basic 存 sessionStorage。
 */
import type { components } from "./schema";
import { throwIfNotOk } from "./httpErrors";
import { newClientRequestId } from "./clientRequestId";

/** API 根路径前缀。 */
export const API_BASE = "/api/v1";

const ADMIN_AUTH_KEY = "admin_basic_auth";

/** OpenAPI 生成的回合视图类型。 */
export type TurnView = components["schemas"]["TurnView"];
/** 模型供应商配置。 */
export type ModelProvider = components["schemas"]["ModelProviderProfile"];
/** startTurn 响应体。 */
export type TurnResponse = components["schemas"]["TurnResponse"];

/**
 * 将管理端密码写入 sessionStorage（Basic auth token）。
 * @param password ADMIN_PASSWORD 明文
 */
export function setAdminPassword(password: string) {
  const token = btoa(`admin:${password}`);
  try {
    sessionStorage.setItem(ADMIN_AUTH_KEY, token);
  } catch {
    // ignore
  }
  try {
    localStorage.removeItem(ADMIN_AUTH_KEY);
  } catch {
    // ignore
  }
}

/** 清除 session/local 中的管理端 Basic 凭证。 */
export function clearAdminAuth() {
  try {
    sessionStorage.removeItem(ADMIN_AUTH_KEY);
  } catch {
    // ignore
  }
  try {
    localStorage.removeItem(ADMIN_AUTH_KEY);
  } catch {
    // ignore
  }
}

/**
 * 是否已有管理端 Basic token（localStorage 会迁移到 sessionStorage）。
 * @returns 存在有效 token 时为 true
 */
export function hasAdminAuth(): boolean {
  try {
    if (sessionStorage.getItem(ADMIN_AUTH_KEY)) return true;
    const fromLocal = localStorage.getItem(ADMIN_AUTH_KEY);
    if (fromLocal) {
      sessionStorage.setItem(ADMIN_AUTH_KEY, fromLocal);
      localStorage.removeItem(ADMIN_AUTH_KEY);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * 探测 API 是否要求 HTTP Basic 认证。
 * @returns 访问 /admin/model-providers 返回 401 时为 true
 */
export async function isAuthRequired(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/admin/model-providers`);
    return res.status === 401;
  } catch {
    return false;
  }
}

/**
 * 用当前 sessionStorage 中的 Basic token 验证管理端权限。
 * @returns token 有效且 /admin/model-providers 成功时为 true
 */
export async function verifyAdminAuth(): Promise<boolean> {
  if (!hasAdminAuth()) return false;
  const res = await fetch(`${API_BASE}/admin/model-providers`, {
    headers: adminAuthHeaders(),
  });
  return res.ok;
}

function adminAuthHeaders(extra: HeadersInit = {}): HeadersInit {
  let token: string | null = null;
  try {
    token = sessionStorage.getItem(ADMIN_AUTH_KEY);
  } catch {
    token = null;
  }
  if (!token) {
    try {
      token = localStorage.getItem(ADMIN_AUTH_KEY);
      if (token) {
        sessionStorage.setItem(ADMIN_AUTH_KEY, token);
        localStorage.removeItem(ADMIN_AUTH_KEY);
      }
    } catch {
      token = null;
    }
  }
  if (!token) return extra;
  return { ...extra, Authorization: `Basic ${token}` };
}

/**
 * 终端用户 API 请求头：仅 cookie 鉴权，不附带 admin Basic。
 * @param extra 额外头字段
 * @returns 合并后的 HeadersInit
 */
export function apiAuthHeaders(extra: HeadersInit = {}): HeadersInit {
  return extra;
}

const sessionFetchInit = { credentials: "include" as RequestCredentials };

/** 回合 SSE/WS 事件单条结构（耐久 PG 或 live Redis 扇出）。 */
export type TurnEvent = {
  event_id: string;
  /** Durable PG sequence; null when live fanout. */
  sequence: number | null;
  /** True for Redis turn.live.* envelopes (not a turn_events row). */
  live?: boolean;
  /** Per-turn live ordering when live=true. */
  live_seq?: number;
  type: string;
  turn_id: string;
  payload: Record<string, unknown>;
  /** turn_events / live 时间戳（ISO），用于耗时计时。 */
  ts?: string;
};

/** 当前登录的终端用户摘要。 */
export type EndUser = { id: string; username: string };

/** 会话列表 API 单项。 */
export type SessionListItem = {
  id: string;
  default_scenario_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  title: string | null;
  last_user_preview: string | null;
  last_turn_status: string | null;
};

/**
 * 获取当前 cookie 会话对应用户；未登录返回 null。
 * @returns EndUser 或 null（401）
 */
export async function fetchMe(): Promise<EndUser | null> {
  const res = await fetch(`${API_BASE}/auth/me`, sessionFetchInit);
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`fetchMe failed: ${res.status}`);
  return res.json() as Promise<EndUser>;
}

/**
 * 用户名密码登录，建立 cookie 会话。
 * @param username 用户名
 * @param password 密码
 * @returns 登录后的用户信息
 */
export async function loginUser(
  username: string,
  password: string,
): Promise<EndUser> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    ...sessionFetchInit,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  await throwIfNotOk(res, "login");
  return res.json() as Promise<EndUser>;
}

/**
 * 注册新用户并自动登录。
 * @param username 用户名
 * @param password 密码
 * @returns 新用户信息
 */
export async function registerUser(
  username: string,
  password: string,
): Promise<EndUser> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    ...sessionFetchInit,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  await throwIfNotOk(res, "register");
  return res.json() as Promise<EndUser>;
}

/** 登出：使服务端 session 失效。 */
export async function logoutUser(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, {
    ...sessionFetchInit,
    method: "POST",
  });
}

/**
 * 修改当前用户密码。
 * @param currentPassword 当前密码
 * @param newPassword 新密码
 */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/password`, {
    ...sessionFetchInit,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  if (!res.ok) {
    let detail = `changePassword failed: ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
}

/** 用户 Work 空间摘要。 */
export type WorkSummary = {
  id: string;
  name: string;
  work_root: string;
  is_default: boolean;
  visibility_seed?: boolean;
  created_at?: string | null;
};

/**
 * 获取当前用户的默认 Work。
 * @returns Work 元数据（含 work_root、visibility_seed 等）
 */
export async function fetchDefaultWork(): Promise<WorkSummary> {
  const res = await fetch(`${API_BASE}/works/default`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchDefaultWork failed: ${res.status}`);
  return res.json() as Promise<WorkSummary>;
}

/**
 * 更新 Work 的 visibility_seed 开关。
 * @param workId Work UUID
 * @param visibilitySeed 是否对检索可见
 */
export async function patchWorkVisibilitySeed(
  workId: string,
  visibilitySeed: boolean,
): Promise<WorkSummary> {
  const res = await fetch(`${API_BASE}/works/${workId}`, {
    ...sessionFetchInit,
    method: "PATCH",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ visibility_seed: visibilitySeed }),
  });
  if (!res.ok) {
    let detail = `patchWork failed: ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json() as Promise<WorkSummary>;
}

/**
 * 分页列出当前用户的会话。
 * @param limit 最大条数，默认 20
 */
export async function listSessions(limit = 20): Promise<SessionListItem[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE}/sessions?${params}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`listSessions failed: ${res.status}`);
  return res.json() as Promise<SessionListItem[]>;
}

/**
 * 创建新会话。
 * @param scenario 默认场景 id，默认 writing
 * @returns 含新 session id 的对象
 */
export async function createSession(
  scenario: "writing" | "agent" | "intel" | "collab" = "writing",
) {
  const res = await fetch(`${API_BASE}/sessions`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ default_scenario_id: scenario }),
  });
  if (!res.ok) throw new Error(`createSession failed: ${res.status}`);
  return res.json() as Promise<{ id: string }>;
}

/**
 * 校验并获取会话元数据（存在性检查）。
 * @param sessionId 会话 UUID
 */
export async function getSession(sessionId: string): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`getSession failed: ${res.status}`);
  return res.json();
}

/**
 * 硬删除自有会话（204）；不删除工作区文件。
 * @param sessionId 会话 UUID
 */
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    ...sessionFetchInit,
    method: "DELETE",
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`deleteSession failed: ${res.status}`);
}

/**
 * 批量硬删除会话（服务端一次请求）。
 * @param sessionIds 待删 session id 列表
 * @returns deleted 与 missing  id 列表
 */
export async function deleteSessionsBulk(
  sessionIds: string[],
): Promise<{ deleted: string[]; missing: string[] }> {
  const res = await fetch(`${API_BASE}/sessions/bulk-delete`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ session_ids: sessionIds }),
  });
  if (!res.ok) throw new Error(`deleteSessionsBulk failed: ${res.status}`);
  let body: { deleted?: unknown; missing?: unknown };
  try {
    body = (await res.json()) as { deleted?: unknown; missing?: unknown };
  } catch {
    throw new Error("deleteSessionsBulk: unexpected response");
  }
  if (!Array.isArray(body.deleted) || !Array.isArray(body.missing)) {
    throw new Error("deleteSessionsBulk: unexpected response");
  }
  return {
    deleted: body.deleted.map(String),
    missing: body.missing.map(String),
  };
}

/** 会话聚合视图（turn 计数、最后状态等）。 */
export type SessionView = {
  session_id: string;
  default_scenario_id: string;
  status: string;
  turn_count: number;
  last_turn_id: string | null;
  last_turn_status: string | null;
  context_summary?: Record<string, unknown> | null;
  updated_at: string;
};

/**
 * GET /sessions/:id/view — 会话级摘要。
 * @param sessionId 会话 UUID
 */
export async function fetchSessionView(sessionId: string): Promise<SessionView> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/view`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchSessionView failed: ${res.status}`);
  return res.json();
}

/** 单条回合列表项。 */
export type TurnSummary = {
  id: string;
  session_id: string;
  scenario_id: string;
  status: string;
  user_input: string | null;
  latest_output: string | null;
  created_at: string;
  /** turn_views 中最新 plan 制品（聊天多 plan 历史可选）。 */
  plan?: Record<string, unknown> | null;
};

/**
 * 列出会话下所有回合摘要。
 * @param sessionId 会话 UUID
 */
export async function fetchSessionTurns(
  sessionId: string,
): Promise<TurnSummary[]> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/turns`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchSessionTurns failed: ${res.status}`);
  return res.json();
}

/**
 * 在会话中发起新回合。
 * @param sessionId 会话 UUID
 * @param message 用户消息
 * @param scenarioId 场景 id
 * @param opts.plan_phase Plan 模式阶段（planning | executing）
 */
export async function startTurn(
  sessionId: string,
  message: string,
  scenarioId: string,
  opts?: { plan_phase?: "planning" | "executing" | null },
) {
  const body: {
    message: string;
    scenario_id: string;
    plan_phase?: "planning" | "executing";
  } = { message, scenario_id: scenarioId };
  if (opts?.plan_phase === "planning" || opts?.plan_phase === "executing") {
    body.plan_phase = opts.plan_phase;
  }
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/turns`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    await throwIfNotOk(res, "startTurn");
  }
  return res.json() as Promise<TurnResponse>;
}

// I19: conditional view polling — unchanged views come back as 304 with no
// body; serve the cached copy instead. Bounded to the most recent turns.
const viewCache = new Map<string, { etag: string; view: TurnView }>();
const VIEW_CACHE_MAX = 64;

/**
 * 获取回合投影视图；支持 ETag 条件请求与客户端 LRU 缓存（I19）。
 * @param turnId 回合 UUID
 */
export async function fetchTurnView(turnId: string): Promise<TurnView> {
  const cached = viewCache.get(turnId);
  const res = await fetch(`${API_BASE}/turns/${turnId}/view`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(
      cached ? { "If-None-Match": cached.etag } : {},
    ),
  });
  if (res.status === 304 && cached) return cached.view;
  if (!res.ok) throw new Error(`fetchTurnView failed: ${res.status}`);
  const view = (await res.json()) as TurnView;
  const etag = res.headers.get("etag");
  if (etag) {
    viewCache.delete(turnId);
    viewCache.set(turnId, { etag, view });
    while (viewCache.size > VIEW_CACHE_MAX) {
      const oldest = viewCache.keys().next().value;
      if (oldest === undefined) break;
      viewCache.delete(oldest);
    }
  }
  return view;
}

async function fetchTurnEventsPage(
  turnId: string,
  sinceSequence: number,
): Promise<{ events: TurnEvent[]; last_sequence: number; has_more: boolean }> {
  const q = new URLSearchParams({
    since_sequence: String(Math.max(0, sinceSequence)),
  });
  const res = await fetch(`${API_BASE}/turns/${turnId}/events?${q}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchTurnEvents failed: ${res.status}`);
  const data = (await res.json()) as {
    events?: TurnEvent[];
    last_sequence?: number;
    has_more?: boolean;
  };
  return {
    events: Array.isArray(data.events) ? data.events : [],
    last_sequence: Number(data.last_sequence ?? 0),
    has_more: Boolean(data.has_more),
  };
}

/**
 * 拉取回合事件快照；自动翻页 has_more（I19）。
 * @param turnId 回合 UUID
 * @param sinceSequence 起始 sequence，默认 0
 * @returns events 与 last_sequence
 */
export async function fetchTurnEvents(
  turnId: string,
  sinceSequence = 0,
): Promise<{ events: TurnEvent[]; last_sequence: number }> {
  // I19: the API pages long streams; follow has_more so callers still see the
  // full snapshot.
  const events: TurnEvent[] = [];
  let cursor = sinceSequence;
  for (;;) {
    const page = await fetchTurnEventsPage(turnId, cursor);
    events.push(...page.events);
    cursor = page.last_sequence;
    if (!page.has_more || page.events.length === 0) {
      return { events, last_sequence: cursor };
    }
  }
}

/**
 * 取消运行中回合。
 * @param turnId 回合 UUID
 * @param force true 时强制终止
 */
export async function cancelTurn(turnId: string, force = false) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/cancel`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ reason: "user_requested", force }),
  });
  if (!res.ok) throw new Error(`cancelTurn failed: ${res.status}`);
  return res.json();
}

/**
 * 批准待审工具调用。
 * @param turnId 回合 UUID
 * @param toolCallId 工具调用 id
 * @param allowPrefix run_command 可选命令前缀白名单
 */
export async function approveToolCall(
  turnId: string,
  toolCallId: string,
  allowPrefix?: string,
) {
  const prefix = (allowPrefix ?? "").trim();
  const res = await fetch(`${API_BASE}/turns/${turnId}/approve-tool-call`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      tool_call_id: toolCallId,
      // Lets the API replay (not re-execute) duplicate submissions.
      client_request_id: newClientRequestId(),
      ...(prefix ? { allow_prefix: prefix } : {}),
    }),
  });
  if (!res.ok) throw new Error(`approveToolCall failed: ${res.status}`);
  return res.json();
}

/**
 * 拒绝待审工具调用。
 * @param turnId 回合 UUID
 * @param toolCallId 工具调用 id
 * @param reason 拒绝原因，默认 user_denied
 */
export async function denyToolCall(
  turnId: string,
  toolCallId: string,
  reason = "user_denied",
) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/deny-tool-call`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      tool_call_id: toolCallId,
      reason,
      client_request_id: newClientRequestId(),
    }),
  });
  if (!res.ok) throw new Error(`denyToolCall failed: ${res.status}`);
  return res.json();
}

/**
 * 接受 writing 场景生成的 patch。
 * @param turnId 回合 UUID
 * @param patchId patch id
 */
export async function acceptPatch(turnId: string, patchId: string) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/patch/accept`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ patch_id: patchId }),
  });
  if (!res.ok) throw new Error(`acceptPatch failed: ${res.status}`);
  return res.json();
}

/**
 * 拒绝 writing patch。
 * @param turnId 回合 UUID
 * @param patchId patch id
 * @param reason 拒绝原因，默认 user_rejected
 */
export async function rejectPatch(
  turnId: string,
  patchId: string,
  reason = "user_rejected",
) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/patch/reject`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ patch_id: patchId, reason }),
  });
  if (!res.ok) throw new Error(`rejectPatch failed: ${res.status}`);
  return res.json();
}

/** 列出已配置的模型供应商。 */
export async function listModelProviders(): Promise<ModelProvider[]> {
  const res = await fetch(`${API_BASE}/admin/model-providers`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`listModelProviders failed: ${res.status}`);
  return res.json();
}

/**
 * 创建模型供应商配置。
 * @param body label、provider、model_name、api_key 等
 */
export async function createModelProvider(body: {
  label: string;
  provider: string;
  model_name: string;
  api_key: string;
  base_url?: string;
  context_window_tokens?: number;
  activate?: boolean;
}) {
  const res = await fetch(`${API_BASE}/admin/model-providers`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ ...body, activate: body.activate ?? true }),
  });
  if (!res.ok) throw new Error(`createModelProvider failed: ${res.status}`);
  return res.json();
}

/**
 * 激活指定模型供应商为当前默认。
 * @param id 供应商配置 id
 */
export async function activateModelProvider(id: string) {
  const res = await fetch(`${API_BASE}/admin/model-providers/${id}/activate`, {
    ...sessionFetchInit,
    method: "PUT",
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`activateModelProvider failed: ${res.status}`);
  return res.json();
}

/**
 * 更新模型供应商字段（部分 PATCH 语义 PUT）。
 * @param id 供应商配置 id
 * @param body 待更新字段
 */
export async function updateModelProvider(
  id: string,
  body: {
    label?: string;
    provider?: string;
    model_name?: string;
    api_key?: string;
    base_url?: string;
    context_window_tokens?: number;
  },
) {
  const res = await fetch(`${API_BASE}/admin/model-providers/${id}`, {
    ...sessionFetchInit,
    method: "PUT",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`updateModelProvider failed: ${res.status}`);
  return res.json();
}

/**
 * 删除模型供应商配置。
 * @param id 供应商配置 id
 */
export async function deleteModelProvider(id: string) {
  const res = await fetch(`${API_BASE}/admin/model-providers/${id}`, {
    ...sessionFetchInit,
    method: "DELETE",
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`deleteModelProvider failed: ${res.status}`);
}

/** 工作区目录列表响应。 */
export type WorkspaceEntries = {
  path: string;
  entries: string[];
};

/** 工作区单文件内容与截断标记。 */
export type WorkspaceFile = {
  path: string;
  content: string;
  truncated?: boolean;
  file_bytes?: number;
};

/**
 * 列出工作区目录条目。
 * @param path 相对路径，默认 "."
 */
export async function fetchWorkspaceEntries(
  path = ".",
): Promise<WorkspaceEntries> {
  const params = new URLSearchParams({ path });
  const res = await fetch(`${API_BASE}/admin/workspace/entries?${params}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchWorkspaceEntries failed: ${res.status}`);
  return res.json();
}

/**
 * 读取工作区文本文件。
 * @param path 相对路径
 */
export async function fetchWorkspaceFile(path: string): Promise<WorkspaceFile> {
  const params = new URLSearchParams({ path });
  const res = await fetch(`${API_BASE}/admin/workspace/file?${params}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchWorkspaceFile failed: ${res.status}`);
  return res.json();
}

/**
 * 写入或覆盖工作区文件。
 * @param path 相对路径
 * @param content 文件全文
 */
export async function saveWorkspaceFile(
  path: string,
  content: string,
): Promise<WorkspaceFile & { bytes_written?: number; status?: string }> {
  const res = await fetch(`${API_BASE}/admin/workspace/file`, {
    method: "PUT",
    ...sessionFetchInit,
    headers: {
      ...apiAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path, content }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`saveWorkspaceFile failed: ${res.status} ${detail}`);
  }
  return res.json();
}

/**
 * 在工作区创建目录。
 * @param path 相对路径
 */
export async function mkdirWorkspacePath(
  path: string,
): Promise<{ path: string; status: string; summary?: string }> {
  const res = await fetch(`${API_BASE}/admin/workspace/entries/mkdir`, {
    method: "POST",
    ...sessionFetchInit,
    headers: {
      ...apiAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`mkdirWorkspacePath failed: ${res.status} ${detail}`);
  }
  return res.json();
}

/**
 * 重命名或移动工作区路径。
 * @param path 源路径
 * @param newPath 目标路径
 * @param overwrite 目标存在时是否覆盖
 */
export async function renameWorkspacePath(
  path: string,
  newPath: string,
  overwrite = false,
): Promise<{ path: string; new_path: string; status: string; summary?: string }> {
  const res = await fetch(`${API_BASE}/admin/workspace/entries/rename`, {
    method: "POST",
    ...sessionFetchInit,
    headers: {
      ...apiAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path, new_path: newPath, overwrite }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`renameWorkspacePath failed: ${res.status} ${detail}`);
  }
  return res.json();
}

function basenameFromPath(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || "download";
}

function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) return null;
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      // fall through
    }
  }
  const plain =
    /filename\s*=\s*"([^"]+)"/i.exec(header) ||
    /filename\s*=\s*([^;]+)/i.exec(header);
  return plain?.[1]?.trim() ?? null;
}

/**
 * 下载工作区文件（触发浏览器保存对话框）。
 * @param path 相对路径
 */
export async function downloadWorkspaceFile(path: string): Promise<void> {
  const params = new URLSearchParams({ path });
  const res = await fetch(`${API_BASE}/admin/workspace/download?${params}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`downloadWorkspaceFile failed: ${res.status} ${detail}`);
  }
  const blob = await res.blob();
  const name =
    filenameFromContentDisposition(res.headers.get("Content-Disposition")) ||
    basenameFromPath(path);
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** 批量删除工作区路径的结果。 */
export type WorkspaceDeleteResult = {
  deleted: string[];
  failed: Array<{ path: string; error: string }>;
  summary: string;
  error?: string;
};

/**
 * 批量删除工作区文件或目录。
 * @param paths 相对路径列表
 */
export async function deleteWorkspacePaths(
  paths: string[],
): Promise<WorkspaceDeleteResult> {
  const res = await fetch(`${API_BASE}/admin/workspace/entries/delete`, {
    method: "POST",
    ...sessionFetchInit,
    headers: {
      ...apiAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ paths }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`deleteWorkspacePaths failed: ${res.status} ${detail}`);
  }
  return res.json();
}

/** sources/ 上传 API 响应。 */
export type SourceUploadResult = {
  path: string;
  bytes_written: number;
  summary: string;
  index?: {
    status?: string;
    path?: string;
    indexed_files?: number;
    chunks?: number;
    added?: number;
    updated?: number;
  };
};

/** RAG 索引构建过程的 live 进度字段。 */
export type SourcesIndexProgress = {
  status?: string;
  phase?: string;
  reason?: string;
  visibility?: string;
  label?: string;
  path?: string | null;
  error?: string | null;
  files_done?: number | null;
  files_total?: number | null;
  dirty_files?: number | null;
  chunks_embedded?: number | null;
  chunks_total?: number | null;
  rate_chunks_per_s?: number | null;
  elapsed_s?: number | null;
  eta_s?: number | null;
  embedding_backend?: string | null;
  batch_size?: number | null;
  updated_at?: string | null;
  plane?: string;
  effect_ready?: boolean;
  last_result?: SourcesIndexStatus["last_result"];
};

/** sources 向量索引整体状态（ingestion 平面，非 effect 质量）。 */
export type SourcesIndexStatus = {
  status: "idle" | "building" | "ready" | "error" | string;
  path?: string | null;
  error?: string | null;
  indexed_files?: number;
  chunks?: number;
  updated_at?: string | null;
  embedding_backend?: string;
  path_indexed?: boolean;
  path_current?: boolean;
  /** IX3：恒为 ingestion，不代表检索效果质量。 */
  plane?: "ingestion" | string;
  ingestion_ready?: boolean;
  /** IX3：此端点恒 false；effect 见 prod-bench / 硬查询。 */
  effect_ready?: boolean;
  hint?: string;
  /** 跨进程共享的 live sync 进度（scan/embed/write）。 */
  progress?: SourcesIndexProgress | null;
  last_result?: {
    indexed_files?: number;
    chunks?: number;
    added?: number;
    updated?: number;
  } | null;
};

/**
 * 查询 sources 索引状态，可选按 path 过滤。
 * @param path 相对 sources 路径
 */
export async function fetchSourcesIndexStatus(
  path?: string,
): Promise<SourcesIndexStatus> {
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  const qs = params.toString();
  const res = await fetch(
    `${API_BASE}/admin/workspace/sources/index-status${qs ? `?${qs}` : ""}`,
    { ...sessionFetchInit, headers: apiAuthHeaders() },
  );
  if (!res.ok) {
    throw new Error(`fetchSourcesIndexStatus failed: ${res.status}`);
  }
  return res.json();
}

/** Agent 工作区 AST 索引元数据（与 RAG sources 索引分离）。 */
export type AstIndexStatus = {
  work_id?: string;
  owner_user_id?: string;
  status?:
    | "cold"
    | "building"
    | "ready"
    | "stale"
    | "error"
    | "disabled"
    | "scan_pending"
    | string;
  generation?: number;
  files_total?: number;
  files_done?: number;
  files_indexed?: number;
  files_stored?: number;
  pending_upsert?: number;
  pending_delete?: number;
  jobs_pending?: number;
  jobs_running?: number;
  catchup_remaining?: number;
  catchup_total?: number;
  error?: string | null;
  enabled?: boolean;
};

/**
 * 查询 AST 索引状态；可选 enqueue 扫描任务。
 * @param opts.enqueue 是否入队 catch-up
 * @param opts.workId 指定 Work id
 */
export async function fetchAstIndexStatus(opts?: {
  enqueue?: boolean;
  workId?: string;
}): Promise<AstIndexStatus> {
  const params = new URLSearchParams();
  if (opts?.enqueue) params.set("enqueue", "true");
  if (opts?.workId) params.set("work_id", opts.workId);
  const qs = params.toString();
  const res = await fetch(
    `${API_BASE}/admin/workspace/ast-index/status${qs ? `?${qs}` : ""}`,
    { ...sessionFetchInit, headers: apiAuthHeaders() },
  );
  if (!res.ok) {
    throw new Error(`fetchAstIndexStatus failed: ${res.status}`);
  }
  return res.json();
}

/**
 * 触发 AST 索引全量或增量重建。
 * @param opts.workId Work id
 * @param opts.memoryOnly 仅内存索引
 */
export async function rebuildAstIndex(opts?: {
  workId?: string;
  memoryOnly?: boolean;
}): Promise<{ accepted?: boolean; work_id?: string }> {
  const params = new URLSearchParams();
  if (opts?.workId) params.set("work_id", opts.workId);
  if (opts?.memoryOnly) params.set("memory_only", "true");
  const qs = params.toString();
  const res = await fetch(
    `${API_BASE}/admin/workspace/ast-index/rebuild${qs ? `?${qs}` : ""}`,
    {
      ...sessionFetchInit,
      method: "POST",
      headers: apiAuthHeaders(),
    },
  );
  if (!res.ok) {
    throw new Error(`rebuildAstIndex failed: ${res.status}`);
  }
  return res.json();
}

/**
 * 清空 AST 索引数据。
 * @param opts.workId Work id
 */
export async function purgeAstIndex(opts?: {
  workId?: string;
}): Promise<Record<string, unknown>> {
  const params = new URLSearchParams();
  if (opts?.workId) params.set("work_id", opts.workId);
  const qs = params.toString();
  const res = await fetch(
    `${API_BASE}/admin/workspace/ast-index/purge${qs ? `?${qs}` : ""}`,
    {
      ...sessionFetchInit,
      method: "POST",
      headers: apiAuthHeaders(),
    },
  );
  if (!res.ok) {
    throw new Error(`purgeAstIndex failed: ${res.status}`);
  }
  return res.json();
}

/**
 * 排队 Turn 外增量 sources 同步（不阻塞聊天，IX1）。
 * @returns accepted 与 index.status
 */
export async function syncSourcesIndex(): Promise<{
  accepted?: boolean;
  index?: { status?: string };
}> {
  const res = await fetch(`${API_BASE}/admin/workspace/sources/sync`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders(),
  });
  if (!res.ok) {
    const detail = await res.text();
    let message = detail || `syncSourcesIndex failed: ${res.status}`;
    try {
      const parsed = JSON.parse(detail) as {
        error?: { message?: string };
        detail?: string;
      };
      message = parsed.error?.message || parsed.detail || message;
    } catch {
      // keep raw text
    }
    throw new Error(message);
  }
  return res.json();
}

/**
 * 上传文件到 sources/ 并触发索引。
 * @param file 浏览器 File 对象
 */
export async function uploadSourceFile(
  file: File,
): Promise<SourceUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/admin/workspace/sources/upload`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders(),
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    let message = detail || `uploadSourceFile failed: ${res.status}`;
    try {
      const parsed = JSON.parse(detail) as {
        error?: { message?: string };
        detail?: string;
      };
      message = parsed.error?.message || parsed.detail || message;
    } catch {
      // keep raw text
    }
    throw new Error(message);
  }
  return res.json();
}

/**
 * 将用户标题 sanitize 为 sources/ 下可接受的 .md 文件名。
 * @param title 原始标题
 * @returns 安全文件名（含 .md 后缀）
 */
export function sourceFilenameFromTitle(title: string): string {
  const raw = title.trim() || "paste-note";
  const withoutExt = raw.replace(/\.(md|markdown|txt|json)$/i, "");
  const safe = withoutExt
    .replace(/[^\w\u4e00-\u9fff-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return `${safe || "paste-note"}.md`;
}

/**
 * 粘贴/输入文本写入 sources/，无需本地选文件。
 * @param title 用作文件名基础的标题
 * @param content Markdown 正文
 */
export async function uploadSourceText(
  title: string,
  content: string,
): Promise<SourceUploadResult> {
  const filename = sourceFilenameFromTitle(title);
  const file = new File([content], filename, {
    type: "text/markdown;charset=utf-8",
  });
  return uploadSourceFile(file);
}

/**
 * 防抖输入时的检索 warm-up（embedder/index，docs/13 S3 A18）；失败静默忽略。
 * @param prefix 可选查询前缀，最长 200 字符
 */
export async function warmupRetrieval(prefix = ""): Promise<void> {
  const params = new URLSearchParams();
  if (prefix.trim()) params.set("prefix", prefix.slice(0, 200));
  const qs = params.toString();
  const url = qs
    ? `${API_BASE}/retrieval/warmup?${qs}`
    : `${API_BASE}/retrieval/warmup`;
  try {
    await fetch(url, {
      ...sessionFetchInit,
      method: "POST",
      headers: apiAuthHeaders(),
    });
  } catch {
    // Ignore warm-up failures.
  }
}

/** 写作范例引用（作者/作品/节拍）。 */
export type WritingExemplarRef = {
  author: string;
  work: string;
  beat: string;
};

/** 管理端写作偏好（权重、信号、范例与 schema 版本）。 */
export type WritingPrefs = {
  preset_label: string;
  fragment_weights: Record<string, Record<string, number>>;
  signal_penalties: Record<string, Record<string, number>> | Record<string, number>;
  signal_rewards: Record<string, Record<string, number>> | Record<string, number>;
  exemplars?: Record<string, WritingExemplarRef[]>;
  schema_version: number;
  updated_at: string | null;
  is_custom: boolean;
};

/** 获取当前写作偏好配置。 */
export async function fetchWritingPrefs(): Promise<WritingPrefs> {
  const res = await fetch(`${API_BASE}/admin/writing-prefs`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(adminAuthHeaders()),
  });
  await throwIfNotOk(res, "fetchWritingPrefs");
  return (await res.json()) as WritingPrefs;
}

/**
 * 更新写作偏好（部分字段）。
 * @param body preset_label、fragment_weights 等
 */
export async function updateWritingPrefs(body: {
  preset_label?: string;
  fragment_weights?: Record<string, Record<string, number>>;
  signal_penalties?: Record<string, Record<string, number>> | Record<string, number>;
  signal_rewards?: Record<string, Record<string, number>> | Record<string, number>;
}): Promise<WritingPrefs> {
  const res = await fetch(`${API_BASE}/admin/writing-prefs`, {
    method: "PUT",
    ...sessionFetchInit,
    headers: {
      ...apiAuthHeaders(adminAuthHeaders()),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  await throwIfNotOk(res, "updateWritingPrefs");
  return (await res.json()) as WritingPrefs;
}

/** 重置写作偏好为服务端默认值。 */
export async function resetWritingPrefs(): Promise<WritingPrefs> {
  const res = await fetch(`${API_BASE}/admin/writing-prefs/reset`, {
    method: "POST",
    ...sessionFetchInit,
    headers: apiAuthHeaders(adminAuthHeaders()),
  });
  await throwIfNotOk(res, "resetWritingPrefs");
  return (await res.json()) as WritingPrefs;
}
