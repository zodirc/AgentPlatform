/** Recursively list files under workspace sources/ for the library UI. */

import { fetchWorkspaceEntries } from "../../shared/api/client";

const SKIP_NAMES = new Set([".gitkeep", ".DS_Store"]);

/**
 * Walk ``sources/`` (and nested dirs). Returns paths relative to ``sources/``
 * (e.g. ``writing/foo.md``, ``seed/writing/dramas/drama1.md``).
 */
export async function listSourcesLibraryFiles(
  listEntries: (path: string) => Promise<{ entries?: string[] }> = fetchWorkspaceEntries,
  root = "sources",
): Promise<string[]> {
  const out: string[] = [];

  async function walk(dir: string, relPrefix: string): Promise<void> {
    const data = await listEntries(dir);
    const entries = data.entries ?? [];
    for (const entry of entries) {
      if (!entry || entry === "./" || entry === "../") continue;
      if (entry.endsWith("/")) {
        const name = entry.slice(0, -1);
        if (!name || name.startsWith(".")) continue;
        const childRel = relPrefix ? `${relPrefix}/${name}` : name;
        await walk(`${dir}/${name}`, childRel);
        continue;
      }
      if (entry.startsWith(".") || SKIP_NAMES.has(entry)) continue;
      out.push(relPrefix ? `${relPrefix}/${entry}` : entry);
    }
  }

  await walk(root, "");
  return out.sort((a, b) => a.localeCompare(b));
}
