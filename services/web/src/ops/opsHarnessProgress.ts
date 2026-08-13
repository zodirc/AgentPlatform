/** Coherent mid-run harness progress for Ops UI (tqdm bar vs postfix can lag). */

export type HarnessCounters = {
  phase?: string | null;
  done: number | null;
  total: number | null;
  n: number | null;
  pct: number | null;
  resolved: number | null;
  unresolved: number | null;
  error: number | null;
};

export type HarnessProgressView = {
  done: number | null;
  total: number | null;
  pct: number | null;
  resolved: number | null;
  unresolved: number | null;
  error: number | null;
};

/**
 * Prefer outcome postfix (✓/✖/err) when it is ahead of the tqdm bar so the
 * card never shows e.g. 3/5 with ✓2·✖2 (4 results).
 */
export function harnessProgressView(h: HarnessCounters): HarnessProgressView {
  const total = h.total ?? h.n;
  const hasOutcomes =
    h.resolved != null || h.unresolved != null || h.error != null;
  const resolved = hasOutcomes ? (h.resolved ?? 0) : null;
  const unresolved = hasOutcomes ? (h.unresolved ?? 0) : null;
  const error = hasOutcomes ? (h.error ?? 0) : null;
  const outcomes =
    hasOutcomes && resolved != null && unresolved != null && error != null
      ? resolved + unresolved + error
      : null;

  let done = h.done;
  if (outcomes != null) {
    const bar = h.done ?? 0;
    done = total != null ? Math.min(total, Math.max(bar, outcomes)) : Math.max(bar, outcomes);
  }

  let pct = h.pct;
  if (done != null && total != null && total > 0) {
    pct = Math.min(100, Math.round((100 * done) / total));
  } else if (h.phase === "done") {
    pct = 100;
  }

  return { done, total, pct, resolved, unresolved, error };
}
