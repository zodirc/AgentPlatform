/** Ops URL helpers — used only under `/ops/<secret>/…` (bypass, not workbench). */

export function opsConsolePath(secret: string): string {
  return `/ops/${encodeURIComponent(secret)}/test`;
}

export function opsRetrievalPath(secret: string, turnId?: string): string {
  const base = `/ops/${encodeURIComponent(secret)}/retrieval`;
  return turnId ? `${base}?turn=${encodeURIComponent(turnId)}` : base;
}

export function opsEnvelopePath(secret: string, turnId?: string): string {
  const base = `/ops/${encodeURIComponent(secret)}/envelopes`;
  return turnId ? `${base}?turn=${encodeURIComponent(turnId)}` : base;
}

export function opsRawPath(secret: string, turnId?: string): string {
  const base = `/ops/${encodeURIComponent(secret)}/raw`;
  return turnId ? `${base}?turn=${encodeURIComponent(turnId)}` : base;
}

export function opsWritingPath(secret: string): string {
  return `/ops/${encodeURIComponent(secret)}/writing`;
}

export function opsRunPath(secret: string, runId: string): string {
  return `/ops/${encodeURIComponent(secret)}/test/runs/${runId}`;
}

export function opsHistoryPath(secret: string): string {
  return `/ops/${encodeURIComponent(secret)}/test/history`;
}

export function opsOfficialPath(secret: string, runId?: string): string {
  const base = `/ops/${encodeURIComponent(secret)}/official`;
  return runId ? `${base}/${encodeURIComponent(runId)}` : base;
}

export function secretFromOpsPath(pathname: string): string {
  const m = pathname.match(/^\/ops\/([^/]+)\//);
  return m ? decodeURIComponent(m[1]) : "";
}

export function turnIdFromSearch(search: string): string {
  try {
    return new URLSearchParams(search).get("turn")?.trim() || "";
  } catch {
    return "";
  }
}
