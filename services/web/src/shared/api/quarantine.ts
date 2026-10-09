import { API_BASE, apiAuthHeaders } from "./client";

const sessionFetchInit = { credentials: "include" as RequestCredentials };

export async function viewQuarantine(itemId: string): Promise<{ id: string; body: string }> {
  const res = await fetch(`${API_BASE}/quarantine/${itemId}`, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`viewQuarantine failed: ${res.status}`);
  return res.json();
}

export async function releaseQuarantine(
  itemId: string,
): Promise<{ released: boolean; body?: string }> {
  const res = await fetch(`${API_BASE}/quarantine/${itemId}/release`, {
    ...sessionFetchInit,
    method: "POST",
    headers: apiAuthHeaders(),
  });
  if (!res.ok) throw new Error(`releaseQuarantine failed: ${res.status}`);
  return res.json();
}
