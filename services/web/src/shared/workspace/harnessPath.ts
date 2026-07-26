/** Paths that belong on disk but not on the default workbench file tree. */

/** Runtime harness tree (drafts, turn manifests, verify reports). */
export function isHarnessInternalPath(path: string): boolean {
  const normalized = path.trim().replace(/^\/+/, "").replace(/\\/g, "/");
  return normalized === ".agent" || normalized.startsWith(".agent/");
}

/** WN1 continuity candidates — not confirmed cards; do not auto-pin. */
export function isContinuityPendingPath(path: string): boolean {
  const normalized = path.trim().replace(/^\/+/, "").replace(/\\/g, "/");
  return (
    normalized === "sources/cards/pending" ||
    normalized.startsWith("sources/cards/pending/")
  );
}

/** Hide from workspace tree / multi-delete affordances. */
export function isWorkSurfaceHiddenPath(path: string): boolean {
  return isHarnessInternalPath(path) || isContinuityPendingPath(path);
}
