import type {
  AstIndexLive,
  CodingCaseLive,
  CodingHarnessLive,
  CodingLiveEvent,
} from "./types";
import { AST_INDEX_WEAK_STATUSES } from "./types";

export const HARNESS_STAGE_LABEL: Record<string, string> = {
  load_dataset: "加载数据集",
  images_ready: "镜像就绪",
  evaluating: "按题评测中",
  instances_done: "实例跑完",
};

/** Parse Ops log ``at`` (ISO) into epoch ms; null if missing/invalid. */
export function parseLogAtMs(at: string | null | undefined): number | null {
  if (at == null || !String(at).trim()) return null;
  const ms = Date.parse(String(at));
  return Number.isFinite(ms) ? ms : null;
}

/** Prefer the earlier start so refresh / late SSE cannot reset a live timer. */
export function preferEarlierStartedAtMs(
  a: number | null | undefined,
  b: number | null | undefined,
): number | null {
  const av = a != null && Number.isFinite(a) ? a : null;
  const bv = b != null && Number.isFinite(b) ? b : null;
  if (av == null) return bv;
  if (bv == null) return av;
  return Math.min(av, bv);
}

export type ParseCodingLiveOpts = {
  /** Log event timestamp (ISO). Used for running-case wall clock across refresh. */
  at?: string | null;
  /** Fallback clock when ``at`` is absent (live first sighting). */
  nowMs?: number;
};

/** Parse `[L1] coding …` / harness lines into the coding progress card. */
export function parseCodingLiveLine(
  line: string,
  opts?: ParseCodingLiveOpts,
): CodingLiveEvent | null {
  const plan = line.match(/^\[L1\]\s+coding\s+plan\s+n=(\d+)\b/i);
  if (plan) {
    return { kind: "plan", n: Number(plan[1]) };
  }
  const start = line.match(/^\[L1\]\s+coding\s+case\s+start\s+(\S+)/i);
  if (start) {
    const fromLog = parseLogAtMs(opts?.at);
    const startedAtMs =
      fromLog ??
      (opts?.nowMs != null && Number.isFinite(opts.nowMs)
        ? opts.nowMs
        : Date.now());
    return {
      kind: "case",
      case: {
        iid: start[1],
        status: "running",
        startedAtMs,
        steps: null,
        elapsedSec: null,
      },
    };
  }
  const done = line.match(
    /^\[L1\]\s+coding\s+(\d+)\s*\/\s*(\d+)\s+(\S+)(?:\s+status=(\S+))?(?:\s+bucket=(\S+))?(?:\s+patch_source=(\S+))?(?:\s+steps=(\d+))?(?:\s+elapsed_s=([0-9.]+))?(?:\s+error=.*)?/i,
  );
  if (done) {
    const statusRaw = (done[4] || "").toLowerCase();
    const status: CodingCaseLive["status"] =
      statusRaw === "pass" ? "pass" : statusRaw === "fail" ? "fail" : "pass";
    const stepsRaw = done[7];
    const elapsedRaw = done[8];
    return {
      kind: "case",
      case: {
        iid: done[3],
        status,
        bucket: done[5] || undefined,
        patchSource: done[6] || undefined,
        steps:
          stepsRaw != null && Number.isFinite(Number(stepsRaw))
            ? Number(stepsRaw)
            : null,
        elapsedSec:
          elapsedRaw != null && Number.isFinite(Number(elapsedRaw))
            ? Number(elapsedRaw)
            : null,
      },
    };
  }
  const hProgress = line.match(
    /^\[L1\]\s+coding\s+harness\s+progress\s+done=(\d+)\/(\d+)\s+pct=(\d+)\s+resolved=(\d+)\s+unresolved=(\d+)\s+error=(\d+)/i,
  );
  if (hProgress) {
    return {
      kind: "harness",
      harness: {
        phase: "running",
        done: Number(hProgress[1]),
        total: Number(hProgress[2]),
        n: Number(hProgress[2]),
        pct: Number(hProgress[3]),
        resolved: Number(hProgress[4]),
        unresolved: Number(hProgress[5]),
        error: Number(hProgress[6]),
        stage: "evaluating",
      },
    };
  }
  const hStage = line.match(
    /^\[L1\]\s+coding\s+harness\s+stage\s+(\S+)(?:\s+n=(\d+))?(?:\s+detail=(.*))?$/i,
  );
  if (hStage) {
    const patch: Partial<CodingHarnessLive> & {
      phase: CodingHarnessLive["phase"];
    } = {
      phase: "running",
      stage: hStage[1],
    };
    if (hStage[2] != null) {
      patch.n = Number(hStage[2]);
      patch.total = Number(hStage[2]);
    }
    const detail = (hStage[3] || "").trim().slice(0, 160);
    if (detail) patch.detail = detail;
    return { kind: "harness", harness: patch };
  }
  const hStart = line.match(/^\[L1\]\s+coding\s+harness\s+start\s+n=(\d+)/i);
  if (hStart) {
    return {
      kind: "harness",
      harness: {
        phase: "running",
        n: Number(hStart[1]),
        total: Number(hStart[1]),
        done: 0,
        pct: 0,
        stage: "start",
        resolved: 0,
        unresolved: 0,
        error: 0,
      },
    };
  }
  if (/^\[L1\]\s+coding\s+harness\s+resolve/i.test(line)) {
    return {
      kind: "harness",
      harness: { phase: "running", stage: "resolve" },
    };
  }
  const hFail = line.match(
    /^\[L1\]\s+coding\s+harness\s+done\s+status=failed(?:\s+error=(.*))?/i,
  );
  if (hFail) {
    return {
      kind: "harness",
      harness: {
        phase: "failed",
        detail: (hFail[1] || "").trim().slice(0, 160) || undefined,
      },
    };
  }
  const hDone = line.match(
    /^\[L1\]\s+coding\s+harness\s+done\s+resolved=(\d+)\/(\d+)\s+unresolved=(\d+)\s+error=(\d+)(?:\s+rate=(\S+))?/i,
  );
  if (hDone) {
    return {
      kind: "harness",
      harness: {
        phase: "done",
        resolved: Number(hDone[1]),
        total: Number(hDone[2]),
        n: Number(hDone[2]),
        done: Number(hDone[2]),
        pct: 100,
        unresolved: Number(hDone[3]),
        error: Number(hDone[4]),
        rate: hDone[5] || null,
        stage: "done",
      },
    };
  }
  const hCase = line.match(
    /^\[L1\]\s+coding\s+harness\s+case\s+(\S+)\s+outcome=(resolved|unresolved|error)/i,
  );
  if (hCase) {
    return {
      kind: "case",
      case: {
        iid: hCase[1],
        status: "pass",
        harness: hCase[2] as CodingCaseLive["harness"],
      },
    };
  }
  return null;
}

