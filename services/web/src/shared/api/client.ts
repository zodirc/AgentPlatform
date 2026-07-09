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

function authHeaders(extra: HeadersInit = {}): HeadersInit {
  let token: string | null = null;
  try {
    token = localStorage.getItem(ADMIN_AUTH_KEY);
  } catch {
    token = null;
  }
  if (!token) return extra;
  return { ...extra, Authorization: `Basic ${token}` };
}

/** Auth headers for turn/stream API calls (SSE fetch, view refresh, etc.). */
export function apiAuthHeaders(extra: HeadersInit = {}): HeadersInit {
  return authHeaders(extra);
}

function adminAuthHeaders(): HeadersInit {
  return authHeaders();
}

export type TurnEvent = {
  event_id: string;
  sequence: number;
  type: string;
  turn_id: string;
  payload: Record<string, unknown>;
};

export async function createSession(
  scenario: "writing" | "agent" | "interview" = "writing",
) {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ default_scenario_id: scenario }),
  });
  if (!res.ok) throw new Error(`createSession failed: ${res.status}`);
  return res.json() as Promise<{ id: string }>;
}

export async function startTurn(
  sessionId: string,
  message: string,
  scenarioId: string,
) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/turns`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ message, scenario_id: scenarioId }),
  });
  if (!res.ok) throw new Error(`startTurn failed: ${res.status}`);
  return res.json() as Promise<TurnResponse>;
}

export async function fetchTurnView(turnId: string): Promise<TurnView> {
  const res = await fetch(`${API_BASE}/turns/${turnId}/view`, {
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchTurnView failed: ${res.status}`);
  return res.json();
}

export async function cancelTurn(turnId: string, force = false) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/cancel`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ reason: "user_requested", force }),
  });
  if (!res.ok) throw new Error(`cancelTurn failed: ${res.status}`);
  return res.json();
}

export async function approveToolCall(turnId: string, toolCallId: string) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/approve-tool-call`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ tool_call_id: toolCallId, reason }),
  });
  if (!res.ok) throw new Error(`denyToolCall failed: ${res.status}`);
  return res.json();
}

export async function acceptPatch(turnId: string, patchId: string) {
  const res = await fetch(`${API_BASE}/turns/${turnId}/patch/accept`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ patch_id: patchId, reason }),
  });
  if (!res.ok) throw new Error(`rejectPatch failed: ${res.status}`);
  return res.json();
}

export async function listModelProviders(): Promise<ModelProvider[]> {
  const res = await fetch(`${API_BASE}/admin/model-providers`, {
    headers: adminAuthHeaders(),
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
    method: "POST",
    headers: { "Content-Type": "application/json", ...adminAuthHeaders() },
    body: JSON.stringify({ ...body, activate: body.activate ?? true }),
  });
  if (!res.ok) throw new Error(`createModelProvider failed: ${res.status}`);
  return res.json();
}

export async function activateModelProvider(id: string) {
  const res = await fetch(`${API_BASE}/admin/model-providers/${id}/activate`, {
    method: "PUT",
    headers: adminAuthHeaders(),
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
    method: "PUT",
    headers: { "Content-Type": "application/json", ...adminAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`updateModelProvider failed: ${res.status}`);
  return res.json();
}

export async function deleteModelProvider(id: string) {
  const res = await fetch(`${API_BASE}/admin/model-providers/${id}`, {
    method: "DELETE",
    headers: adminAuthHeaders(),
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
    headers: adminAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchWorkspaceEntries failed: ${res.status}`);
  return res.json();
}

export async function fetchWorkspaceFile(path: string): Promise<WorkspaceFile> {
  const params = new URLSearchParams({ path });
  const res = await fetch(`${API_BASE}/admin/workspace/file?${params}`, {
    headers: adminAuthHeaders(),
  });
  if (!res.ok) throw new Error(`fetchWorkspaceFile failed: ${res.status}`);
  return res.json();
}

export type SourceUploadResult = {
  path: string;
  bytes_written: number;
  summary: string;
  index?: {
    indexed_files?: number;
    chunks?: number;
    added?: number;
    updated?: number;
  };
};

export async function uploadSourceFile(file: File): Promise<SourceUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/admin/workspace/sources/upload`, {
    method: "POST",
    headers: adminAuthHeaders(),
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `uploadSourceFile failed: ${res.status}`);
  }
  return res.json();
}
