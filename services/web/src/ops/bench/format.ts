export function isActiveStatus(status?: string): boolean {
  return status === "queued" || status === "running" || status === "cancelling";
}

export function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Human duration: 12s · 3m 05s · 1h 02m */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m ${String(rem).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return `${h}h ${String(remM).padStart(2, "0")}m`;
}

export function elapsedSeconds(
  startedIso: string | null | undefined,
  endedIso: string | null | undefined,
  nowMs: number,
): number | null {
  if (!startedIso) return null;
  const start = Date.parse(startedIso);
  if (!Number.isFinite(start)) return null;
  const end = endedIso ? Date.parse(endedIso) : nowMs;
  if (!Number.isFinite(end)) return null;
  return Math.max(0, (end - start) / 1000);
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function cleanPhase(raw: string): string {
  return raw.replace(/^\[phase\]\s*/i, "").trim();
}
