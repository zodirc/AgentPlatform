import type { DetailProgress, OfficialRun } from "./types";
import { suitesFromRun, suitesToTargets } from "./presets";

export { parseCodingLiveLine } from "./codingLive";

export function targetsFromRun(r: OfficialRun): string[] {
  return suitesToTargets(suitesFromRun(r));
}
export const SUITE_DETAIL_LABEL: Record<string, string> = {
  context: "上下文",
  coding: "编码",
  retrieval: "检索",
  retrieval_zh: "中文检索",
};

export const SUITE_UNIT: Record<string, string> = {
  retrieval: "查询",
  retrieval_zh: "查询",
  context: "题",
  coding: "题",
};

/** Strip suite prefix from case tokens for the detail strip. */
export function shortCaseToken(token: string): string {
  return token.replace(/^(swe|beir|cmteb|longbench)\./i, "");
}
export function aggregateParts(
  parts: Record<string, { done: number; total: number }> | undefined,
): { done: number; total: number } | null {
  if (!parts) return null;
  const vals = Object.values(parts);
  if (!vals.length) return null;
  return {
    done: vals.reduce((a, p) => a + (Number.isFinite(p.done) ? p.done : 0), 0),
    total: vals.reduce(
      (a, p) => a + (Number.isFinite(p.total) ? p.total : 0),
      0,
    ),
  };
}

/** Prefer sibling BEIR dataset qrels count when the next corpus is still indexing. */
export function inferQueryTotal(
  parts: Record<string, { done: number; total: number }>,
  excludeKey?: string,
): number | null {
  let max = 0;
  for (const [k, v] of Object.entries(parts)) {
    if (excludeKey && k === excludeKey) continue;
    if (Number.isFinite(v.total) && v.total > max) max = v.total;
  }
  return max > 0 ? max : null;
}

export function mergeDetailProgress(
  prev: DetailProgress | undefined,
  next: DetailProgress,
): DetailProgress {
  const parts: Record<string, { done: number; total: number }> = {
    ...(prev?.parts || {}),
  };
  if (next.parts) {
    for (const [k, v] of Object.entries(next.parts)) {
      parts[k] = { ...parts[k], ...v };
    }
  }
  if (
    next.partKey &&
    next.done != null &&
    Number.isFinite(next.done) &&
    next.total != null &&
    Number.isFinite(next.total)
  ) {
    parts[next.partKey] = { done: next.done, total: next.total };
  }
  // Index/materialize for a dataset that has no queries plan yet: reserve a
  // bucket (same qrels/集 as siblings) so 40/40 does not look finished.
  if (next.pipelineGap && next.partKey && !parts[next.partKey]) {
    const inferred = inferQueryTotal(parts, next.partKey);
    if (inferred != null) {
      parts[next.partKey] = { done: 0, total: inferred };
    }
  }

  const summed = aggregateParts(Object.keys(parts).length ? parts : undefined);
  const pct =
    next.pct != null && Number.isFinite(next.pct)
      ? next.pct
      : (prev?.pct ?? null);
  const done = summed
    ? summed.done
    : next.done != null && Number.isFinite(next.done)
      ? next.done
      : (prev?.done ?? null);
  const total = summed
    ? summed.total
    : next.total != null && Number.isFinite(next.total)
      ? next.total
      : (prev?.total ?? null);
  const unit = next.unit || prev?.unit || undefined;
  const outPct =
    summed && summed.total > 0
      ? Math.max(
          0,
          Math.min(100, Math.round((summed.done / summed.total) * 100)),
        )
      : pct;
  const pipelineGap =
    next.pipelineGap !== undefined
      ? next.pipelineGap
      : Boolean(prev?.pipelineGap);
  return {
    ...next,
    pct: outPct,
    done,
    total,
    unit,
    parts: Object.keys(parts).length ? parts : undefined,
    partKey: next.partKey || prev?.partKey,
    pipelineGap,
  };
}

