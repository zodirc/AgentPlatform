import type { OfficialRun } from "./types";
import { targetsFromRun } from "./progressParse";

export function isEffectEligible(r: OfficialRun): boolean {
  /** Only completed runs; exclude dry / skip_api / reclaimed from effect aggregates. */
  if (String(r.status || "") !== "completed") return false;
  if (r.model_meta?.reclaimed) return false;
  const err = String(r.error || "");
  if (err.includes("reclaimed")) return false;
  const dry = r.context_dry ?? r.model_meta?.context_dry;
  const skip = r.coding_skip_api ?? r.model_meta?.coding_skip_api;
  const targets = targetsFromRun(r);
  if (targets.includes("context") && dry) return false;
  if (targets.includes("coding_infer") && skip) return false;
  // Hash smoke retrieval is not an effect score.
  const prod = r.retrieval_prod ?? r.model_meta?.retrieval_prod;
  if (targets.includes("retrieval") && prod === false && targets.length === 1)
    return false;
  if (
    targets.includes("retrieval_zh") &&
    prod === false &&
    targets.length === 1
  )
    return false;
  return true;
}

export function runMetrics(
  r: OfficialRun | null | undefined,
): Record<string, number> {
  if (!r) return {};
  const m = r.metrics || r.summary?.metrics || {};
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(m)) {
    if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
  }
  // Also flatten case metrics with prefix for comparison richness
  for (const c of r.cases || []) {
    for (const [k, v] of Object.entries(c.metrics || {})) {
      if (typeof v === "number" && Number.isFinite(v)) {
        out[`${c.case_id}.${k}`] = v;
      }
    }
  }
  return dropAliasedMetrics(out);
}

/** Drop L1 `agent.*` copies when the unprefixed twin already exists. */
export function dropAliasedMetrics(
  m: Record<string, number>,
): Record<string, number> {
  const out = { ...m };
  for (const k of Object.keys(out)) {
    if (!k.includes("agent.")) continue;
    const stripped = k.startsWith("agent.")
      ? k.slice("agent.".length)
      : k.replace(".agent.", ".");
    if (stripped === k || !(stripped in out)) continue;
    if (out[stripped] === out[k]) delete out[k];
  }
  return out;
}

/** Prefer official effect metrics; fall back through prefixed case keys. */
export function historyHeadlineMetric(m: Record<string, number>): {
  label: string;
  value: number;
} | null {
  const prefer = [
    "resolve_rate",
    "official.coding.resolve_rate",
    "official.coding_infer.resolve_rate",
    "ndcg_at_10",
    "retention_vs_full_f1",
    "patch_rate",
    "official.coding.patch_rate",
    "official.coding_infer.patch_rate",
    "n_instances",
    "official.coding.n_instances",
  ];
  for (const k of prefer) {
    const v = m[k];
    if (typeof v === "number" && Number.isFinite(v)) {
      const short = k.includes(".") ? k.split(".").pop() || k : k;
      return { label: short, value: v };
    }
  }
  for (const [k, v] of Object.entries(m)) {
    if (k.endsWith("resolve_rate") && Number.isFinite(v)) {
      return { label: "resolve_rate", value: v };
    }
  }
  for (const [k, v] of Object.entries(m)) {
    if (k.endsWith("patch_rate") && Number.isFinite(v)) {
      return { label: "patch_rate", value: v };
    }
  }
  return null;
}

export function median(sorted: number[]): number {
  if (!sorted.length) return Number.NaN;
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

export type MetricAgg = {
  key: string;
  n: number;
  min: number;
  median: number;
  mean: number;
  max: number;
  latest: number;
};

export function aggregateMetrics(runs: OfficialRun[]): MetricAgg[] {
  const byKey: Record<string, number[]> = {};
  const latestByKey: Record<string, number> = {};
  for (const r of runs) {
    if (!isEffectEligible(r)) continue;
    const m = runMetrics(r);
    if (!Object.keys(m).length) continue;
    for (const [k, v] of Object.entries(m)) {
      (byKey[k] ||= []).push(v);
      // runs is newest-first from list; first write wins as latest
      if (!(k in latestByKey)) latestByKey[k] = v;
    }
  }
  return Object.keys(byKey)
    .sort()
    .map((key) => {
      const vals = byKey[key].slice().sort((a, b) => a - b);
      const sum = vals.reduce((a, b) => a + b, 0);
      return {
        key,
        n: vals.length,
        min: vals[0],
        median: median(vals),
        mean: sum / vals.length,
        max: vals[vals.length - 1],
        latest: latestByKey[key],
      };
    });
}
