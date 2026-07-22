/** Recently used usernames for login chips (no passwords). */

const STORAGE_KEY = "agent.auth.recent_usernames";
const MAX_RECENT = 5;

export function readRecentUsernames(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((v): v is string => typeof v === "string" && v.trim().length > 0)
      .map((v) => v.trim())
      .slice(0, MAX_RECENT);
  } catch {
    return [];
  }
}

export function rememberUsername(username: string): void {
  const cleaned = username.trim();
  if (!cleaned) return;
  const next = [
    cleaned,
    ...readRecentUsernames().filter(
      (u) => u.toLowerCase() !== cleaned.toLowerCase(),
    ),
  ].slice(0, MAX_RECENT);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore
  }
}