export function formatSuiteDetails(details: Record<string, DetailProgress>): {
  label: string;
  pct: number | null;
  kind: DetailProgress["kind"];
  done: number | null;
  total: number | null;
  remain: number | null;
  unit: string | null;
  suiteKey: string | null;
} {
  const keys = Object.keys(details);
  if (!keys.length) {
    return {
      label: "尚未开始",
      pct: null,
      kind: "idle",
      done: null,
      total: null,
      remain: null,
      unit: null,
      suiteKey: null,
    };
  }
  const order = ["retrieval", "context", "coding"];
  const sorted = [
    ...order.filter((k) => k in details),
    ...keys.filter((k) => !order.includes(k) && k !== "_").sort(),
  ];
  const kind = sorted.some((k) => details[k].kind === "eval")
    ? "eval"
    : sorted.some((k) => details[k].kind === "pull") ||
        details._?.kind === "pull"
      ? "pull"
      : "idle";

  // Active suite = last unfinished among known suite keys; else latest with totals.
  let focus: DetailProgress | null = null;
  let focusKey: string | null = null;
  for (const k of order) {
    const d = details[k];
    if (!d) continue;
    if (d.total != null && Number.isFinite(d.total) && d.total > 0) {
      focus = d;
      focusKey = k;
      const unfinished =
        d.done == null || d.done < d.total || d.pipelineGap === true;
      if (unfinished) break;
    } else if (d.pipelineGap === true) {
      // Indexing before any queries plan — still the active suite.
      focus = d;
      focusKey = k;
      break;
    }
  }
  if (!focus) {
    for (const k of [...sorted].reverse()) {
      const d = details[k];
      if (d.total != null && Number.isFinite(d.total) && d.total > 0) {
        focus = d;
        focusKey = k === "_" ? null : k;
        break;
      }
    }
  }
  if (!focus && details._) {
    focus = details._;
    focusKey = null;
  }

  const done = focus?.done ?? null;
  const total = focus?.total ?? null;
  let remain = done != null && total != null ? Math.max(0, total - done) : null;
  // Between BEIR datasets, query counters can look "complete" while the next
  // corpus is still embedding — never claim "剩 0" in that gap.
  if (focus?.pipelineGap && remain === 0) {
    remain = null;
  }
  const unit = focus?.unit || (focusKey ? SUITE_UNIT[focusKey] : null) || null;
  const pct =
    done != null && total != null && total > 0
      ? Math.max(0, Math.min(100, Math.round((done / total) * 100)))
      : (focus?.pct ?? null);

  // Detail strip: only the active suite (finished suites cluttered the line and
  // made coding look stuck on an old instance / pull cache hint).
  const label = (() => {
    if (focus) {
      const name = focusKey ? SUITE_DETAIL_LABEL[focusKey] || focusKey : null;
      const lab = (focus.label || "").replace(/^L1\s+/, "");
      // 「已完成 a/b」so 1/5 is not read as "item 1 of 5 / current case".
      const bucket =
        done != null && total != null
          ? done < total
            ? ` · 已完成 ${done}/${total}`
            : ` · ${done}/${total}`
          : "";
      const withBucket =
        bucket && !lab.includes(`${done}/${total}`) ? `${lab}${bucket}` : lab;
      return name ? `${name}: ${withBucket}` : withBucket;
    }
    return sorted
      .map((k) => {
        const d = details[k];
        const name = SUITE_DETAIL_LABEL[k] || k;
        return `${name}: ${d.label}`;
      })
      .join(" · ");
  })();

  return { label, pct, kind, done, total, remain, unit, suiteKey: focusKey };
}

export function suiteFromL1Token(token: string): string | null {
  const t = token.trim().toLowerCase();
  if (!t) return null;
  if (t.startsWith("swe.") || t === "coding" || t.startsWith("coding.")) {
    return "coding";
  }
  if (
    t.startsWith("longbench.") ||
    t === "context" ||
    t.startsWith("context.")
  ) {
    return "context";
  }
  if (
    t.startsWith("beir.") ||
    t === "retrieval" ||
    t.startsWith("retrieval.")
  ) {
    return "retrieval";
  }
  return null;
}

