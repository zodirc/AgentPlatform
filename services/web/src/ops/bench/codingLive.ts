import type {
  AstIndexLive,
  CodingCaseLive,
  CodingHarnessLive,
  CodingLiveEvent,
} from "./types";

export const HARNESS_STAGE_LABEL: Record<string, string> = {
  load_dataset: "加载数据集",
  images_ready: "镜像就绪",
  evaluating: "按题评测中",
  instances_done: "实例跑完",
};

/** Parse `[L1] coding …` / harness lines into the coding progress card. */
export function parseCodingLiveLine(line: string): CodingLiveEvent | null {
  const plan = line.match(/^\[L1\]\s+coding\s+plan\s+n=(\d+)\b/i);
  if (plan) {
    return { kind: "plan", n: Number(plan[1]) };
  }
  const start = line.match(/^\[L1\]\s+coding\s+case\s+start\s+(\S+)/i);
  if (start) {
    return {
      kind: "case",
      case: { iid: start[1], status: "running" },
    };
  }
  const done = line.match(
    /^\[L1\]\s+coding\s+(\d+)\s*\/\s*(\d+)\s+(\S+)(?:\s+status=(\S+))?(?:\s+bucket=(\S+))?(?:\s+patch_source=(\S+))?/i,
  );
  if (done) {
    const statusRaw = (done[4] || "").toLowerCase();
    const status: CodingCaseLive["status"] =
      statusRaw === "pass" ? "pass" : statusRaw === "fail" ? "fail" : "pass";
    return {
      kind: "case",
      case: {
        iid: done[3],
        status,
        bucket: done[5] || undefined,
        patchSource: done[6] || undefined,
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
  const next: CodingCaseLive = {
    iid: ev.case.iid,
    status: ev.case.status,
    bucket: ev.case.bucket ?? prev?.bucket,
    patchSource: ev.case.patchSource ?? prev?.patchSource,
    harness: ev.case.harness ?? prev?.harness,
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

export function formatAstIndexRows(
  byIid: Record<string, AstIndexLive>,
): AstIndexLive[] {
  const order = ["building", "cold", "queued", "stale", "ready", "error"];
  return Object.values(byIid).sort((a, b) => {
    const ia = order.indexOf(a.status);
    const ib = order.indexOf(b.status);
    return (
      (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.iid.localeCompare(b.iid)
    );
  });
}
