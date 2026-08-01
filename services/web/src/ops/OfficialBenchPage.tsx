import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  OpsShell,
  opsOfficialPath,
  opsRunPath,
  secretFromOpsPath,
  statusClass,
} from "./OpsShell";

type Criterion = {
  id: string;
  official: string;
  title: string;
  metrics: string;
  pass_rule: string;
  notes: string;
};

type TargetMeta = {
  id: string;
  label: string;
  group?: string;
  description: string;
  needs_model?: boolean;
};

type Preset = {
  id: string;
  label: string;
  targets: string[];
  context_dry: boolean;
  coding_skip_api: boolean;
  hint: string;
};

type Caps = Record<string, boolean>;

type OfficialRun = {
  id: string;
  status: string;
  suite?: string;
  official_suite?: string;
  title?: string;
  created_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  progress_done?: number;
  progress_total?: number;
  current_phase?: string;
  phase_hint?: string;
  targets?: string[];
  context_dry?: boolean;
  coding_skip_api?: boolean;
  cancel_requested?: boolean;
  report_html_available?: boolean;
  child_reports?: Array<{ case_id?: string; bench_run_id?: string; report_html?: string }>;
  summary?: {
    total?: number;
    pass?: number;
    fail?: number;
    skipped?: number;
    pending?: number;
    progress_done?: number;
    progress_total?: number;
    metrics?: Record<string, number>;
  };
  metrics?: Record<string, number>;
  model_meta?: {
    title?: string;
    official_suite?: string;
    context_dry?: boolean;
    coding_skip_api?: boolean;
    report_html_available?: boolean;
    child_reports?: Array<{ case_id?: string; bench_run_id?: string; report_html?: string }>;
  };
  source?: string;
  cases?: Array<{
    case_id: string;
    status: string;
    metrics?: Record<string, number>;
    error?: string | null;
  }>;
  logs?: Array<{
    at?: string;
    kind?: string;
    message?: string;
    case_id?: string;
    status?: string;
    phase?: string;
    progress_done?: number;
    progress_total?: number;
  }>;
};

const KNOWN_TARGETS = ["pull", "retrieval", "context", "coding_pull", "coding_infer"] as const;

function isActiveStatus(status?: string): boolean {
  return status === "queued" || status === "running" || status === "cancelling";
}