export function parseProgressLine(line: string): DetailProgress | null {
  // L1 agent-path live lines (official_agent_path)
  const l1SuiteStart = line.match(/^\[L1\]\s+suite start\s+(\S+)/i);
  if (l1SuiteStart) {
    const raw = l1SuiteStart[1].toLowerCase();
    const suite =
      raw === "coding_infer" || raw === "coding"
        ? "coding"
        : raw === "context"
          ? "context"
          : raw === "retrieval"
            ? "retrieval"
            : null;
    if (suite) {
      return {
        kind: "eval",
        suite,
        label: `L1 开始 · ${SUITE_DETAIL_LABEL[suite]}`,
        pct: null,
        unit: SUITE_UNIT[suite],
      };
    }
  }
  const l1Coding = line.match(/^\[L1\]\s+coding\s+(\d+)\s*\/\s*(\d+)\s+(\S+)/i);
  if (l1Coding) {
    const cur = Number(l1Coding[1]);
    const total = Number(l1Coding[2]);
    const iid = l1Coding[3];
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite: "coding",
      label: `已完成 ${cur}/${total || "?"} · ${shortCaseToken(iid)}`,
      pct,
      done: Number.isFinite(cur) ? cur : null,
      total: Number.isFinite(total) ? total : null,
      unit: "题",
    };
  }
  const l1CtxPlan = line.match(
    /^\[L1\]\s+context plan\s+n=(\d+)(?:\s+parallel=(\d+))?/i,
  );
  if (l1CtxPlan) {
    const n = Number(l1CtxPlan[1]);
    const p = l1CtxPlan[2] ? ` · 并行${l1CtxPlan[2]}` : "";
    return {
      kind: "eval",
      suite: "context",
      label: `L1 上下文计划 ${n} 题${p}`,
      pct: 0,
      done: 0,
      total: Number.isFinite(n) ? n : null,
      unit: "题",
    };
  }
  const l1CodePlan = line.match(
    /^\[L1\]\s+coding plan\s+n=(\d+)\s+tier=(\S+)(?:\s+parallel=(\d+))?/i,
  );
  if (l1CodePlan) {
    const n = Number(l1CodePlan[1]);
    return {
      kind: "eval",
      suite: "coding",
      label: `L1 编码计划 ${l1CodePlan[1]} · ${l1CodePlan[2]}${
        l1CodePlan[3] ? ` · 并行${l1CodePlan[3]}` : ""
      }`,
      pct: 0,
      done: 0,
      total: Number.isFinite(n) ? n : null,
      unit: "题",
    };
  }
  const l1RetPlan = line.match(
    /^\[L1\]\s+(\S+)\s+queries plan\s+n=(\d+)(?:\s+\(qrels-only[^)]*\))?(?:\s+parallel=(\d+))?/i,
  );
  if (l1RetPlan) {
    const n = Number(l1RetPlan[2]);
    const ds = l1RetPlan[1];
    return {
      kind: "eval",
      suite: "retrieval",
      label: `L1 检索 ${ds} · ${l1RetPlan[2]} qrels${
        l1RetPlan[3] ? ` · 并行${l1RetPlan[3]}` : ""
      }`,
      pct: 0,
      done: 0,
      total: Number.isFinite(n) ? n : null,
      unit: "查询",
      partKey: ds,
      parts: Number.isFinite(n) ? { [ds]: { done: 0, total: n } } : undefined,
      pipelineGap: false,
    };
  }
  const l1Ctx = line.match(/^\[L1\]\s+context\s+(\d+)\s*\/\s*(\d+)/i);
  if (l1Ctx) {
    const cur = Number(l1Ctx[1]);
    const total = Number(l1Ctx[2]);
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite: "context",
      label: `L1 上下文 ${cur}/${total || "?"}`,
      pct,
      done: Number.isFinite(cur) ? cur : null,
      total: Number.isFinite(total) ? total : null,
      unit: "题",
    };
  }
  const l1Q = line.match(/^\[L1\]\s+(\S+)\s+queries\s+(\d+)\s*\/\s*(\d+)/i);
  if (l1Q) {
    const ds = l1Q[1];
    const cur = Number(l1Q[2]);
    const total = Number(l1Q[3]);
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite: "retrieval",
      label: `L1 检索 ${ds} · 查询 ${cur}/${total || "?"}`,
      pct,
      done: Number.isFinite(cur) ? cur : null,
      total: Number.isFinite(total) ? total : null,
      unit: "查询",
      partKey: ds,
      parts:
        Number.isFinite(cur) && Number.isFinite(total)
          ? { [ds]: { done: cur, total } }
          : undefined,
      pipelineGap: false,
    };
  }
  const l1Pull = line.match(/^\[L1\]\s+pull\s+(.+)$/i);
  if (l1Pull) {
    const what = l1Pull[1].trim();
    const suite = /swe/i.test(what)
      ? "coding"
      : /longbench|context/i.test(what)
        ? "context"
        : "retrieval";
    return {
      kind: "pull",
      suite,
      label: `L1 拉取 · ${what}`,
      pct: null,
    };
  }
  const l1Mat = line.match(
    /^\[L1\]\s+materialize\s+(\S+):\s+(\d+)\s*\/\s*(\d+)/i,
  );
  if (l1Mat) {
    const cur = Number(l1Mat[2]);
    const total = Number(l1Mat[3]);
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    const doneMat = total > 0 && cur >= total;
    return {
      kind: "eval",
      suite: "retrieval",
      label: `L1 物化 ${l1Mat[1]} · ${cur}/${total || "?"}`,
      pct,
      partKey: l1Mat[1],
      unit: "查询",
      pipelineGap: !doneMat,
    };
  }
  const l1Sync = line.match(/^\[L1\]\s+sync\s+(\S+):\s+(.+)$/i);
  if (l1Sync) {
    const ds = l1Sync[1];
    const rest = l1Sync[2];
    if (/^done\b/i.test(rest)) {
      return {
        kind: "eval",
        suite: "retrieval",
        label: `L1 索引完成 · ${ds}`,
        pct: 100,
        partKey: ds,
        unit: "查询",
        // Still waiting for queries plan / turns.
        pipelineGap: true,
      };
    }
    const files = rest.match(/files=(\d+)\s*\/\s*(\d+)/i);
    const chunks = rest.match(/chunks=(\d+)\s*\/\s*(\d+)/i);
    const phase = rest.match(/phase=(\S+)/i)?.[1] || "building";
    const eta = rest.match(/eta=([\d.]+)s/i)?.[1];
    const rate = rest.match(/rate=([\d.]+)\/s/i)?.[1];
    let pct: number | null = null;
    if (chunks) {
      const c = Number(chunks[1]);
      const t = Number(chunks[2]);
      if (t > 0 && Number.isFinite(c)) {
        pct = Math.max(0, Math.min(100, Math.round((c / t) * 100)));
      }
    } else if (files) {
      const c = Number(files[1]);
      const t = Number(files[2]);
      if (t > 0 && Number.isFinite(c)) {
        pct = Math.max(0, Math.min(100, Math.round((c / t) * 100)));
      }
    }
    const bits = [`L1 索引 ${ds}`, phase];
    if (chunks) bits.push(`chunks ${chunks[1]}/${chunks[2]}`);
    else if (files) bits.push(`files ${files[1]}/${files[2]}`);
    if (rate) bits.push(`${rate}/s`);
    if (eta) bits.push(`ETA ${eta}s`);
    return {
      kind: "eval",
      suite: "retrieval",
      label: bits.join(" · "),
      pct,
      partKey: ds,
      unit: "查询",
      pipelineGap: true,
    };
  }
  if (/^\[L1\]\s+dataset\s+\S+:\s+materialize/i.test(line)) {
    const name = line.match(/^\[L1\]\s+dataset\s+(\S+):/i)?.[1] || "?";
    return {
      kind: "eval",
      suite: "retrieval",
      label: `L1 检索物化/索引 · ${name}`,
      pct: null,
      partKey: name,
      unit: "查询",
      pipelineGap: true,
    };
  }
  const l1TurnStart = line.match(/^\[L1\]\s+turn start\s+(\S+)/i);
  if (l1TurnStart) {
    const label = l1TurnStart[1];
    const suite = suiteFromL1Token(label);
    if (suite) {
      return {
        kind: "eval",
        suite,
        label: `进行中 · ${shortCaseToken(label)}`,
        pct: null,
      };
    }
  }
  const l1CheckoutFail = line.match(
    /^\[L1\]\s+checkout failed\s+(\S+):\s*(.+)$/i,
  );
  if (l1CheckoutFail) {
    return {
      kind: "eval",
      suite: "coding",
      label: `checkout 失败 · ${shortCaseToken(l1CheckoutFail[1])}（仅 problem.md）`,
      pct: null,
    };
  }
  const l1CheckoutOk = line.match(
    /^\[L1\]\s+checkout\s+(\S+)\s+mirror_hit=(\S+)/i,
  );
  if (l1CheckoutOk) {
    return {
      kind: "eval",
      suite: "coding",
      label: `checkout · ${shortCaseToken(l1CheckoutOk[1])} · mirror=${l1CheckoutOk[2]}`,
      pct: null,
    };
  }
  const l1TurnDone = line.match(
    /^\[L1\]\s+turn done\s+(\S+)\s+status=(\S+)\s+events=(\d+)\s+(\d+)s/i,
  );
  if (l1TurnDone) {
    const label = l1TurnDone[1];
    const suite = suiteFromL1Token(label);
    if (suite) {
      return {
        kind: "eval",
        suite,
        label: `Turn ${l1TurnDone[2]} · ${shortCaseToken(label)} · ${l1TurnDone[4]}s`,
        pct: null,
      };
    }
  }
  const l1Wait = line.match(
    /^\[L1\]\s+(?:…|\.\.\.)\s+waiting\s+(\S+)\s+(\d+)s\s+last=(\S+)/i,
  );
  if (l1Wait) {
    const label = l1Wait[1];
    const suite = suiteFromL1Token(label);
    if (suite) {
      return {
        kind: "eval",
        suite,
        label: `等待 · ${shortCaseToken(label)} · ${l1Wait[2]}s · last=${l1Wait[3]}`,
        pct: null,
      };
    }
  }
  // "[L1] · tool.started read_file · swe.xxx turn_id=..."
  const l1Step = line.match(
    /^\[L1\]\s+·\s+(\S+)(?:\s+(.+?))?\s+·\s+(\S+)\s+turn_id=/i,
  );
  if (l1Step) {
    const et = l1Step[1];
    const detail = (l1Step[2] || "").trim();
    const label = l1Step[3];
    const suite = suiteFromL1Token(label);
    if (suite) {
      const caseId = shortCaseToken(label);
      // Detail strip should answer "which case", not dump stream event names
      // (context.reported → 「上下文就绪」looked like the context suite).
      if (et.startsWith("tool.")) {
        const verb = et === "tool.started" ? "工具" : "工具完成";
        return {
          kind: "eval",
          suite,
          label: `${verb}${detail ? ` ${detail}` : ""} · ${caseId}`,
          pct: null,
        };
      }
      return {
        kind: "eval",
        suite,
        label: `进行中 · ${caseId}`,
        pct: null,
      };
    }
  }
  if (/^\[L1\]\s+coding infer done/i.test(line)) {
    return {
      kind: "eval",
      suite: "coding",
      label: "L1 编码套件结束",
      pct: 100,
    };
  }
  if (/^\[L1\]\s+context done/i.test(line)) {
    return {
      kind: "eval",
      suite: "context",
      label: "L1 上下文套件结束",
      pct: 100,
    };
  }
  if (/^\[L1\]\s+retrieval done/i.test(line)) {
    return {
      kind: "eval",
      suite: "retrieval",
      label: "L1 检索套件结束",
      pct: 100,
      pipelineGap: false,
    };
  }

  // Context / coding infer lines: "[context] infer — 72/120 hotpotqa arm=full"
  // Dash may be em/en/hyphen; keep tolerant for Ops log replay.
  const infer = line.match(
    /^\[(context|coding)\]\s+infer\s+\D*?(\d+)\s*\/\s*(\d+)\s+(.+)$/i,
  );
  if (infer) {
    const suite = infer[1].toLowerCase();
    const cur = Number(infer[2]);
    const total = Number(infer[3]);
    const rest = infer[4].trim();
    const pct =
      total > 0 && Number.isFinite(cur)
        ? Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
        : null;
    return {
      kind: "eval",
      suite,
      label: `推理 ${cur}/${total || "?"} · ${rest}`,
      pct,
    };
  }
  if (/^\[(context|coding)\]\s+run_finished/i.test(line)) {
    const suite = line.match(/^\[(context|coding)\]/i)?.[1]?.toLowerCase();
    const failed = /\bfailed\b/i.test(line);
    return {
      kind: "eval",
      suite,
      label: failed ? "套件结束（未达标）" : "套件结束",
      pct: 100,
    };
  }

  const m = line.match(/^\[progress\]\s+(pull|eval)\s+(.+)$/i);
  if (!m) return null;
  const kind = m[1].toLowerCase() as "pull" | "eval";
  const rest = m[2];
  const kv: Record<string, string> = {};
  for (const part of rest.split(/\s+/)) {
    const eq = part.indexOf("=");
    if (eq > 0) kv[part.slice(0, eq)] = part.slice(eq + 1);
  }
  if (kind === "pull" && rest.startsWith("plan")) {
    const fileHint = `${kv.file || ""} ${rest}`.toLowerCase();
    const suite = /longbench|multifield|hotpot|narrative/.test(fileHint)
      ? "context"
      : /swe|instance/.test(fileHint)
        ? "coding"
        : "retrieval";
    return {
      kind: "pull",
      suite,
      label: `拉取计划：共 ${kv.total || "?"} 集 · 已缓存 ${kv.cached || "0"} · 待下 ${kv.need || "?"} · 约 ${kv.approx_mib || "?"} MiB`,
      pct: kv.need === "0" ? 100 : 0,
    };
  }
  if (kind === "pull") {
    const pct = kv.pct != null ? Number(kv.pct) : null;
    const size = kv.size_mib ? ` · ${kv.size_mib} MiB` : "";
    const cached = kv.cached === "1" ? "（缓存跳过）" : "";
    const fileHint = `${kv.file || ""}`.toLowerCase();
    const suite = /longbench|multifield|hotpot|narrative|data\.zip/.test(
      fileHint,
    )
      ? "context"
      : /swe|instance/.test(fileHint)
        ? "coding"
        : "retrieval";
    return {
      kind: "pull",
      suite,
      label: `拉取 ${kv.dataset || "?"} · ${kv.file || ""}${size}${cached}`,
      pct: Number.isFinite(pct as number) ? (pct as number) : null,
    };
  }
  if (rest.startsWith("plan")) {
    return {
      kind: "eval",
      suite: "retrieval",
      label: `评测计划：${kv.datasets || "?"} 集 × ${kv.arms || "?"} 臂 = ${kv.units || "?"} 块`,
      pct:
        kv.pct != null && Number.isFinite(Number(kv.pct)) ? Number(kv.pct) : 0,
    };
  }
  const pct = kv.pct != null ? Number(kv.pct) : null;
  const q = kv.queries ? ` · 查询 ${kv.queries}` : "";
  const arm = kv.arm ? `/${kv.arm}` : "";
  const unit = kv.unit ? `块 ${kv.unit}` : `集 ${kv.dataset || "?"}`;
  return {
    kind: "eval",
    suite: "retrieval",
    label: `评测 ${unit} · ${kv.name || ""}${arm} · ${kv.stage || ""}${q}`,
    pct: Number.isFinite(pct as number) ? (pct as number) : null,
  };
}
