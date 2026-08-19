import type { QueryClient } from "@tanstack/react-query";
import { fetchWorkspaceEntries } from "../../shared/api/client";
import { isWorkSurfaceHiddenPath } from "../../shared/workspace/harnessPath";
import { isSeedCorpusPath } from "../../shared/workspace/seedPath";
import {
  joinWorkspacePath,
  parentDirOf,
  toWorkspaceRelativePath,
} from "./workspacePaths";
import { patchWorkspaceEntriesCache } from "./WorkspaceTree";

const HIDDEN_ENTRIES = new Set([
  ".ruff_cache",
  "__pycache__",
  ".git",
  ".agent",
]);

const WRITE_TOOLS = new Set([
  "write_file",
  "edit_file",
  "draft_section",
  "update_outline",
  "export_document",
  "propose_patch",
  "apply_patch",
]);

export type WorkspaceChild = {
  name: string;
  path: string;
  isDir: boolean;
};

export function parseWorkspaceListing(
  parentPath: string,
  entries: string[],
): WorkspaceChild[] {
  return entries
    .filter((entry) => {
      const name = entry.endsWith("/") ? entry.slice(0, -1) : entry;
      if (HIDDEN_ENTRIES.has(name)) return false;
      const full = joinWorkspacePath(parentPath, name);
      return !isWorkSurfaceHiddenPath(full);
    })
    .map((entry) => {
      const isDir = entry.endsWith("/");
      const name = isDir ? entry.slice(0, -1) : entry;
      return {
        name,
        path: joinWorkspacePath(parentPath, name),
        isDir,
      };
    });
}

export {
  joinWorkspacePath,
  parentDirOf,
  toWorkspaceRelativePath,
  isPathChecked,
} from "./workspacePaths";

export function isSelectableWorkspacePath(path: string): boolean {
  return (
    path !== "." &&
    !isSeedCorpusPath(path) &&
    !isWorkSurfaceHiddenPath(path)
  );
}

/** Dir itself plus every nested file/dir (skips seed / harness). */
export async function collectDescendantPaths(
  fetchEntries: (path: string) => Promise<string[]>,
  dir: string,
): Promise<{ paths: string[]; dirs: string[] }> {
  const paths: string[] = [];
  const dirs: string[] = [dir];
  const stack = [dir];
  while (stack.length > 0) {
    const current = stack.pop() as string;
    let entries: string[] = [];
    try {
      entries = await fetchEntries(current);
    } catch {
      continue;
    }
    for (const child of parseWorkspaceListing(current, entries)) {
      if (!isSelectableWorkspacePath(child.path)) continue;
      paths.push(child.path);
      if (child.isDir) {
        dirs.push(child.path);
        stack.push(child.path);
      }
    }
  }
  return { paths, dirs };
}

/** Walk already-fetched listings only (no network). Stops at dirs not in cache. */
export function collectCachedDescendants(
  getEntries: (dir: string) => string[] | undefined,
  dir: string,
): { paths: string[]; dirs: string[] } {
  const paths: string[] = [];
  const dirs: string[] = [dir];
  const stack = [dir];
  while (stack.length > 0) {
    const current = stack.pop() as string;
    const entries = getEntries(current);
    if (!entries) continue;
    for (const child of parseWorkspaceListing(current, entries)) {
      if (!isSelectableWorkspacePath(child.path)) continue;
      paths.push(child.path);
      if (child.isDir) {
        dirs.push(child.path);
        stack.push(child.path);
      }
    }
  }
  return { paths, dirs };
}

export function collectDescendantPathsWithClient(
  queryClient: QueryClient,
  dir: string,
): Promise<{ paths: string[]; dirs: string[] }> {
  return collectDescendantPaths(async (path) => {
    const data = await fetchWorkspaceEntries(path);
    queryClient.setQueryData(["workspace-entries", path], data);
    return data.entries;
  }, dir);
}

/** Directories that must be expanded so `paths` (files or dirs) are visible. */
export function expandPathsForReveal(paths: readonly string[]): string[] {
  const out = new Set<string>(["."]);
  for (const raw of paths) {
    const rel = toWorkspaceRelativePath(raw);
    if (!rel) continue;
    let acc = ".";
    const parts = rel.split("/").filter(Boolean);
    for (const part of parts) {
      acc = joinWorkspacePath(acc, part);
      out.add(acc);
    }
  }
  return [...out];
}