export function applyCodingLiveEvent(
  byIid: Record<string, CodingCaseLive>,
  harness: CodingHarnessLive,
  ev: CodingLiveEvent,
): { byIid: Record<string, CodingCaseLive>; harness: CodingHarnessLive } {
  if (ev.kind === "plan") {
    return {
      byIid,
      harness: { ...harness, n: ev.n, total: harness.total ?? ev.n },
    };
  }
  if (ev.kind === "harness") {
    const merged: CodingHarnessLive = { ...harness, phase: ev.harness.phase };
    for (const [k, v] of Object.entries(ev.harness) as [
      keyof CodingHarnessLive,
      CodingHarnessLive[keyof CodingHarnessLive],
    ][]) {
      if (v !== undefined) {
        (merged as Record<string, unknown>)[k] = v;
      }
    }
    return { byIid, harness: merged };
  }
  const prev = byIid[ev.case.iid];
  const incoming = ev.case.status;
  let status = incoming;
  if (
    prev &&
    (prev.status === "pass" || prev.status === "fail") &&
    (incoming === "running" || incoming === "pending")
  ) {
    status = prev.status;
  }
  const next: CodingCaseLive = {
    iid: ev.case.iid,
    status,
    bucket: ev.case.bucket ?? prev?.bucket,
    patchSource: ev.case.patchSource ?? prev?.patchSource,
    harness: ev.case.harness ?? prev?.harness,
    steps: ev.case.steps ?? prev?.steps ?? null,
    elapsedSec: ev.case.elapsedSec ?? prev?.elapsedSec ?? null,
    startedAtMs: preferEarlierStartedAtMs(
      ev.case.startedAtMs,
      prev?.startedAtMs,
    ),
  };
  // Harness-only case lines keep prior infer status when present.
  if (ev.case.harness && prev && !ev.case.bucket && !ev.case.patchSource) {
    next.status = prev.status;
  }
  return {
    byIid: { ...byIid, [ev.case.iid]: next },
    harness,
  };
}

