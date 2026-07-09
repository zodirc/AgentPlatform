const SESSION_STORAGE_KEY = "agent_platform_session_id";
const SESSION_QUERY_PARAM = "session";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isSessionId(value: string | null | undefined): value is string {
  return Boolean(value && UUID_RE.test(value));
}

export function readStoredSessionId(): string | null {
  try {
    const value = localStorage.getItem(SESSION_STORAGE_KEY);
    return isSessionId(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeStoredSessionId(sessionId: string) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  } catch {
    // ignore quota / private mode
  }
}

export function clearStoredSessionId() {
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function sessionIdFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get(SESSION_QUERY_PARAM);
  return isSessionId(value) ? value : null;
}

export function sessionIdFromPathname(pathname: string): string | null {
  if (!pathname.startsWith("/s/")) return null;
  const segment = pathname.slice(3).split("/")[0];
  return isSessionId(segment) ? segment : null;
}

/** Preserve session query when navigating between modes. */
export function pathWithSession(pathname: string, sessionId: string | null): string {
  if (!sessionId) return pathname;
  const params = new URLSearchParams();
  params.set(SESSION_QUERY_PARAM, sessionId);
  return `${pathname}?${params.toString()}`;
}

export function shareableSessionPath(sessionId: string): string {
  return `/s/${sessionId}`;
}
