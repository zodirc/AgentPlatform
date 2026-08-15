import { SUITE_DETAIL_LABEL } from "./progressParse";
import { suitesFromRun } from "./presets";
import type { OfficialRun } from "./types";

export type SuiteWallTime = {
  key: string;
  label: string;
  elapsedSec: number | null;
  running: boolean;
};

const SUITE_START_RE = /^\[L1\]\s+suite start\s+(\S+)/i;

export function normalizeSuiteKey(raw: string): string {
  const s = String(raw || "")
    .trim()
    .toLowerCase()
    .replace(/^official\./, "");
  if (s === "coding_infer" || s === "coding_pull" || s === "coding") return "coding";
  if (s === "cmteb") return "retrieval_zh";
  return s;
}

function suiteLabel(key: string): string {
  return SUITE_DETAIL_LABEL[key] || key;
}

function parseIsoMs(iso?: string | null): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

function wallFromCase(caseRow: NonNullable<OfficialRun["cases"]>[number]): number | null {
  const top = caseRow.suite_wall_s;
  if (typeof top === "number" && Number.isFinite(top) && top >= 0) return top;
  const nested = caseRow.metrics?.suite_wall_s;
  if (typeof nested === "number" && Number.isFinite(nested) && nested >= 0) return nested;
  return null;
}

/** Wall-clock per L1 suite (sequential). Prefers persisted suite_wall_s; else log starts. */
export function suiteWallTimes(
  run: Pick<OfficialRun, "cases" | "logs" | "finished_at" | "created_at" | "status"> & {
    targets?: string[];
    official_suite?: string;
    model_meta?: OfficialRun["model_meta"];
  },
  nowMs: number,
): SuiteWallTime[] {
  const ordered = suitesFromRun(run);
  const fromCases = new Map<string, number>();
  for (const row of run.cases || []) {
    const key = normalizeSuiteKey(row.case_id);
    const wall = wallFromCase(row);
    if (key && wall != null) fromCases.set(key, wall);
  }

  const starts: Array<{ key: string; atMs: number }> = [];
  for (const item of run.logs || []) {
    const msg = String(item.message || "");
    const m = msg.match(SUITE_START_RE);
    if (!m) continue;
    const atMs = parseIsoMs(item.at);
    if (atMs == null) continue;
    starts.push({ key: normalizeSuiteKey(m[1]), atMs });
  }

  const finishedMs = parseIsoMs(run.finished_at);
  const running = run.status === "queued" || run.status === "running" || run.status === "cancelling";
  const endMs = finishedMs ?? (running ? nowMs : null);

  const keys: string[] = [];
  for (const k of starts.map((s) => s.key)) {
    if (k && !keys.includes(k)) keys.push(k);
  }
  for (const k of ordered) {
    if (!keys.includes(k)) keys.push(k);
  }

  return keys.map((key) => {
    const persisted = fromCases.get(key);
    if (persisted != null) {
      return { key, label: suiteLabel(key), elapsedSec: persisted, running: false };
    }
    const idx = starts.findIndex((s) => s.key === key);
    if (idx < 0) {
      return { key, label: suiteLabel(key), elapsedSec: null, running: false };
    }
    const start = starts[idx].atMs;
    const next = starts[idx + 1]?.atMs;
    const closed = next ?? endMs;
    if (closed == null) {
      return { key, label: suiteLabel(key), elapsedSec: null, running: false };
    }
    const liveTail = next == null && running && finishedMs == null;
    return {
      key,
      label: suiteLabel(key),
      elapsedSec: Math.max(0, (closed - start) / 1000),
      running: Boolean(liveTail),
    };
  });
}
