/** Workspace-root relative path helpers (no React). */

export function joinWorkspacePath(parent: string, name: string): string {
  if (parent === "." || parent === "") return name;
  return `${parent.replace(/\/$/, "")}/${name}`;
}

export function parentDirOf(path: string): string {
  const normalized = path.replace(/\/$/, "");
  const idx = normalized.lastIndexOf("/");
  if (idx < 0) return ".";
  return normalized.slice(0, idx) || ".";
}

/** Workspace-root relative path: `notes/a.md` (never absolute, never leading ./). */
export function toWorkspaceRelativePath(path: string): string {
  let rel = path.trim().replace(/\\/g, "/");
  rel = rel.replace(/^file:\/\//i, "");
  rel = rel.replace(/^\/+(?:workspace|data\/works\/[^/]+)\//i, "");
  rel = rel.replace(/^\/+/, "");
  while (rel.startsWith("./")) rel = rel.slice(2);
  if (!rel || rel === ".") return "";
  return rel;
}

/** Checked if the path itself or any ancestor directory is in the set. */
export function isPathChecked(
  checked: ReadonlySet<string>,
  path: string,
): boolean {
  if (checked.has(path)) return true;
  let parent = parentDirOf(path);
  while (parent && parent !== ".") {
    if (checked.has(parent)) return true;
    parent = parentDirOf(parent);
  }
  return checked.has(".");
}
