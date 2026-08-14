import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useNavigate } from "react-router-dom";
import { harnessProgressView } from "../opsHarnessProgress";
import { opsOfficialPath } from "../OpsShell";
import {
  applyCodingLiveEvent,
  EMPTY_CODING_HARNESS,
  formatAstIndexRows,
  formatCodingCaseRows,
  parseAstIndexLine,
  parseCodingLiveLine,
} from "./codingLive";
import { formatSuiteDetails, mergeDetailProgress, parseProgressLine, targetsFromRun } from "./progressParse";
import { EventSourcePolyfill } from "./sse";
import type {
  AstIndexLive,
  CodingCaseLive,
  CodingHarnessLive,
  DetailProgress,
  OfficialLogItem,
  OfficialRun,
} from "./types";

const DEFAULT_PHASE = "全过程：① 拉取（已有则跳过）→ ② 评测 → ③ 回归对比上次指标";

function cleanPhase(raw: string): string {
  return raw.replace(/^\[phase\]\s*/i, "").trim();
}

export function isOfficialBenchActive(status?: string): boolean {
  return status === "queued" || status === "running" || status === "cancelling";
}

type Args = {
  secret: string;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setDetail: Dispatch<SetStateAction<OfficialRun | null>>;
  loadDetail: () => Promise<OfficialRun | null>;
  loadList: () => Promise<OfficialRun[]>;
};

