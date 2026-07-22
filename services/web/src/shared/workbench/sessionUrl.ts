const SESSION_STORAGE_PREFIX = "agent_platform_session_id";
const SESSION_STORAGE_KEY_LEGACY = "agent_platform_session_id";
const SESSION_QUERY_PARAM = "session";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function sessionKeyForUser(userId: string | null | undefined): string {
  if (userId) return `${SESSION_STORAGE_PREFIX}:${userId}`;
  return SESSION_STORAGE_KEY_LEGACY;
}

export function isSessionId(value: string | null | undefined): value is string {
  return Boolean(value && UUID_RE.test(value));
}

export function readStoredSessionId(userId?: string | null): string | null {
  try {
    if (userId) {
      const perUser = localStorage.getItem(sessionKeyForUser(userId));
      if (isSessionId(perUser)) return perUser;
      // Migrate legacy global key once into this user.
      const legacy = localStorage.getItem(SESSION_STORAGE_KEY_LEGACY);
      if (isSessionId(legacy)) {
        localStorage.setItem(sessionKeyForUser(userId), legacy);
        return legacy;
      }
      return null;
    }
    const value = localStorage.getItem(SESSION_STORAGE_KEY_LEGACY);
    return isSessionId(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeStoredSessionId(
  sessionId: string,
  userId?: string | null,
) {
  try {
    localStorage.setItem(sessionKeyForUser(userId), sessionId);
    if (userId) {
      localStorage.setItem(SESSION_STORAGE_KEY_LEGACY, sessionId);
    }
  } catch {
    // ignore quota / private mode
  }
}

/** Clear only the active/legacy pointer — keep per-user history keys. */
export function clearStoredSessionId(userId?: string | null) {
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY_LEGACY);
    if (userId) {
      // Keep per-user key so the same user can resume after re-login.
      // Intentionally do not remove sessionKeyForUser(userId).
    }
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