export function mergeCodingCase(
  prev: CodingCaseLive | undefined,
  next: CodingCaseLive,
): CodingCaseLive {
  if (!prev) return next;
  let status = next.status;
  if (
    (prev.status === "pass" || prev.status === "fail") &&
    (next.status === "running" || next.status === "pending")
  ) {
    status = prev.status;
  }
  const patchSource =
    next.patchSource && next.patchSource !== "none"
      ? next.patchSource
      : prev.patchSource;
  return {
    ...prev,
    ...next,
    status,
    patchSource,
    bucket: next.bucket ?? prev.bucket,
    harness: next.harness ?? prev.harness,
    steps: next.steps ?? prev.steps ?? null,
    elapsedSec: next.elapsedSec ?? prev.elapsedSec ?? null,
    startedAtMs: preferEarlierStartedAtMs(next.startedAtMs, prev.startedAtMs),
  };
}

export function mergeCodingLiveState(
  prev: {
    byIid: Record<string, CodingCaseLive>;
    harness: CodingHarnessLive;
  },
  nextByIid: Record<string, CodingCaseLive>,
  nextHarness: CodingHarnessLive,
): { byIid: Record<string, CodingCaseLive>; harness: CodingHarnessLive } {
  const byIid = { ...prev.byIid };
  for (const row of Object.values(nextByIid)) {
    byIid[row.iid] = mergeCodingCase(byIid[row.iid], row);
  }
  const harness = {
    ...(nextHarness.phase !== "idle" ? nextHarness : prev.harness),
  };
  if (
    (harness.n == null || harness.n <= 0) &&
    prev.harness.n != null &&
    prev.harness.n > 0
  ) {
    harness.n = prev.harness.n;
    harness.total = harness.total ?? prev.harness.total ?? prev.harness.n;
  }
  return { byIid, harness };
}

