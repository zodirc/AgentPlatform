import type { components } from "./schema";

export const API_BASE = "/api/v1";

const ADMIN_AUTH_KEY = "admin_basic_auth";

export type TurnView = components["schemas"]["TurnView"];
export type ModelProvider = components["schemas"]["ModelProviderProfile"];
export type TurnResponse = components["schemas"]["TurnResponse"];

export function setAdminPassword(password: string) {
  localStorage.setItem(ADMIN_AUTH_KEY, btoa(`admin:${password}`));
  try {
    sessionStorage.removeItem(ADMIN_AUTH_KEY);
  } catch {
    // ignore
  }
}

export function clearAdminAuth() {
  localStorage.removeItem(ADMIN_AUTH_KEY);
  try {
    sessionStorage.removeItem(ADMIN_AUTH_KEY);
  } catch {
    // ignore
  }
}

export function hasAdminAuth(): boolean {
  try {
    const fromLocal = localStorage.getItem(ADMIN_AUTH_KEY);
    if (fromLocal) return true;
    const legacy = sessionStorage.getItem(ADMIN_AUTH_KEY);
    if (legacy) {
      localStorage.setItem(ADMIN_AUTH_KEY, legacy);
      sessionStorage.removeItem(ADMIN_AUTH_KEY);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

/** Returns true when the API requires HTTP Basic credentials. */
export async function isAuthRequired(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/admin/model-providers`);
    return res.status === 401;
  } catch {
    return false;
  }
}

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
    token = localStorage.getItem(ADMIN_AUTH_KEY);
  } catch {
    token = null;
  }
  if (!token) return extra;
  return { ...extra, Authorization: `Basic ${token}` };
}

/** End-user session routes: cookie credentials only (no admin Basic). */
export function apiAuthHeaders(extra: HeadersInit = {}): HeadersInit {
  return extra;
}

const sessionFetchInit = { credentials: "include" as RequestCredentials };

export type TurnEvent = {
  event_id: string;
  sequence: number;
  type: string;
  turn_id: string;
  payload: Record<string, unknown>;
};

export type EndUser = { id: string; username: string };

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

export async function fetchMe(): Promise<EndUser | null> {
  const res = await fetch(`${API_BASE}/auth/me`, sessionFetchInit);
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`fetchMe failed: ${res.status}`);
  return res.json() as Promise<EndUser>;
}

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
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  return res.json() as Promise<EndUser>;
}

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
  if (!res.ok) throw new Error(`register failed: ${res.status}`);
  return res.json() as Promise<EndUser>;
}

export async function logoutUser(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, {
    ...sessionFetchInit,
    method: "POST",
  });
}

export async function listSessions(limit = 20): Promise<SessionListItem[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE}/sessions?${params}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`listSessions failed: ${res.status}`);
  return res.json() as Promise<SessionListItem[]>;
}

export async function createSession(
  scenario: "writing" | "agent" | "interview" = "writing",
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

export async function getSession(sessionId: string): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`getSession failed: ${res.status}`);
  return res.json();
}

/** Hard-delete own session (204). Does not remove workspace files. */
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    ...sessionFetchInit,
    method: "DELETE",
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`deleteSession failed: ${res.status}`);
}

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

export async function fetchSessionView(sessionId: string): Promise<SessionView> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/view`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchSessionView failed: ${res.status}`);
  return res.json();
}

export type TurnSummary = {
  id: string;
  session_id: string;
  scenario_id: string;
  status: string;
  user_input: string | null;
  latest_output: string | null;
  created_at: string;
};

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
  if (!res.ok) throw new Error(`startTurn failed: ${res.status}`);
  return res.json() as Promise<TurnResponse>;
}

export async function fetchTurnView(turnId: string): Promise<TurnView> {
  const res = await fetch(`${API_BASE}/turns/${turnId}/view`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchTurnView failed: ${res.status}`);
  return res.json();
}

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

export async function approveToolCall(turnId: string, toolCallId: string) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/approve-tool-call`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ tool_call_id: toolCallId }),
  });
  if (!res.ok) throw new Error(`approveToolCall failed: ${res.status}`);
  return res.json();
}

export async function denyToolCall(
  turnId: string,
  toolCallId: string,
  reason = "user_denied",
) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/deny-tool-call`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ tool_call_id: toolCallId, reason }),
  });
  if (!res.ok) throw new Error(`denyToolCall failed: ${res.status}`);
  return res.json();
}

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

export async function listModelProviders(): Promise<ModelProvider[]> {
  const res = await fetch(`${API_BASE}/admin/model-providers`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`listModelProviders failed: ${res.status}`);
  return res.json();
}

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

export async function activateModelProvider(id: string) {
  const res = await fetch(`${API_BASE}/admin/model-providers/${id}/activate`, {
    ...sessionFetchInit,
    method: "PUT",
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`activateModelProvider failed: ${res.status}`);
  return res.json();
}

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

export async function deleteModelProvider(id: string) {
  const res = await fetch(`${API_BASE}/admin/model-providers/${id}`, {
    ...sessionFetchInit,
    method: "DELETE",
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`deleteModelProvider failed: ${res.status}`);
}

export type WorkspaceEntries = {
  path: string;
  entries: string[];
};

export type WorkspaceFile = {
  path: string;
  content: string;
};

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

export async function fetchWorkspaceFile(path: string): Promise<WorkspaceFile> {
  const params = new URLSearchParams({ path });
  const res = await fetch(`${API_BASE}/admin/workspace/file?${params}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchWorkspaceFile failed: ${res.status}`);
  return res.json();
}

export type WorkspaceDeleteResult = {
  deleted: string[];
  failed: Array<{ path: string; error: string }>;
  summary: string;
  error?: string;
};

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
  /** IX3: always "ingestion" — never effect-quality. */
  plane?: "ingestion" | string;
  ingestion_ready?: boolean;
  /** IX3: always false from this endpoint; effect = prod-bench / hard queries. */
  effect_ready?: boolean;
  hint?: string;
  last_result?: {
    indexed_files?: number;
    chunks?: number;
    added?: number;
    updated?: number;
  } | null;
};

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

/** IX1: queue Turn-external incremental sync (does not block chat). */
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

/** Sanitize a user-facing title into a sources/ filename accepted by the API. */
export function sourceFilenameFromTitle(title: string): string {
  const raw = title.trim() || "paste-note";
  const withoutExt = raw.replace(/\.(md|markdown|txt|json)$/i, "");
  const safe = withoutExt
    .replace(/[^\w\u4e00-\u9fff-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return `${safe || "paste-note"}.md`;
}

/** Paste / type content into sources/ without picking a local file. */
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

/** Debounced typing warm-up for embedder/index (docs/13 S3 A18). Best-effort. */
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