export function useOfficialBenchStream({
  secret,
  setBusy,
  setError,
  setDetail,
  loadDetail,
  loadList,
}: Args) {
  const navigate = useNavigate();
  const [logs, setLogs] = useState<string[]>([]);
  const [logItems, setLogItems] = useState<OfficialLogItem[]>([]);
  const [lastFinishedId, setLastFinishedId] = useState<string | null>(null);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [phaseHint, setPhaseHint] = useState(DEFAULT_PHASE);
  const [suiteDetails, setSuiteDetails] = useState<Record<string, DetailProgress>>({});
  const [astIndexByIid, setAstIndexByIid] = useState<Record<string, AstIndexLive>>({});
  const [coding, setCoding] = useState<{
    byIid: Record<string, CodingCaseLive>;
    harness: CodingHarnessLive;
  }>({ byIid: {}, harness: EMPTY_CODING_HARNESS });
  const sourceRef = useRef<EventSourcePolyfill | null>(null);
  const attachedRunIdRef = useRef<string | null>(null);

  const reset = useCallback((resetProgress = false) => {
    setLogs([]);
    setLogItems([]);
    setSuiteDetails({});
    setAstIndexByIid({});
    setCoding({ byIid: {}, harness: { ...EMPTY_CODING_HARNESS } });
    if (resetProgress) {
      setProgress({ done: 0, total: 0 });
      setPhaseHint(DEFAULT_PHASE);
    }
  }, []);

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
    const nextDetails: Record<string, DetailProgress> = {};
    const nextAst: Record<string, AstIndexLive> = {};
    let nextCoding: Record<string, CodingCaseLive> = {};
    let nextHarness: CodingHarnessLive = { ...EMPTY_CODING_HARNESS };
    for (const item of run.logs || []) {
      if (String(item.kind || "") !== "log" || !item.message) continue;
      const msg = String(item.message);
      const parsed = parseProgressLine(msg);
      if (parsed?.suite) {
        const prev = nextDetails[parsed.suite];
        if (!(parsed.kind === "pull" && prev?.kind === "eval")) {
          nextDetails[parsed.suite] = mergeDetailProgress(prev, parsed);
        }
      }
      const ast = parseAstIndexLine(msg);
      if (ast) nextAst[ast.iid] = ast;
      const codingEvent = parseCodingLiveLine(msg);
      if (codingEvent) {
        const applied = applyCodingLiveEvent(nextCoding, nextHarness, codingEvent);
        nextCoding = applied.byIid;
        nextHarness = applied.harness;
      }
    }
    setSuiteDetails(nextDetails);
    setAstIndexByIid(nextAst);
    setCoding({ byIid: nextCoding, harness: nextHarness });
    if (opts?.logs === false) return;
    const lines: string[] = [];
    for (const item of run.logs || []) {
      const kind = String(item.kind || "");
      if (kind === "log" && item.message) {
        const msg = String(item.message);
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
    setLogs(lines.slice(-800));
    setLogItems((run.logs || []).slice(-2000));
  }, []);

  const detach = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    attachedRunIdRef.current = null;
    setBusy(false);
  }, [setBusy]);

  const attach = useCallback(
    (runId: string, opts?: { resetLogs?: boolean }) => {
      if (attachedRunIdRef.current === runId && sourceRef.current) {
        setBusy(true);
        return;
      }
      sourceRef.current?.close();
      attachedRunIdRef.current = runId;
      setBusy(true);
      setError(null);
      if (opts?.resetLogs) reset();
      const source = new EventSourcePolyfill(
        `/api/v1/ops/official/runs/${runId}/stream`,
        secret,
      );
      sourceRef.current = source;
      source.onmessage = (event) => {
        if (attachedRunIdRef.current !== runId) return;
        try {
          const data = JSON.parse(event.data) as Record<string, unknown>;
          const kind = String(data.kind || "");
          const at = data.at != null ? String(data.at) : new Date().toISOString();
          const pushLogItem = (item: OfficialLogItem) => {
            setLogItems((prev) => [...prev.slice(-1999), item]);
          };
          if (kind === "phase") {
            const message = String(data.message || data.phase || "");
            setPhaseHint(cleanPhase(message));
            pushLogItem({
              at,
              kind: "phase",
              message,
              phase: data.phase != null ? String(data.phase) : undefined,
            });
          } else if (kind === "log") {
            const message = String(data.message || "");
            const parsed = parseProgressLine(message);
            if (parsed?.suite) {
              setSuiteDetails((prev) => {
                const current = prev[parsed.suite!];
                if (parsed.kind === "pull" && current?.kind === "eval") return prev;
                return {
                  ...prev,
                  [parsed.suite!]: mergeDetailProgress(current, parsed),
                };
              });
            } else if (
              message.startsWith("[pull]") ||
              message.startsWith("[L1] pull") ||
              message.startsWith("[progress] pull")
            ) {
              setSuiteDetails((prev) => ({
                ...prev,
                _: {
                  kind: "pull",
                  label: message.replace(/^\[(pull|progress|L1)\]\s*/i, "").slice(0, 120),
                  pct: prev._?.pct ?? null,
                },
              }));
            }
            const ast = parseAstIndexLine(message);
            if (ast) setAstIndexByIid((prev) => ({ ...prev, [ast.iid]: ast }));
            const codingEvent = parseCodingLiveLine(message);
            if (codingEvent) {
              setCoding((prev) => {
                const applied = applyCodingLiveEvent(
                  prev.byIid,
                  prev.harness,
                  codingEvent,
                );
                return { byIid: applied.byIid, harness: applied.harness };
              });
            }
            if (
              !message.startsWith("[progress]") ||
              message.startsWith("[progress] pull")
            ) {
              setLogs((prev) => [...prev.slice(-800), message]);
              pushLogItem({ at, kind: "log", message });
            }
          } else if (kind === "case_started") {
            setLogs((prev) => [...prev, `→ ${data.case_id}`]);
            pushLogItem({
              at,
              kind: "case_started",
              message: data.case_id != null ? `→ ${data.case_id}` : "case_started",
              case_id: data.case_id != null ? String(data.case_id) : undefined,
            });
            void loadList();
          } else if (kind === "case_finished") {
            const message = `${data.status === "pass" ? "✓" : data.status === "skipped" ? "○" : "✗"} ${data.case_id}`;
            setLogs((prev) => [...prev, message]);
            pushLogItem({
              at,
              kind: "case_finished",
              message: data.case_id != null ? message : "case_finished",
              case_id: data.case_id != null ? String(data.case_id) : undefined,
              status: data.status != null ? String(data.status) : undefined,
            });
            setProgress((prev) => ({
              done: Number(data.progress_done != null ? data.progress_done : prev.done),
              total: Number(data.progress_total || prev.total || 0),
            }));
            const metrics = data.metrics;
            const caseId = String(data.case_id || "");
            if (caseId && metrics && typeof metrics === "object" && !Array.isArray(metrics)) {
              setDetail((prev) => {
                if (!prev || prev.id !== runId) return prev;
                const cases = (prev.cases || []).map((item) =>
                  item.case_id === caseId
                    ? {
                        ...item,
                        status: String(data.status || item.status),
                        metrics: metrics as Record<string, number>,
                      }
                    : item,
                );
                return {
                  ...prev,
                  cases,
                  summary: {
                    ...(prev.summary || {}),
                    total: cases.length,
                    pass: cases.filter((item) => item.status === "pass").length,
                    fail: cases.filter((item) => item.status === "fail").length,
                    skipped: cases.filter((item) => item.status === "skipped").length,
                    pending: cases.filter(
                      (item) => item.status === "pending" || item.status === "running",
                    ).length,
                    progress_done: Number(
                      data.progress_done || prev.summary?.progress_done || 0,
                    ),
                    progress_total: Number(
                      data.progress_total || prev.summary?.progress_total || 0,
                    ),
                  },
                };
              });
            }
            void loadDetail();
            void loadList();
          } else if (kind === "run_started") {
            pushLogItem({ at, kind: "run_started", message: "run_started" });
            void loadList();
          } else if (kind === "run_finished") {
            pushLogItem({
              at,
              kind: "run_finished",
              message: `run_finished status=${String(data.status || "")}`,
              status: data.status != null ? String(data.status) : undefined,
            });
            source.close();
            if (attachedRunIdRef.current === runId) attachedRunIdRef.current = null;
            setBusy(false);
            setLastFinishedId(runId);
            reset(true);
            navigate(opsOfficialPath(secret), { replace: true });
            void loadList();
          }
        } catch {
          /* ignore malformed events */
        }
      };
      source.onerror = () => {
        source.close();
        if (attachedRunIdRef.current === runId) attachedRunIdRef.current = null;
        void loadDetail().finally(() => setBusy(false));
      };
    },
    [loadDetail, loadList, navigate, reset, secret, setBusy, setDetail, setError],
  );

  useEffect(() => () => sourceRef.current?.close(), []);

  const detailProgress = useMemo(() => formatSuiteDetails(suiteDetails), [suiteDetails]);
  const astIndexRows = useMemo(() => formatAstIndexRows(astIndexByIid), [astIndexByIid]);
  const codingRows = useMemo(() => formatCodingCaseRows(coding.byIid), [coding.byIid]);
  const codingSummary = useMemo(() => {
    let running = 0;
    let pass = 0;
    let fail = 0;
    let resolved = 0;
    for (const row of codingRows) {
      if (row.status === "running" || row.status === "pending") running += 1;
      else if (row.status === "pass") pass += 1;
      else if (row.status === "fail") fail += 1;
      if (row.harness === "resolved") resolved += 1;
    }
    return {
      running,
      pass,
      fail,
      resolved,
      total: codingRows.length,
      harness: coding.harness,
      harnessView: harnessProgressView(coding.harness),
    };
  }, [coding.harness, codingRows]);
  const astIndexSummary = useMemo(() => {
    let building = 0;
    let ready = 0;
    let error = 0;
    let disabled = 0;
    for (const row of astIndexRows) {
      if (row.status === "ready" || row.status === "stale") ready += 1;
      else if (
        row.status === "error" ||
        row.status === "watch_timeout" ||
        row.status === "cancelled"
      )
        error += 1;
      else if (row.status === "disabled") disabled += 1;
      else building += 1;
    }
    return { building, ready, error, disabled, total: astIndexRows.length };
  }, [astIndexRows]);

  const live = {
    logs,
    logItems,
    lastFinishedId,
    progress,
    phaseHint,
    suiteDetails,
    astIndexByIid,
    coding,
    detailProgress,
    astIndexRows,
    codingRows,
    codingSummary,
    astIndexSummary,
    attachedRunId: attachedRunIdRef.current,
    setLastFinishedId,
    setLogs,
    setLogItems,
    setProgress,
    setPhaseHint,
    setSuiteDetails,
    setAstIndexByIid,
    setCoding,
    applyRunSnapshot,
    reset,
  };
  return { live, attach, detach };
}