export function formatCodingCaseRows(
  byIid: Record<string, CodingCaseLive>,
): CodingCaseLive[] {
  const order = ["running", "pending", "fail", "pass"];
  return Object.values(byIid).sort((a, b) => {
    const ia = order.indexOf(a.status);
    const ib = order.indexOf(b.status);
    return (
      (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.iid.localeCompare(b.iid)
    );
  });
}

/** Compact per-case steps + wall time for the live strip. */
export function formatCodingCaseStats(
  row: CodingCaseLive,
  nowMs: number,
  formatDuration: (seconds: number | null | undefined) => string,
): string {
  const bits: string[] = [];
  if (row.steps != null && Number.isFinite(row.steps)) {
    bits.push(`${row.steps}步`);
  }
  let sec: number | null = null;
  if (row.elapsedSec != null && Number.isFinite(row.elapsedSec)) {
    sec = row.elapsedSec;
  } else if (
    (row.status === "running" || row.status === "pending") &&
    row.startedAtMs != null &&
    Number.isFinite(row.startedAtMs)
  ) {
    sec = Math.max(0, (nowMs - row.startedAtMs) / 1000);
  }
  if (sec != null) {
    bits.push(formatDuration(sec));
  }
  return bits.join(" · ");
}

export function sumCodingCaseStats(
  rows: CodingCaseLive[],
  nowMs: number,
): { stepsTotal: number; elapsedTotalSec: number; stepsKnown: number; elapsedKnown: number } {
  let stepsTotal = 0;
  let elapsedTotalSec = 0;
  let stepsKnown = 0;
  let elapsedKnown = 0;
  for (const row of rows) {
    if (row.steps != null && Number.isFinite(row.steps)) {
      stepsTotal += row.steps;
      stepsKnown += 1;
    }
    if (row.elapsedSec != null && Number.isFinite(row.elapsedSec)) {
      elapsedTotalSec += row.elapsedSec;
      elapsedKnown += 1;
    } else if (
      (row.status === "running" || row.status === "pending") &&
      row.startedAtMs != null &&
      Number.isFinite(row.startedAtMs)
    ) {
      elapsedTotalSec += Math.max(0, (nowMs - row.startedAtMs) / 1000);
      elapsedKnown += 1;
    }
  }
  return { stepsTotal, elapsedTotalSec, stepsKnown, elapsedKnown };
}

export const EMPTY_CODING_HARNESS: CodingHarnessLive = {
  phase: "idle",
  n: null,
  done: null,
  pct: null,
  stage: null,
  resolved: null,
  total: null,
  unresolved: null,
  error: null,
  rate: null,
};

/** Parse `[L1] workspace_index …` progress lines into a per-instance card. */
export function parseAstIndexLine(line: string): AstIndexLive | null {
  const enqueue = line.match(
    /^\[L1\]\s+workspace_index\s+enqueue\s+\(ephemeral\)\s+(\S+)/i,
  );
  if (enqueue) {
    return {
      iid: enqueue[1],
      status: "queued",
      filesDone: null,
      filesTotal: null,
      ephemeral: true,
    };
  }
  const m = line.match(
    /^\[L1\]\s+workspace_index\s+(\S+)\s+status=(\S+)(?:\s+files=(\d+|\?)\/(\d+|\?))?/i,
  );
  if (!m) return null;
  const doneRaw = m[3];
  const totalRaw = m[4];
  return {
    iid: m[1],
    status: m[2],
    filesDone:
      doneRaw && doneRaw !== "?" && Number.isFinite(Number(doneRaw))
        ? Number(doneRaw)
        : null,
    filesTotal:
      totalRaw && totalRaw !== "?" && Number.isFinite(Number(totalRaw))
        ? Number(totalRaw)
        : null,
    ephemeral: /\bephemeral=1\b/i.test(line),
  };
}

export function mergeAstIndexEntry(
  prev: AstIndexLive | undefined,
  next: AstIndexLive,
): AstIndexLive {
  if (!prev) return next;
  if (
    AST_INDEX_WEAK_STATUSES.has(next.status) &&
    !AST_INDEX_WEAK_STATUSES.has(prev.status)
  ) {
    return {
      ...prev,
      filesDone: prev.filesDone ?? next.filesDone,
      filesTotal: prev.filesTotal ?? next.filesTotal,
      ephemeral: prev.ephemeral || next.ephemeral,
    };
  }
  return {
    ...next,
    filesDone: next.filesDone ?? prev.filesDone,
    filesTotal: next.filesTotal ?? prev.filesTotal,
    ephemeral: next.ephemeral || prev.ephemeral,
  };
}

function astPlaceholderForCoding(caseRow: CodingCaseLive): AstIndexLive {
  const finished = caseRow.status === "pass" || caseRow.status === "fail";
  return {
    iid: caseRow.iid,
    status: finished ? "purged" : "queued",
    filesDone: null,
    filesTotal: null,
    ephemeral: true,
  };
}

/**
 * Align AST cards with coding instances. Log truncation / ephemeral purge
 * must not drop finished cases from the live strip.
 */
export function formatAstIndexRows(
  byIid: Record<string, AstIndexLive>,
  codingByIid?: Record<string, CodingCaseLive>,
): AstIndexLive[] {
  const merged: Record<string, AstIndexLive> = { ...byIid };
  for (const row of Object.values(codingByIid || {})) {
    const existing = merged[row.iid];
    if (!existing) {
      merged[row.iid] = astPlaceholderForCoding(row);
      continue;
    }
    const finished = row.status === "pass" || row.status === "fail";
    if (finished && AST_INDEX_WEAK_STATUSES.has(existing.status)) {
      merged[row.iid] = {
        ...existing,
        status: existing.filesTotal ? "ready" : "purged",
      };
    }
  }
  const order = [
    "building",
    "cold",
    "queued",
    "stale",
    "ready",
    "purged",
    "error",
  ];
  return Object.values(merged).sort((a, b) => {
    const ia = order.indexOf(a.status);
    const ib = order.indexOf(b.status);
    return (
      (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.iid.localeCompare(b.iid)
    );
  });
}
