const RELOAD_KEY = "web:stale-chunk-reload";

/** Vite hashed chunk vanished after a rebuild; browser still holds the old graph. */
export function isStaleChunkError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error ?? "");
  return /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed/i.test(
    msg,
  );
}

/** Reload once per tab session so a deploy does not loop if the new HTML is also broken. */
export function reloadOnceOnStaleChunk(): boolean {
  try {
    if (sessionStorage.getItem(RELOAD_KEY)) return false;
    sessionStorage.setItem(RELOAD_KEY, "1");
  } catch {
    /* private mode / blocked storage */
  }
  window.location.reload();
  return true;
}

export function installStaleChunkReload(): void {
  window.addEventListener("vite:preloadError", (event) => {
    event.preventDefault();
    reloadOnceOnStaleChunk();
  });
  window.addEventListener("unhandledrejection", (event) => {
    if (!isStaleChunkError(event.reason)) return;
    event.preventDefault();
    reloadOnceOnStaleChunk();
  });
}
