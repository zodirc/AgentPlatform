/** Standing seed corpus under sources/seed/ (RO mount; docs/15 · docs/27). */

export function isSeedCorpusPath(path: string): boolean {
  const normalized = path.trim().replace(/^\/+/, "").replace(/\\/g, "/");
  return (
    normalized === "sources/seed" ||
    normalized.startsWith("sources/seed/") ||
    normalized === "seed" ||
    normalized.startsWith("seed/")
  );
}

/** Path relative to sources/ (e.g. seed/writing/periods/periods1.md). */
export function isSeedRelUnderSources(rel: string): boolean {
  const normalized = rel.trim().replace(/^\/+/, "").replace(/\\/g, "/");
  return normalized === "seed" || normalized.startsWith("seed/");
}
