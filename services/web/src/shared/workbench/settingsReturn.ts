/** Remember which workbench to reopen after leaving Settings. */

const STORAGE_KEY = "agent_platform_settings_return";

const WORKBENCH_ROOTS = ["/writing", "/agent", "/intel", "/collab"] as const;

function isWorkbenchPathname(pathname: string): boolean {
  return WORKBENCH_ROOTS.some(
    (root) => pathname === root || pathname.startsWith(`${root}/`),
  );
}

/** Call before navigating into /settings from a scenario page. */
export function rememberSettingsReturn(pathWithQuery: string): void {
  try {
    const pathname = pathWithQuery.split("?")[0] || "";
    if (!isWorkbenchPathname(pathname)) return;
    sessionStorage.setItem(STORAGE_KEY, pathWithQuery);
  } catch {
    // ignore quota / private mode
  }
}

/** Path (+ optional ?session=) to leave Settings for. */
export function readSettingsReturn(fallback = "/writing"): string {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const pathname = raw.split("?")[0] || "";
    if (!isWorkbenchPathname(pathname)) return fallback;
    return raw;
  } catch {
    return fallback;
  }
}