/** Patch + invalidate parent listings so the tree shows newly written files. */
export function syncWorkspaceTreeForWrites(
  queryClient: QueryClient,
  paths: readonly string[],
): string[] {
  const parents = new Set<string>();
  for (const raw of paths) {
    const rel = toWorkspaceRelativePath(raw);
    if (!rel) continue;
    const parts = rel.split("/").filter(Boolean);
    if (parts.length === 0) continue;
    let acc = ".";
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const isLast = i === parts.length - 1;
      patchWorkspaceEntriesCache(queryClient, acc, name, !isLast);
      parents.add(acc);
      if (!isLast) {
        acc = joinWorkspacePath(acc, name);
      }
    }
  }
  for (const parent of parents) {
    void queryClient.invalidateQueries({
      queryKey: ["workspace-entries", parent],
      refetchType: "all",
    });
  }
  return expandPathsForReveal([...paths]);
}

export function writtenWorkspacePathsFromTurn(input: {
  artifacts?: Array<Record<string, unknown>>;
  events?: Array<{ type: string; payload: Record<string, unknown> }>;
}): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const add = (raw: unknown) => {
    if (typeof raw !== "string" || !raw.trim()) return;
    const rel = toWorkspaceRelativePath(raw);
    if (!rel || seen.has(rel)) return;
    seen.add(rel);
    out.push(rel);
  };
  for (const art of input.artifacts ?? []) {
    const type = String(art.type ?? "");
    if (
      type === "file_write" ||
      type === "outline" ||
      type === "section_draft" ||
      type === "section.draft"
    ) {
      add(art.path);
    }
    add(art.output_path);
    add(art.export_path);
    add(art.outline_path);
  }
  const writeCompletedIds = new Set<string>();
  for (const ev of input.events ?? []) {
    if (ev.type === "outline.updated") {
      add(ev.payload.path);
      add(ev.payload.outline_path);
      continue;
    }
    if (ev.type === "patch.applied") {
      add(ev.payload.path);
      continue;
    }
    if (ev.type !== "tool.completed") continue;
    const name = String(ev.payload.tool_name ?? "");
    if (!WRITE_TOOLS.has(name)) continue;
    if (String(ev.payload.status ?? "") === "error") continue;
    add(ev.payload.path);
    add(ev.payload.output_path);
    add(ev.payload.outline_path);
    add(ev.payload.export_path);
    const id = String(ev.payload.tool_call_id ?? "");
    if (id) writeCompletedIds.add(id);
  }
  for (const ev of input.events ?? []) {
    if (ev.type !== "tool.started") continue;
    const id = String(ev.payload.tool_call_id ?? "");
    if (!id || !writeCompletedIds.has(id)) continue;
    const args = ev.payload.arguments;
    if (!args || typeof args !== "object") continue;
    const rec = args as Record<string, unknown>;
    add(rec.path);
    add(rec.output_path);
  }
  return out;
}

export function dropCheckedUnder(
  checked: ReadonlySet<string>,
  dir: string,
): Set<string> {
  const next = new Set(checked);
  next.delete(dir);
  const prefix = `${dir}/`;
  for (const path of checked) {
    if (path === dir || path.startsWith(prefix)) next.delete(path);
  }
  return next;
}

export function uncheckAncestors(
  checked: ReadonlySet<string>,
  path: string,
): Set<string> {
  const next = new Set(checked);
  next.delete(path);
  let parent = parentDirOf(path);
  while (parent && parent !== ".") {
    next.delete(parent);
    parent = parentDirOf(parent);
  }
  next.delete(".");
  return next;
}

/**
 * Uncheck one file that may only be selected via a parent directory.
 * Materialize cached siblings first so they stay checked.
 */
export function uncheckFileKeepingSiblings(
  checked: ReadonlySet<string>,
  path: string,
  getEntries: (dir: string) => string[] | undefined,
): Set<string> {
  let ancestor: string | null = null;
  let walk = parentDirOf(path);
  while (walk && walk !== ".") {
    if (checked.has(walk)) {
      ancestor = walk;
      break;
    }
    walk = parentDirOf(walk);
  }
  const next = new Set(checked);
  if (ancestor) {
    const { paths } = collectCachedDescendants(getEntries, ancestor);
    for (const child of paths) next.add(child);
  }
  return uncheckAncestors(next, path);
}