function targetsFromRun(r: OfficialRun): string[] {
  if (Array.isArray(r.targets) && r.targets.length > 0) {
    return r.targets.filter((t) => (KNOWN_TARGETS as readonly string[]).includes(t));
  }
  const suite = r.official_suite || r.model_meta?.official_suite || "";
  return suite
    .split("+")
    .map((s) => s.trim())
    .filter((t) => (KNOWN_TARGETS as readonly string[]).includes(t));
}

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Human duration: 12s · 3m 05s · 1h 02m */
function formatDuration(seconds: number | null | undefined): string {
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

function elapsedSeconds(
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

/** ETA from wall clock + overall fraction in [0,1]. Null when too early / stuck. */
function estimateEtaSeconds(elapsedSec: number, frac: number): number | null {
  if (!(elapsedSec >= 3) || !(frac >= 0.03) || frac >= 0.995) return null;
  const total = elapsedSec / frac;
  const remain = total - elapsedSec;
  if (!Number.isFinite(remain) || remain < 0) return null;
  // Cap absurd ETAs (e.g. progress stuck at 3% for a long time)
  if (remain > elapsedSec * 40) return null;
  return remain;
}

function shortId(id: string): string {
  return id.slice(0, 8);
}

function cleanPhase(raw: string): string {
  return raw.replace(/^\[phase\]\s*/i, "").trim();
}

type DetailProgress = {
  kind: "pull" | "eval" | "idle";
  label: string;
  pct: number | null;
};

function parseProgressLine(line: string): DetailProgress | null {
  const m = line.match(
    /^\[progress\]\s+(pull|eval)\s+(.+)$/i,
  );
  if (!m) return null;
  const kind = m[1].toLowerCase() as "pull" | "eval";
  const rest = m[2];
  const kv: Record<string, string> = {};
  for (const part of rest.split(/\s+/)) {
    const eq = part.indexOf("=");
    if (eq > 0) kv[part.slice(0, eq)] = part.slice(eq + 1);
  }
  if (kind === "pull" && rest.startsWith("plan")) {
    return {
      kind: "pull",
      label: `拉取计划：共 ${kv.total || "?"} 集 · 已缓存 ${kv.cached || "0"} · 待下 ${kv.need || "?"} · 约 ${kv.approx_mib || "?"} MiB`,
      pct: kv.need === "0" ? 100 : 0,
    };
  }
  if (kind === "pull") {
    const pct = kv.pct != null ? Number(kv.pct) : null;
    const size = kv.size_mib ? ` · ${kv.size_mib} MiB` : "";
    const cached = kv.cached === "1" ? "（缓存跳过）" : "";
    return {
      kind: "pull",
      label: `拉取 ${kv.dataset || "?"} · ${kv.file || ""}${size}${cached}`,
      pct: Number.isFinite(pct as number) ? (pct as number) : null,
    };
  }
  if (rest.startsWith("plan")) {
    return {
      kind: "eval",
      label: `评测计划：${kv.datasets || "?"} 集 × ${kv.arms || "?"} 臂 = ${kv.units || "?"} 块`,
      pct: kv.pct != null && Number.isFinite(Number(kv.pct)) ? Number(kv.pct) : 0,
    };
  }
  const pct = kv.pct != null ? Number(kv.pct) : null;
  const q = kv.queries ? ` · 查询 ${kv.queries}` : "";
  const arm = kv.arm ? `/${kv.arm}` : "";
  const unit = kv.unit ? `块 ${kv.unit}` : `集 ${kv.dataset || "?"}`;
  return {
    kind: "eval",
    label: `评测 ${unit} · ${kv.name || ""}${arm} · ${kv.stage || ""}${q}`,
    pct: Number.isFinite(pct as number) ? (pct as number) : null,
  };
}

function runMetrics(r: OfficialRun | null | undefined): Record<string, number> {
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
  return out;
}

function median(sorted: number[]): number {
  if (!sorted.length) return Number.NaN;
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

type MetricAgg = {
  key: string;
  n: number;
  min: number;
  median: number;
  mean: number;
  max: number;
  latest: number;
};

function aggregateMetrics(runs: OfficialRun[]): MetricAgg[] {
  const byKey: Record<string, number[]> = {};
  const latestByKey: Record<string, number> = {};
  for (const r of runs) {
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

function MetricBars({ metrics }: { metrics: Record<string, number> }) {
  const entries = Object.entries(metrics);
  if (!entries.length) {
    return <p className="text-sm text-muted-foreground">本次尚无数值指标（流水线/dry 常见）。</p>;
  }
  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => {
        const width = Math.max(0, Math.min(100, v > 1 ? v : v * 100));
        return (
          <div key={k}>
            <div className="mb-0.5 flex justify-between gap-2 text-xs">
              <span className="truncate font-mono text-muted-foreground">{k}</span>
              <strong className="shrink-0 tabular-nums">{v.toFixed(4)}</strong>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-foreground/75" style={{ width: `${width}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

class EventSourcePolyfill {
  private controller = new AbortController();
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string, secret: string) {
    void this.start(url, secret);
  }

  private async start(url: string, secret: string) {
    try {
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${secret}`, Accept: "text/event-stream" },
        signal: this.controller.signal,
      });
      if (!resp.ok || !resp.body) {
        this.onerror?.();
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data:"));
          if (line) this.onmessage?.({ data: line.slice(5).trim() });
        }
      }
    } catch {
      if (!this.controller.signal.aborted) this.onerror?.();
    }
  }

  close() {
    this.controller.abort();
  }
}

export function OfficialBenchPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const secret = secretFromOpsPath(pathname);
  const selectedId = pathname.match(/\/official\/([^/]+)\/?$/)?.[1] || "";

  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [targetsMeta, setTargetsMeta] = useState<TargetMeta[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [caps, setCaps] = useState<Caps>({});
  const [selectedTargets, setSelectedTargets] = useState<Set<string>>(
    () => new Set(["retrieval", "context", "coding_pull", "coding_infer"]),
  );
  const [contextDry, setContextDry] = useState(true);
  const [codingSkipApi, setCodingSkipApi] = useState(true);
  const [showCriteria, setShowCriteria] = useState(false);
  const [suiteFilter, setSuiteFilter] = useState<string>("");
  const [runs, setRuns] = useState<OfficialRun[]>([]);
  const [detail, setDetail] = useState<OfficialRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [clearingHistory, setClearingHistory] = useState(false);
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [phaseHint, setPhaseHint] = useState(
    "全过程：① 拉取（已有则跳过）→ ② 评测 → ③ 回归对比上次指标",
  );
  const [detailProgress, setDetailProgress] = useState<DetailProgress>({
    kind: "idle",
    label: "尚未开始",
    pct: null,
  });
  const [tab, setTab] = useState<"overview" | "metrics" | "cases" | "log">("overview");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const logBoxRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSourcePolyfill | null>(null);
  const attachedRunIdRef = useRef<string | null>(null);

  const headers = useMemo(
    () => ({
      Authorization: `Bearer ${secret}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    }),
    [secret],
  );

  const applyRunSnapshot = useCallback((run: OfficialRun, opts?: { logs?: boolean }) => {
    setProgress({
      done: run.progress_done ?? run.summary?.progress_done ?? 0,
      total:
        run.progress_total ??
        run.summary?.progress_total ??
        targetsFromRun(run).length ??
        0,
    });
    if (run.phase_hint || run.current_phase) {
      setPhaseHint(cleanPhase(run.phase_hint || run.current_phase || ""));
    }
    if (opts?.logs === false) return;
    const lines: string[] = [];
    let lastDetail: DetailProgress | null = null;
    for (const item of run.logs || []) {
      const kind = String(item.kind || "");
      if (kind === "log" && item.message) {
        const msg = String(item.message);
        const parsed = parseProgressLine(msg);
        if (parsed) lastDetail = parsed;
        if (!msg.startsWith("[progress]")) lines.push(msg);
      } else if (kind === "phase" && item.message) {
        setPhaseHint(cleanPhase(String(item.message)));
      } else if (kind === "case_started" && item.case_id) {
        lines.push(`→ ${item.case_id}`);
      } else if (kind === "case_finished" && item.case_id) {
        lines.push(
          `${item.status === "pass" ? "✓" : item.status === "skipped" ? "○" : "✗"} ${item.case_id}`,
        );
      }
    }
    if (lastDetail) setDetailProgress(lastDetail);
    if (lines.length) setLiveLogs(lines.slice(-400));
  }, []);

  const targetEnabled = useCallback(
    (id: string) => {
      if (id === "retrieval") return caps.retrieval !== false && caps.script !== false;
      if (!caps.script) return false;
      // After image rebuild, datasets should be true; still gate honestly.
      if (caps.datasets === false && (id === "context" || id.startsWith("coding"))) {
        return false;
      }
      return true;
    },
    [caps],
  );

  const loadMeta = useCallback(async () => {
    const resp = await fetch("/api/v1/ops/official/meta", { headers });
    if (resp.status === 401 || resp.status === 403 || resp.status === 404) {
      setError(resp.status === 404 ? "Ops 未启用" : "无效密钥");
      return;
    }
    if (!resp.ok) {
      setError(`meta HTTP ${resp.status}`);
      return;
    }
    const body = (await resp.json()) as {
      criteria: Criterion[];
      targets: TargetMeta[];
      presets?: Preset[];
      capabilities: Caps;
      defaults?: { context_dry?: boolean; coding_skip_api?: boolean };
    };
    setCriteria(body.criteria || []);
    setTargetsMeta(body.targets || []);
    setPresets(body.presets || []);
    setCaps(body.capabilities || {});
    if (body.defaults?.context_dry !== undefined) setContextDry(body.defaults.context_dry);
    if (body.defaults?.coding_skip_api !== undefined) {
      setCodingSkipApi(body.defaults.coding_skip_api);
    }
    setError(null);
  }, [headers]);

  const loadList = useCallback(async (): Promise<OfficialRun[]> => {
    const resp = await fetch("/api/v1/ops/official/runs?limit=80", { headers });
    if (!resp.ok) return [];
    const body = (await resp.json()) as { runs: OfficialRun[] };
    const list = body.runs || [];
    setRuns(list);
    return list;
  }, [headers]);

  const loadDetail = useCallback(async (): Promise<OfficialRun | null> => {
    if (!selectedId) {
      setDetail(null);
      return null;
    }
    const resp = await fetch(`/api/v1/ops/official/runs/${selectedId}`, { headers });
    if (!resp.ok) return null;
    const body = (await resp.json()) as OfficialRun;
    setDetail(body);
    setProgress({
      done: body.progress_done ?? body.summary?.progress_done ?? 0,
      total:
        body.progress_total ??
        body.summary?.progress_total ??
        targetsFromRun(body).length ??
        0,
    });
    if (body.phase_hint || body.current_phase) {
      setPhaseHint(cleanPhase(body.phase_hint || body.current_phase || ""));
    }
    return body;
  }, [headers, selectedId]);

  const attachLiveStream = useCallback(
    (runId: string, opts?: { resetLogs?: boolean }) => {
      if (attachedRunIdRef.current === runId && esRef.current) {
        setBusy(true);
        return;
      }
      esRef.current?.close();
      attachedRunIdRef.current = runId;
      setBusy(true);
      setError(null);
      if (opts?.resetLogs) {
        setLiveLogs([]);
        setDetailProgress({ kind: "idle", label: "启动中…", pct: null });
      }
      const es = new EventSourcePolyfill(
        `/api/v1/ops/official/runs/${runId}/stream`,
        secret,
      );
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as Record<string, unknown>;
          const kind = String(data.kind || "");
          if (kind === "phase") {
            setPhaseHint(cleanPhase(String(data.message || data.phase || "")));
          } else if (kind === "log") {
            const msg = String(data.message || "");
            const parsed = parseProgressLine(msg);
            if (parsed) setDetailProgress(parsed);
            if (!msg.startsWith("[progress]")) {
              setLiveLogs((prev) => [...prev.slice(-400), msg]);
            }
          } else if (kind === "case_started") {
            setLiveLogs((prev) => [...prev, `→ ${data.case_id}`]);
            void loadList();
          } else if (kind === "case_finished") {
            setLiveLogs((prev) => [
              ...prev,
              `${data.status === "pass" ? "✓" : data.status === "skipped" ? "○" : "✗"} ${data.case_id}`,
            ]);
            setProgress({
              done: Number(data.progress_done || 0),
              total: Number(data.progress_total || 0),
            });
            void loadDetail();
            void loadList();
          } else if (kind === "run_started") {
            void loadList();
          }
          if (kind === "run_finished") {
            es.close();
            if (attachedRunIdRef.current === runId) attachedRunIdRef.current = null;
            setBusy(false);
            setDetailProgress({
              kind: "idle",
              label: "本轮结束",
              pct: 100,
            });
            void loadDetail();
            void loadList();
          }
        } catch {
          /* ignore */
        }
      };
      es.onerror = () => {
        es.close();
        if (attachedRunIdRef.current === runId) attachedRunIdRef.current = null;
        void loadDetail().finally(() => setBusy(false));
      };
    },
    [secret, loadDetail, loadList],
  );

  useEffect(() => {
    void loadMeta();
    void (async () => {
      const list = await loadList();
      const live = list.find(
        (r) => isActiveStatus(r.status) && (r.source === "live" || !r.finished_at),
      );
      if (!live) return;
      if (!selectedId) {
        navigate(opsOfficialPath(secret, live.id), { replace: true });
        return;
      }
      if (selectedId === live.id) {
        applyRunSnapshot(live, { logs: false });
        attachLiveStream(live.id, { resetLogs: true });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount reconnect
  }, [loadMeta, loadList, secret]);

  useEffect(() => {
    void (async () => {
      const body = await loadDetail();
      if (!body) return;
      if (isActiveStatus(body.status)) {
        applyRunSnapshot(body, { logs: false });
        // SSE replays in-memory history; only clear if this is a fresh attach.
        attachLiveStream(body.id, {
          resetLogs: attachedRunIdRef.current !== body.id,
        });
      } else {
        applyRunSnapshot(body);
        if (attachedRunIdRef.current === body.id) {
          esRef.current?.close();
          attachedRunIdRef.current = null;
          setBusy(false);
        }
      }
    })();
  }, [loadDetail, applyRunSnapshot, attachLiveStream]);

  useEffect(() => {
    const box = logBoxRef.current;
    if (!box) return;
    // Only scroll the log pane — never scrollIntoView (that moves the whole page).
    box.scrollTop = box.scrollHeight;
  }, [liveLogs]);

  useEffect(() => () => esRef.current?.close(), []);

  // Tick wall clock while a run is live so elapsed / ETA update.
  useEffect(() => {
    if (!busy) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [busy]);

  const applyPreset = (p: Preset) => {
    setSelectedTargets(new Set(p.targets));
    setContextDry(p.context_dry);
    setCodingSkipApi(p.coding_skip_api);
  };

  const toggleTarget = (id: string) => {
    if (!targetEnabled(id)) return;
    setSelectedTargets((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const startRun = async (opts?: {
    force?: boolean;
    targets?: string[];
    context_dry?: boolean;
    coding_skip_api?: boolean;
  }) => {
    const targets = (opts?.targets ?? Array.from(selectedTargets)).filter(targetEnabled);
    if (targets.length === 0) return;
    if (busy && !opts?.force) return;
    const dry = opts?.context_dry ?? contextDry;
    const skipApi = opts?.coding_skip_api ?? codingSkipApi;
    if (opts?.targets) {
      setSelectedTargets(new Set(targets));
      setContextDry(dry);
      setCodingSkipApi(skipApi);
    }
    setBusy(true);
    setLiveLogs([]);
    setError(null);
    setTab("log");
    try {
      const resp = await fetch("/api/v1/ops/official/runs", {
        method: "POST",
        headers,
        body: JSON.stringify({
          targets,
          context_dry: dry,
          coding_skip_api: skipApi,
          force: Boolean(opts?.force),
        }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        let msg = text || `HTTP ${resp.status}`;
        try {
          const j = JSON.parse(text) as {
            error?: { message?: string };
            detail?: string;
          };
          msg = j.error?.message || j.detail || msg;
        } catch {
          /* keep */
        }
        if (String(msg).includes("official_run_already_active") && !opts?.force) {
          setError(
            "已有 Bench 在跑（或上次未干净结束）。可点右上角「取消」，或点「强制重开」。",
          );
          setBusy(false);
          return;
        }
        throw new Error(msg);
      }
      const created = (await resp.json()) as OfficialRun;
      setProgress({ done: 0, total: created.progress_total || targets.length });
      navigate(opsOfficialPath(secret, created.id));
      attachLiveStream(created.id, { resetLogs: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const stopRun = async (runId?: string) => {
    const id = runId || selectedId;
    if (!id) return;
    setError(null);
    const resp = await fetch(`/api/v1/ops/official/runs/${id}/stop`, {
      method: "POST",
      headers,
    });
    if (!resp.ok) {
      const text = await resp.text();
      setError(text || `停止失败 HTTP ${resp.status}`);
    } else {
      // Live SSE may still deliver run_finished; DB-only cancel won't.
      const body = (await resp.json().catch(() => null)) as OfficialRun | null;
      if (body && !isActiveStatus(body.status)) {
        setBusy(false);
        setDetailProgress({ kind: "idle", label: "已取消", pct: null });
        setPhaseHint("已停止");
      }
    }
    await loadList();
    if (id === selectedId) await loadDetail();
  };

  const clearHistory = async () => {
    if (busy || clearingHistory) return;
    const n = runs.length;
    if (n === 0) return;
    const ok = window.confirm(
      `清空全部 Bench 历史（约 ${n} 条）？\n会删除数据库记录与报告目录，保留 BEIR/LongBench 数据缓存。`,
    );
    if (!ok) return;
    setClearingHistory(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/ops/official/runs", {
        method: "DELETE",
        headers,
      });
      if (!resp.ok) {
        const text = await resp.text();
        let msg = text || `HTTP ${resp.status}`;
        try {
          const j = JSON.parse(text) as { detail?: string; error?: { message?: string } };
          msg = j.error?.message || j.detail || msg;
        } catch {
          /* keep */
        }
        throw new Error(msg);
      }
      esRef.current?.close();
      attachedRunIdRef.current = null;
      setDetail(null);
      setLiveLogs([]);
      setRuns([]);
      setProgress({ done: 0, total: 0 });
      setDetailProgress({ kind: "idle", label: "尚未开始", pct: null });
      if (selectedId) {
        navigate(opsOfficialPath(secret), { replace: true });
      }
      await loadList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setClearingHistory(false);
    }
  };

  const rerunFrom = async (r: OfficialRun) => {
    const targets = targetsFromRun(r).filter(targetEnabled);
    if (targets.length === 0) {
      setError("该记录没有可重跑的目标（或当前镜像不支持）。");
      return;
    }
    await startRun({
      force: true,
      targets,
      context_dry: r.context_dry ?? r.model_meta?.context_dry ?? true,
      coding_skip_api: r.coding_skip_api ?? r.model_meta?.coding_skip_api ?? true,
    });
  };

  const suitePct =
    progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;
  const detailPct =
    detailProgress.pct != null && Number.isFinite(detailProgress.pct)
      ? Math.max(0, Math.min(100, Math.round(detailProgress.pct)))
      : null;
  // Prefer fine-grained bar while a suite is mid-flight (suite bar stuck at 0/N is misleading).
  const barPct =
    busy && detailPct != null
      ? Math.max(4, Math.round((suitePct * 0.35) + (detailPct * 0.65)))
      : suitePct || (busy ? 4 : 0);

  // Overall fraction for ETA: finished suites + current suite's detail %.
  const overallFrac = (() => {
    const total = progress.total || 0;
    if (total <= 0) return barPct / 100;
    const done = Math.min(progress.done, total);
    const within =
      detailPct != null && done < total ? Math.max(0, Math.min(1, detailPct / 100)) : 0;
    return Math.min(1, (done + within) / total);
  })();

  const runStartedAt = detail?.created_at || null;
  const runFinishedAt = busy ? null : detail?.finished_at || null;
  const elapsedSec = elapsedSeconds(runStartedAt, runFinishedAt, nowMs);
  const etaSec = busy
    ? estimateEtaSeconds(elapsedSec ?? 0, overallFrac)
    : null;
  const timingLabel = (() => {
    if (elapsedSec == null) return null;
    if (busy) {
      const etaPart =
        etaSec != null
          ? ` · 预计剩余 ${formatDuration(etaSec)}`
          : overallFrac < 0.03
            ? " · 预计剩余 —（进度太少）"
            : " · 预计剩余 —";
      return `已用 ${formatDuration(elapsedSec)}${etaPart}`;
    }
    if (runFinishedAt) return `用时 ${formatDuration(elapsedSec)}`;
    return `已用 ${formatDuration(elapsedSec)}`;
  })();

  const filteredRuns = useMemo(() => {
    if (!suiteFilter) return runs;
    return runs.filter((r) =>
      (r.official_suite || r.model_meta?.official_suite || "").includes(suiteFilter),
    );
  }, [runs, suiteFilter]);

  const metricAggs = useMemo(() => aggregateMetrics(filteredRuns), [filteredRuns]);
  const scoredRunCount = useMemo(
    () =>
      filteredRuns.filter((r) => Object.keys(runMetrics(r)).length > 0).length,
    [filteredRuns],
  );

  const detailMetrics = runMetrics(detail);

  return (
    <OpsShell
      wide
      secret={secret}
      title="Bench"
      subtitle="BEIR · LongBench · SWE-bench Lite · 指标与过程"
      actions={
        <>
          <button
            type="button"
            onClick={() => setShowCriteria((v) => !v)}
            className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            {showCriteria ? "收起标准" : "评判标准"}
          </button>
          {busy ? (
            <button
              type="button"
              onClick={() => void stopRun()}
              className="rounded-md border border-destructive/40 px-2 py-1 text-xs text-destructive hover:bg-destructive/10"
            >
              取消
            </button>
          ) : null}
          {error?.includes("已有 Bench") ? (
            <button
              type="button"
              onClick={() => void startRun({ force: true })}
              className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
            >
              强制重开
            </button>
          ) : null}
        </>
      }
    >
      {error ? (
        <p className="mb-4 whitespace-pre-wrap rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
          {error}
        </p>
      ) : null}

      {showCriteria ? (
        <section className="mb-5 grid gap-3 md:grid-cols-3">
          {criteria.map((c) => (
            <article key={c.id} className="rounded-lg border border-border bg-card/50 p-3 text-xs">
              <h3 className="font-semibold tracking-tight">{c.title}</h3>
              <p className="mt-0.5 text-muted-foreground">{c.official}</p>
              <p className="mt-2">
                <span className="text-muted-foreground">指标 </span>
                {c.metrics}
              </p>
              <p className="mt-1">
                <span className="text-muted-foreground">判定 </span>
                {c.pass_rule}
              </p>
            </article>
          ))}
        </section>
      ) : null}

      {/* Process legend */}
      <section className="mb-4 rounded-xl border border-border bg-muted/30 px-4 py-3 text-xs">
        <p className="font-semibold text-foreground">你始终该知道在干嘛（每个套件都是这三步）</p>
        <ol className="mt-2 grid gap-2 sm:grid-cols-3">
          <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
            <span className="font-medium">① 拉取 Pull</span>
            <p className="mt-0.5 text-muted-foreground">
              BEIR / LongBench / SWE 题集进缓存；<strong>已有则跳过下载</strong>。慢通常只发生在第一次。
            </p>
          </li>
          <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
            <span className="font-medium">② 评测 Eval</span>
            <p className="mt-0.5 text-muted-foreground">
              跑检索 / 上下文 / 编码，产出 nDCG、retention、patch 率等指标。
            </p>
          </li>
          <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
            <span className="font-medium">③ 回归 Regress</span>
            <p className="mt-0.5 text-muted-foreground">
              下方汇总表看多次跑分的最高 / 平均 / 中位；相对上次 Δ 也在检索日志里。
            </p>
          </li>
        </ol>
        <p className="mt-2 text-muted-foreground">
          首次拉 BEIR 走德国 UKP 源，国内慢可开代理；<strong>拉完会缓存</strong>，之后主要是 ②③。
        </p>
      </section>

      {/* Launch strip */}
      <section className="mb-5 rounded-xl border border-border bg-gradient-to-b from-card/80 to-background p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">发起一次 Bench</h2>
          <div className="flex flex-wrap gap-1.5">
            {presets.map((p) => (
              <button
                key={p.id}
                type="button"
                disabled={busy}
                title={p.hint}
                onClick={() => applyPreset(p)}
                className="rounded-full border border-border px-2.5 py-1 text-[11px] hover:bg-muted disabled:opacity-40"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {targetsMeta.map((t) => {
            const enabled = targetEnabled(t.id);
            const on = selectedTargets.has(t.id);
            return (
              <button
                key={t.id}
                type="button"
                disabled={!enabled || busy}
                onClick={() => toggleTarget(t.id)}
                className={`rounded-lg border px-3 py-2.5 text-left text-xs transition-colors ${
                  on && enabled
                    ? "border-foreground/50 bg-foreground/[0.06]"
                    : "border-border hover:bg-muted/50"
                } ${!enabled ? "cursor-not-allowed opacity-45" : ""}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{t.label}</span>
                  <span
                    className={`h-2 w-2 rounded-full ${on && enabled ? "bg-foreground" : "bg-border"}`}
                  />
                </div>
                <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
                  {t.description}
                  {!enabled ? "（镜像缺 datasets，请 rebuild api）" : ""}
                </p>
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={contextDry}
              disabled={busy}
              onChange={(e) => setContextDry(e.target.checked)}
            />
            上下文 dry（不调模型）
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={codingSkipApi}
              disabled={busy}
              onChange={(e) => setCodingSkipApi(e.target.checked)}
            />
            编码跳过平台 API
          </label>
          <button
            type="button"
            disabled={busy || Array.from(selectedTargets).filter(targetEnabled).length === 0}
            onClick={() => void startRun()}
            className="ml-auto rounded-md bg-foreground px-4 py-1.5 text-sm text-background disabled:opacity-40"
          >
            {busy ? "运行中…" : "开始"}
          </button>
          {error?.includes("已有 Bench") ? (
            <button
              type="button"
              onClick={() => void startRun({ force: true })}
              className="rounded-md border border-border px-3 py-1.5 text-sm"
            >
              强制重开
            </button>
          ) : null}
        </div>

        {(busy || liveLogs.length > 0) && (
          <div className="mt-4 space-y-2">
            <div className="rounded-md border border-border/80 bg-background/80 px-3 py-2 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  <span className="text-muted-foreground">当前阶段 · </span>
                  <span className="font-medium">{phaseHint}</span>
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  {timingLabel ? (
                    <span className="tabular-nums text-muted-foreground">{timingLabel}</span>
                  ) : null}
                  {busy ? (
                    <span className="rounded bg-foreground/10 px-1.5 py-0.5 text-[10px] tabular-nums">
                      直播中
                    </span>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">已结束 · 过程日志保留</span>
                  )}
                </div>
              </div>
            </div>
            <div className="rounded-md border border-border/80 bg-background/60 px-3 py-2 text-xs">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span>
                  <span className="text-muted-foreground">明细 · </span>
                  <span className="font-medium">{detailProgress.label}</span>
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {detailPct != null ? `${detailPct}%` : "—"}
                </span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-foreground/70 transition-[width] duration-200"
                  style={{ width: `${detailPct != null ? detailPct : busy ? 8 : 0}%` }}
                />
              </div>
            </div>
            <div className="flex justify-between text-[11px] text-muted-foreground">
              <span>
                套件完成 {progress.done}/{progress.total || "—"}
                （四个勾选项各算 1；单套内部进度看上面「明细」）
              </span>
              <span className="tabular-nums">
                {barPct}%
                {busy && etaSec != null ? ` · ~${formatDuration(etaSec)}` : ""}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-foreground/80 transition-[width] duration-300"
                style={{ width: `${barPct}%` }}
              />
            </div>
            <div
              ref={logBoxRef}
              className="max-h-48 overflow-y-auto overscroll-contain rounded-md border border-border/80 bg-muted/40 p-2 font-mono text-[11px] leading-relaxed"
            >
              {liveLogs.length === 0 ? (
                <p className="text-muted-foreground">
                  日志：先看 [pull] plan（几集、约多少 MiB），再看 %；评测看 [eval] dataset i/n
                  与 search %…
                </p>
              ) : (
                liveLogs.map((line, i) => (
                  <div
                    key={`${i}-${line.slice(0, 24)}`}
                    className={
                      line.includes("[phase]") || line.startsWith("[pull] plan")
                        ? "font-semibold text-foreground"
                        : undefined
                    }
                  >
                    {line}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </section>

      {/* Multi-run aggregates */}
      <section className="mb-5 rounded-xl border border-border p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">指标汇总</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              对筛选范围内、已有数值的跑次：n · 最低 · 中位 · 平均 · 最高 · 最近一次。
              {scoredRunCount > 0 ? ` 当前 ${scoredRunCount} 次有分。` : ""}
            </p>
          </div>
          <label className="flex items-center gap-1.5 text-xs">
            筛选
            <select
              className="rounded-md border border-border bg-background px-2 py-1"
              value={suiteFilter}
              onChange={(e) => setSuiteFilter(e.target.value)}
            >
              <option value="">全部套件</option>
              <option value="retrieval">含 retrieval</option>
              <option value="context">含 context</option>
              <option value="coding">含 coding</option>
            </select>
          </label>
        </div>

        {metricAggs.length === 0 ? (
          <p className="mt-4 text-xs text-muted-foreground">
            还没有可汇总的数值。先跑完「仅检索」（不要中途取消），指标会出现在这里。
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="border-b border-border py-2 pr-2 font-medium">指标</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">n</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">最低</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">中位</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">平均</th>
                  <th className="border-b border-border py-2 pr-2 font-medium">最高</th>
                  <th className="border-b border-border py-2 font-medium">最近</th>
                </tr>
              </thead>
              <tbody>
                {metricAggs.map((row) => (
                  <tr key={row.key} className="border-b border-border/60">
                    <td className="py-1.5 pr-2 font-mono text-[11px]">{row.key}</td>
                    <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">{row.n}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{row.min.toFixed(4)}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{row.median.toFixed(4)}</td>
                    <td className="py-1.5 pr-2 tabular-nums font-medium">{row.mean.toFixed(4)}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{row.max.toFixed(4)}</td>
                    <td className="py-1.5 tabular-nums text-muted-foreground">
                      {row.latest.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        {/* History table */}
        <aside className="rounded-xl border border-border">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <h2 className="text-sm font-semibold">历史 ({filteredRuns.length})</h2>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="text-[11px] text-muted-foreground underline disabled:opacity-40"
                disabled={busy || clearingHistory || runs.length === 0}
                title="清空 Bench 历史（数据库 + 报告目录；保留 BEIR 数据缓存）"
                onClick={() => void clearHistory()}
              >
                {clearingHistory ? "清空中…" : "清空"}
              </button>
              <button
                type="button"
                className="text-[11px] text-muted-foreground underline"
                onClick={() => void loadList()}
              >
                刷新
              </button>
            </div>
          </div>
          <div className="max-h-[32rem] overflow-y-auto">
            {filteredRuns.length === 0 ? (
              <p className="p-3 text-xs text-muted-foreground">暂无记录。</p>
            ) : (
              <ul>
                {filteredRuns.map((r) => {
                  const active = selectedId === r.id;
                  const m = runMetrics(r);
                  const headline =
                    m.ndcg_at_10 ??
                    m.retention_vs_full_f1 ??
                    m.patch_rate ??
                    m.n_instances;
                  const durSec = elapsedSeconds(
                    r.created_at,
                    isActiveStatus(r.status) ? null : r.finished_at,
                    nowMs,
                  );
                  return (
                    <li key={r.id} className="border-b border-border/70 last:border-0">
                      <div
                        className={`px-3 py-2.5 text-xs ${active ? "bg-muted" : "hover:bg-muted/60"}`}
                      >
                        <button
                          type="button"
                          className="w-full text-left"
                          onClick={() => navigate(opsOfficialPath(secret, r.id))}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">
                              {r.official_suite || r.model_meta?.official_suite || "bench"}
                            </span>
                            <span className={statusClass(r.status)}>{r.status}</span>
                          </div>
                          <div className="mt-0.5 flex justify-between gap-2 text-[11px] text-muted-foreground">
                            <span>{formatTime(r.created_at)}</span>
                            {durSec != null ? (
                              <span className="tabular-nums shrink-0">
                                {isActiveStatus(r.status) ? "已用 " : ""}
                                {formatDuration(durSec)}
                              </span>
                            ) : null}
                          </div>
                          <div className="mt-1 flex justify-between font-mono text-[10px] text-muted-foreground">
                            <span>{shortId(r.id)}</span>
                            <span>
                              {typeof headline === "number"
                                ? headline.toFixed(3)
                                : `${r.summary?.pass ?? 0}/${r.summary?.total ?? 0}`}
                            </span>
                          </div>
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        {/* Detail */}
        <div className="rounded-xl border border-border p-4">
          {!selectedId ? (
            <p className="text-sm text-muted-foreground">
              从左侧选一次 run，或点「开始」发起新评测。观测重点：指标趋势与 A/B Δ。
            </p>
          ) : !detail ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (
            <div className="space-y-4">
              <header>
                <h2 className="text-lg font-semibold tracking-tight">
                  {detail.title || detail.model_meta?.title || detail.id}
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  <span className={statusClass(detail.status)}>{detail.status}</span>
                  {" · "}
                  {formatTime(detail.created_at)} → {formatTime(detail.finished_at)}
                  {elapsedSec != null ? (
                    <>
                      {" · "}
                      <span className="tabular-nums">
                        {busy ? "已用" : "用时"} {formatDuration(elapsedSec)}
                        {busy && etaSec != null
                          ? ` · 预计剩余 ${formatDuration(etaSec)}`
                          : ""}
                      </span>
                    </>
                  ) : null}
                  {" · "}
                  pass {detail.summary?.pass ?? 0}/{detail.summary?.total ?? 0}
                </p>
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <button
                    type="button"
                    className="rounded-md border border-border px-2 py-1 hover:bg-muted"
                    disabled={!targetsFromRun(detail).some(targetEnabled)}
                    title="按相同目标强制重跑（会停掉当前活动轮）"
                    onClick={() => void rerunFrom(detail)}
                  >
                    重跑
                  </button>
                  <Link
                    className="rounded-md border border-border px-2 py-1 hover:bg-muted"
                    to={opsRunPath(secret, detail.id)}
                  >
                    通用 Run 页
                  </Link>
                </div>
                {detail.error ? (
                  <p className="mt-2 text-sm text-destructive">{detail.error}</p>
                ) : null}
              </header>

              <div className="flex flex-wrap gap-1.5 text-xs">
                {(["overview", "metrics", "cases", "log"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setTab(t)}
                    className={`rounded-md border px-2.5 py-1 ${
                      tab === t ? "border-foreground/40 bg-muted" : "border-border"
                    }`}
                  >
                    {t === "overview"
                      ? "总览"
                      : t === "metrics"
                        ? "指标"
                        : t === "cases"
                          ? "步骤"
                          : "日志"}
                  </button>
                ))}
              </div>

              {tab === "overview" ? (
                <div className="grid gap-3 sm:grid-cols-4">
                  {(
                    [
                      ["total", detail.summary?.total],
                      ["pass", detail.summary?.pass],
                      ["fail", detail.summary?.fail],
                      ["skipped", detail.summary?.skipped],
                    ] as const
                  ).map(([label, val]) => (
                    <div key={label} className="rounded-lg bg-muted/40 px-3 py-2 text-center">
                      <div className="text-[11px] text-muted-foreground">{label}</div>
                      <div className="text-xl font-semibold tabular-nums">{val ?? 0}</div>
                    </div>
                  ))}
                  <div className="sm:col-span-4">
                    <MetricBars metrics={detailMetrics} />
                  </div>
                </div>
              ) : null}

              {tab === "metrics" ? <MetricBars metrics={detailMetrics} /> : null}

              {tab === "cases" ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-border text-muted-foreground">
                      <tr>
                        <th className="py-2 pr-2">步骤</th>
                        <th className="py-2 pr-2">状态</th>
                        <th className="py-2">指标</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.cases || []).map((c) => (
                        <tr key={c.case_id} className="border-b border-border/60">
                          <td className="py-1.5 pr-2 font-mono">{c.case_id}</td>
                          <td className={`py-1.5 pr-2 ${statusClass(c.status)}`}>{c.status}</td>
                          <td className="py-1.5 font-mono text-[10px]">
                            {JSON.stringify(c.metrics || {})}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              {tab === "log" ? (
                <ol className="max-h-[28rem] space-y-2 overflow-y-auto text-xs">
                  {(detail.logs || []).map((item, i) => (
                    <li key={`${item.at}-${i}`} className="border-b border-border/50 pb-2">
                      <span className="text-muted-foreground">{formatTime(item.at)}</span>{" "}
                      <span className="rounded-full border border-border px-1.5 text-[10px] uppercase">
                        {item.kind || "log"}
                      </span>
                      <div className="mt-0.5 whitespace-pre-wrap font-mono text-[11px]">
                        {item.message}
                      </div>
                    </li>
                  ))}
                </ol>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </OpsShell>
  );
}
