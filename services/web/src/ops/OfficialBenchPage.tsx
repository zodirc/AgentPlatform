import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  OpsShell,
  opsOfficialPath,
  opsRunPath,
  secretFromOpsPath,
  statusClass,
} from "./OpsShell";
import { opsApiErrorText, opsDisplayText } from "./opsDisplayText";
import { isOpsErrorLogLine } from "./opsLogStyle";
import { ArtifactsPanel } from "./bench/ArtifactsPanel";
import { HARNESS_STAGE_LABEL } from "./bench/codingLive";
import {
  cleanPhase,
  elapsedSeconds,
  formatDuration,
  formatTime,
  isActiveStatus,
  shortId,
} from "./bench/format";
import { HistoryPane } from "./bench/HistoryPane";
import { LivePane } from "./bench/LivePane";
import {
  aggregateMetrics,
  historyHeadlineMetric,
  isEffectEligible,
  runMetrics,
} from "./bench/metrics";
import {
  isOpsKeyLogItem,
  liveLogLineClass,
  MetricBars,
  OfficialLogLine,
} from "./bench/officialLog";
import {
  BENCH_SCENARIO_GROUPS,
  contextTierLabel,
  CUSTOM_PROFILE_ID,
  FALLBACK_SUITE_META,
  inferApiStyle,
  inferProfileIdFromSaved,
  L1_RUN_PROFILES,
  presetById,
  PROVIDER_PRESETS,
  retrievalTierLabel,
  runSuitesLabel,
  suitesFromRun,
  suitesFromTargets,
  suitesLabelZh,
  tierFromLimit,
} from "./bench/presets";
import {
  shortCaseToken,
  SUITE_DETAIL_LABEL,
} from "./bench/progressParse";
import { downloadAuthorizedFile, openAuthorizedHtml } from "./bench/sse";
import { SummaryPane } from "./bench/SummaryPane";
import { useOfficialBenchStream } from "./bench/useOfficialBenchStream";
import type {
  ApiStyle,
  Caps,
  CodingTierMeta,
  ContextTier,
  Criterion,
  OfficialRun,
  Preset,
  RetrievalTier,
  RunArtifacts,
  SuiteId,
  TargetMeta,
} from "./bench/types";
import { SUITE_IDS } from "./bench/types";

export function OfficialBenchPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const secret = secretFromOpsPath(pathname);
  const selectedId = pathname.match(/\/official\/([^/]+)\/?$/)?.[1] || "";

  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [targetsMeta, setTargetsMeta] = useState<TargetMeta[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [caps, setCaps] = useState<Caps>({});
  const [selectedSuites, setSelectedSuites] = useState<Set<SuiteId>>(
    () => new Set(["retrieval", "coding"]),
  );
  const [codingTier, setCodingTier] = useState("n5");
  const [codingNInstances, setCodingNInstances] = useState(5);
  const [codingHarness] = useState(true);
  const [codingCheckoutRepo, setCodingCheckoutRepo] = useState(true);
  /** Await AST ready before StartTurn; default off (R1). */
  const [workspaceIndexWaitReady, setWorkspaceIndexWaitReady] = useState(false);
  const [codingTierMeta, setCodingTierMeta] = useState<CodingTierMeta[]>([
    { id: "n3", n_instances: 3 },
    { id: "n5", n_instances: 5 },
    { id: "n10", n_instances: 10 },
    { id: "n25", n_instances: 25 },
    { id: "full300", n_instances: 300 },
    { id: "custom", n_instances: null },
  ]);
  const [retrievalProd, setRetrievalProd] = useState(true);
  /** L1 LongBench size tier: full ≈120; others are hard caps. */
  const [contextTier, setContextTier] = useState<ContextTier>("20");
  /** L1 BEIR qrels queries-per-dataset tier. */
  const [retrievalTier, setRetrievalTier] = useState<RetrievalTier>("20");
  /** Concurrent product Turns inside one L1 suite. */
  const [l1Parallel, setL1Parallel] = useState(1);
  const [activeProfileId, setActiveProfileId] = useState("l1_balanced");
  /** Which profile's param form is expanded (click chip again to collapse). */
  const [profileFormOpen, setProfileFormOpen] = useState(true);
  // Empty until user picks a preset or restores real prefs — do not invent deepseek defaults.
  const [modelProvider, setModelProvider] = useState("");
  const [modelApiStyle, setModelApiStyle] = useState<ApiStyle>("openai");
  const [modelName, setModelName] = useState("");
  const [modelBaseUrl, setModelBaseUrl] = useState("");
  const [modelApiKey, setModelApiKey] = useState("");
  const [modelContextWindow, setModelContextWindow] = useState("");
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeMessage, setProbeMessage] = useState<string | null>(null);
  const [probeOk, setProbeOk] = useState<boolean | null>(null);
  const [prefsReady, setPrefsReady] = useState(false);
  /** Last api_key successfully written to localStorage ("" = none saved). */
  const [storedApiKey, setStoredApiKey] = useState("");
  const [apiKeyEditing, setApiKeyEditing] = useState(false);
  const [apiKeySaveFlash, setApiKeySaveFlash] = useState(false);
  const [showCriteria, setShowCriteria] = useState(false);
  /** 本轮 = 发起+直播；历史 = 列表+详情；指标汇总跨跑次。默认进本轮，不自动摊开历史详情。 */
  const [pagePane, setPagePane] = useState<"live" | "history" | "summary">(
    "live",
  );
  const [suiteFilter, setSuiteFilter] = useState<string>("");
  const [runs, setRuns] = useState<OfficialRun[]>([]);
  const [detail, setDetail] = useState<OfficialRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [clearingHistory, setClearingHistory] = useState(false);
  const [historySelectMode, setHistorySelectMode] = useState(false);
  const [checkedRunIds, setCheckedRunIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [astIndexExpanded, setAstIndexExpanded] = useState(false);
  const [tab, setTab] = useState<
    "overview" | "metrics" | "cases" | "artifacts" | "log"
  >("overview");
  const [artifacts, setArtifacts] = useState<RunArtifacts | null>(null);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const logBoxRef = useRef<HTMLDivElement>(null);
  /** First finished deep-link may open 历史; later finished loads must not yank off 本轮. */
  const historyDeepLinkDoneRef = useRef(false);

  const headers = useMemo(
    () => ({
      Authorization: `Bearer ${secret}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    }),
    [secret],
  );

  // Restore Bench prefs (model + suites + run profile). api_key only if explicitly saved.
  // v1 auto-wrote form defaults (deepseek-chat) — only restore model when v>=2 or key present.
  useEffect(() => {
    try {
      const raw = localStorage.getItem("ops.bench.prefs");
      if (raw) {
        const saved = JSON.parse(raw) as {
          v?: number;
          provider?: string;
          api_style?: string;
          model_name?: string;
          base_url?: string;
          context_window_tokens?: string;
          remember_api_key?: boolean;
          api_key?: string;
          suites?: string[];
          coding_tier?: string;
          coding_n?: number;
          coding_harness?: boolean;
          coding_checkout_repo?: boolean;
          workspace_index_wait_ready?: boolean;
          retrieval_prod?: boolean;
          eval_path?: string;
          context_tier?: string;
          retrieval_tier?: string;
          l1_max_parallel?: number;
          retrieval_arm?: string;
          context_arm?: string;
          active_profile_id?: string;
        };
        const storedKey =
          saved.remember_api_key === false ? "" : String(saved.api_key || "");
        const hasKey = Boolean(storedKey);
        const restoreModel = (saved.v ?? 0) >= 2 || hasKey;
        if (restoreModel) {
          if (saved.provider) setModelProvider(saved.provider);
          if (saved.model_name) {
            const migrated =
              saved.provider === "deepseek" &&
              saved.model_name === "deepseek-chat"
                ? "deepseek-v4-flash"
                : saved.model_name;
            setModelName(migrated);
          }
          if (saved.base_url != null) setModelBaseUrl(saved.base_url);
          if (saved.context_window_tokens != null) {
            setModelContextWindow(String(saved.context_window_tokens));
          } else if (
            saved.provider === "deepseek" &&
            (!saved.model_name || saved.model_name === "deepseek-chat")
          ) {
            setModelContextWindow("128000");
          }
          setModelApiStyle(
            inferApiStyle(saved.provider || "", saved.api_style),
          );
        }
        if (hasKey) {
          setModelApiKey(storedKey);
          setStoredApiKey(storedKey);
          setApiKeyEditing(false);
        } else {
          setApiKeyEditing(true);
        }
        if (Array.isArray(saved.suites) && saved.suites.length) {
          setSelectedSuites(
            new Set(
              saved.suites.filter((s): s is SuiteId =>
                (SUITE_IDS as readonly string[]).includes(s),
              ),
            ),
          );
        }
        if (saved.coding_tier) setCodingTier(saved.coding_tier);
        if (saved.coding_n != null) setCodingNInstances(saved.coding_n);
        // coding_harness is always on — ignore saved false from older prefs.
        if (typeof saved.coding_checkout_repo === "boolean") {
          // Checkout is mandatory for coding structural / git_diff — ignore saved false.
          setCodingCheckoutRepo(true);
        }
        if (typeof saved.workspace_index_wait_ready === "boolean") {
          setWorkspaceIndexWaitReady(saved.workspace_index_wait_ready);
        }
        if (typeof saved.retrieval_prod === "boolean")
          setRetrievalProd(saved.retrieval_prod);
        if (
          saved.context_tier === "10" ||
          saved.context_tier === "20" ||
          saved.context_tier === "full"
        ) {
          setContextTier(saved.context_tier);
        }
        if (
          saved.retrieval_tier === "10" ||
          saved.retrieval_tier === "20" ||
          saved.retrieval_tier === "full"
        ) {
          setRetrievalTier(saved.retrieval_tier);
        }
        if (
          saved.l1_max_parallel != null &&
          Number.isFinite(saved.l1_max_parallel)
        ) {
          setL1Parallel(Number(saved.l1_max_parallel));
        }
        // Arms are free-only on Ops acceptance path; ignore legacy forced/oracle prefs.
        if (
          typeof saved.active_profile_id === "string" &&
          saved.active_profile_id
        ) {
          setActiveProfileId(saved.active_profile_id);
        } else if (Array.isArray(saved.suites) && saved.suites.length) {
          setActiveProfileId(inferProfileIdFromSaved(saved));
        }
      } else {
        const old = localStorage.getItem("ops.bench.model");
        if (old) {
          const key = sessionStorage.getItem("ops.bench.model.api_key");
          if (key) {
            const saved = JSON.parse(old) as {
              provider?: string;
              model_name?: string;
              base_url?: string;
              context_window_tokens?: string;
            };
            if (saved.provider) setModelProvider(saved.provider);
            if (saved.model_name) setModelName(saved.model_name);
            if (saved.base_url != null) setModelBaseUrl(saved.base_url);
            if (saved.context_window_tokens != null) {
              setModelContextWindow(String(saved.context_window_tokens));
            }
            setModelApiKey(key);
            setStoredApiKey(key);
            setApiKeyEditing(false);
          } else {
            setApiKeyEditing(true);
          }
        } else {
          setApiKeyEditing(true);
        }
      }
    } catch {
      setApiKeyEditing(true);
    } finally {
      setPrefsReady(true);
    }
  }, []);

  // Persist non-secret prefs; keep previously saved api_key unless save/clear handlers update it.
  useEffect(() => {
    if (!prefsReady) return;
    try {
      let existingKey = "";
      try {
        const raw = localStorage.getItem("ops.bench.prefs");
        if (raw) {
          const prev = JSON.parse(raw) as {
            api_key?: string;
            remember_api_key?: boolean;
          };
          if (prev.remember_api_key !== false)
            existingKey = String(prev.api_key || "");
        }
      } catch {
        /* ignore */
      }
      localStorage.setItem(
        "ops.bench.prefs",
        JSON.stringify({
          v: 3,
          provider: modelProvider,
          api_style: modelApiStyle,
          model_name: modelName,
          base_url: modelBaseUrl,
          context_window_tokens: modelContextWindow,
          api_key: existingKey,
          suites: Array.from(selectedSuites),
          coding_tier: codingTier,
          coding_n: codingNInstances,
          coding_harness: codingHarness,
          coding_checkout_repo: true,
          workspace_index_wait_ready: workspaceIndexWaitReady,
          retrieval_prod: retrievalProd,
          eval_path: "agent",
          context_tier: contextTier,
          retrieval_tier: retrievalTier,
          l1_max_parallel: l1Parallel,
          retrieval_arm: "free",
          context_arm: "free",
          active_profile_id: activeProfileId,
        }),
      );
    } catch {
      /* ignore */
    }
  }, [
    prefsReady,
    modelProvider,
    modelApiStyle,
    modelName,
    modelBaseUrl,
    modelContextWindow,
    selectedSuites,
    codingTier,
    codingNInstances,
    codingHarness,
    codingCheckoutRepo,
    workspaceIndexWaitReady,
    retrievalProd,
    contextTier,
    retrievalTier,
    l1Parallel,
    activeProfileId,
  ]);

  const persistApiKey = useCallback((key: string) => {
    try {
      let base: Record<string, unknown> = { v: 2 };
      try {
        const raw = localStorage.getItem("ops.bench.prefs");
        if (raw) base = { ...JSON.parse(raw), v: 2 };
      } catch {
        /* ignore */
      }
      base.api_key = key;
      delete base.remember_api_key;
      localStorage.setItem("ops.bench.prefs", JSON.stringify(base));
    } catch {
      /* ignore */
    }
    setStoredApiKey(key);
  }, []);

  const saveApiKey = useCallback(() => {
    const key = modelApiKey.trim();
    if (!key) return;
    persistApiKey(key);
    setModelApiKey(key);
    setApiKeyEditing(false);
    setApiKeySaveFlash(true);
    window.setTimeout(() => setApiKeySaveFlash(false), 1500);
  }, [modelApiKey, persistApiKey]);

  const clearApiKey = useCallback(() => {
    persistApiKey("");
    setModelApiKey("");
    setApiKeyEditing(true);
    setApiKeySaveFlash(false);
  }, [persistApiKey]);

  const probeModel = useCallback(async () => {
    const key = modelApiKey.trim();
    const name = modelName.trim();
    const provider = modelProvider.trim() || "custom";
    if (!key || !name) {
      setProbeOk(false);
      setProbeMessage("请先填写 model_name 与 api_key。");
      return;
    }
    setProbeBusy(true);
    setProbeOk(null);
    setProbeMessage("正在从 bench 容器探测…");
    try {
      const cw = Number(modelContextWindow);
      const resp = await fetch("/api/v1/ops/official/model/probe", {
        method: "POST",
        headers,
        body: JSON.stringify({
          provider,
          api_style: inferApiStyle(provider, modelApiStyle),
          model_name: name,
          api_key: key,
          base_url: modelBaseUrl.trim() || undefined,
          context_window_tokens:
            Number.isFinite(cw) && cw >= 1024 ? Math.floor(cw) : undefined,
        }),
      });
      const text = await resp.text();
      let data: {
        ok?: boolean;
        latency_ms?: number;
        preview?: string;
        error?: string;
        endpoint?: string;
        detail?: string;
      } = {};
      try {
        data = JSON.parse(text) as typeof data;
      } catch {
        /* keep */
      }
      if (!resp.ok) {
        setProbeOk(false);
        setProbeMessage(opsApiErrorText(data, text || `HTTP ${resp.status}`));
        return;
      }
      if (data.ok) {
        setProbeOk(true);
        const preview = (data.preview || "").replace(/\s+/g, " ").trim();
        setProbeMessage(
          `联通成功 · ${data.latency_ms ?? "?"}ms` +
            (data.endpoint ? ` · ${data.endpoint}` : "") +
            (preview ? ` · 回复「${preview.slice(0, 40)}」` : ""),
        );
      } else {
        setProbeOk(false);
        setProbeMessage(
          opsDisplayText(data.error) ||
            `联通失败` +
              (data.endpoint ? ` · ${data.endpoint}` : "") +
              (data.latency_ms != null ? ` · ${data.latency_ms}ms` : ""),
        );
      }
    } catch (e) {
      setProbeOk(false);
      setProbeMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setProbeBusy(false);
    }
  }, [
    headers,
    modelApiKey,
    modelApiStyle,
    modelBaseUrl,
    modelContextWindow,
    modelName,
    modelProvider,
  ]);

  const apiKeyDirty = modelApiKey.trim() !== storedApiKey;
  const apiKeyStored = Boolean(storedApiKey);

  const needsLiveModel = useMemo(
    () =>
      selectedSuites.has("context") ||
      selectedSuites.has("coding") ||
      selectedSuites.has("retrieval") ||
      selectedSuites.has("retrieval_zh"),
    [selectedSuites],
  );

  const applyProviderPreset = (provider: string) => {
    setModelProvider(provider);
    if (!provider) {
      setModelName("");
      setModelBaseUrl("");
      setModelApiStyle("openai");
      return;
    }
    if (provider === "custom") {
      // Keep current fields; user chooses API protocol explicitly.
      return;
    }
    const preset = presetById(provider);
    if (!preset) return;
    setModelApiStyle(preset.api_style);
    setModelName(preset.model);
    setModelBaseUrl(preset.base_url);
    if (preset.context_window && !modelContextWindow) {
      setModelContextWindow(preset.context_window);
    } else if (preset.context_window) {
      setModelContextWindow(preset.context_window);
    }
  };

  const targetEnabled = useCallback(
    (id: string) => {
      if (id === "retrieval")
        return caps.retrieval !== false && caps.script !== false;
      if (!caps.script && !caps.bench_worker) return false;
      if (id === "coding") {
        return (
          caps.coding_infer !== false ||
          caps.script !== false ||
          caps.bench_worker === true
        );
      }
      if (caps.datasets === false && (id === "context" || id === "coding")) {
        // Still ok if remote bench has datasets
        if (caps.bench_worker) return true;
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
      coding_tiers?: CodingTierMeta[];
      defaults?: {
        coding_tier?: string;
        coding_n_instances?: number | null;
        coding_harness?: boolean;
        retrieval_prod?: boolean;
        eval_path?: "agent" | "component";
        context_tier?: ContextTier;
        retrieval_tier?: RetrievalTier;
        l1_max_parallel?: number;
        targets?: string[];
      };
    };
    setCriteria(body.criteria || []);
    setTargetsMeta(body.targets || []);
    const apiPresets = body.presets || [];
    const merged = (
      apiPresets.some((p) => p.id === "l1_balanced" || p.retrieval_tier != null)
        ? apiPresets
        : L1_RUN_PROFILES
    ).filter(
      (p) =>
        p.id !== "p1_lexical_micro" &&
        p.id !== "scifact_micro_l1" &&
        !(p.targets || []).includes("p1_lexical_micro"),
    );
    setPresets(merged);
    setCaps(body.capabilities || {});
    if (body.coding_tiers?.length) setCodingTierMeta(body.coding_tiers);

    // Local prefs win over API defaults. Previously loadMeta always forced
    // l1_balanced + defaults, so refresh after 「自定义」looked like 「适中」again.
    let hasLocalRunPrefs = false;
    let savedProfileId = "";
    try {
      const raw = localStorage.getItem("ops.bench.prefs");
      if (raw) {
        const saved = JSON.parse(raw) as {
          suites?: unknown;
          active_profile_id?: string;
        };
        hasLocalRunPrefs =
          Array.isArray(saved.suites) && saved.suites.length > 0;
        if (typeof saved.active_profile_id === "string") {
          savedProfileId = saved.active_profile_id;
        }
      }
    } catch {
      /* ignore */
    }

    if (!hasLocalRunPrefs) {
      const d = body.defaults;
      if (d?.coding_tier) setCodingTier(d.coding_tier);
      if (d?.coding_n_instances != null)
        setCodingNInstances(d.coding_n_instances);
      if (d?.retrieval_prod !== undefined) setRetrievalProd(d.retrieval_prod);
      if (d?.context_tier) setContextTier(d.context_tier);
      if (d?.retrieval_tier) setRetrievalTier(d.retrieval_tier);
      if (d?.l1_max_parallel != null) setL1Parallel(d.l1_max_parallel);
      if (d?.targets?.length) {
        const suites = suitesFromTargets(d.targets);
        if (suites.size) setSelectedSuites(suites);
      }
      setActiveProfileId(
        merged.some((p) => p.id === "l1_balanced")
          ? "l1_balanced"
          : merged[0]?.id || "",
      );
    } else if (savedProfileId) {
      const known =
        savedProfileId === CUSTOM_PROFILE_ID ||
        merged.some((p) => p.id === savedProfileId) ||
        L1_RUN_PROFILES.some((p) => p.id === savedProfileId);
      setActiveProfileId(known ? savedProfileId : CUSTOM_PROFILE_ID);
    } else {
      try {
        const raw = localStorage.getItem("ops.bench.prefs");
        if (raw) setActiveProfileId(inferProfileIdFromSaved(JSON.parse(raw)));
      } catch {
        /* ignore */
      }
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
    const resp = await fetch(`/api/v1/ops/official/runs/${selectedId}`, {
      headers,
    });
    if (!resp.ok) return null;
    const body = (await resp.json()) as OfficialRun;
    setDetail(body);
    return body;
  }, [headers, selectedId]);

  const { live, attach: attachLiveStream, detach: detachLiveStream } =
    useOfficialBenchStream({
      secret,
      setBusy,
      setError,
      setDetail,
      loadDetail,
      loadList,
    });
  const {
    logs: liveLogs,
    logItems: liveLogItems,
    lastFinishedId: lastFinishedLiveId,
    progress,
    phaseHint,
    detailProgress,
    astIndexRows,
    codingRows,
    codingSummary,
    astIndexSummary,
    setLastFinishedId: setLastFinishedLiveId,
    setProgress,
    setPhaseHint,
    setSuiteDetails,
    applyRunSnapshot,
    reset: resetLive,
  } = live;

  useEffect(() => {
    setArtifacts(null);
    setArtifactsError(null);
  }, [selectedId]);

  useEffect(() => {
    if (tab !== "artifacts" || !selectedId) return;
    let cancelled = false;
    setArtifactsLoading(true);
    setArtifactsError(null);
    void (async () => {
      try {
        const resp = await fetch(
          `/api/v1/ops/official/runs/${selectedId}/artifacts`,
          { headers },
        );
        if (!resp.ok) {
          const text = await resp.text();
          if (!cancelled) {
            setArtifacts(null);
            setArtifactsError(
              opsApiErrorText(text, text || `HTTP ${resp.status}`),
            );
          }
          return;
        }
        const body = (await resp.json()) as RunArtifacts;
        if (!cancelled) setArtifacts(body);
      } catch (e) {
        if (!cancelled) {
          setArtifacts(null);
          setArtifactsError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setArtifactsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, selectedId, headers]);

  useEffect(() => {
    void loadMeta();
    void (async () => {
      const list = await loadList();
      // Do not auto-navigate into the latest/live run — user picks from 历史.
      // Only reconnect SSE when the URL already points at that live run.
      const live = list.find(
        (r) =>
          isActiveStatus(r.status) && (r.source === "live" || !r.finished_at),
      );
      if (!live || !selectedId || selectedId !== live.id) return;
      setPagePane((p) => (p === "summary" ? p : "live"));
      applyRunSnapshot(live, { logs: false });
      attachLiveStream(live.id, { resetLogs: true });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount reconnect
  }, [loadMeta, loadList, secret]);

  const liveRun = useMemo(
    () =>
      runs.find((r) => isActiveStatus(r.status) && r.source === "live") ?? null,
    [runs],
  );

  /** Params shown in the summary: live/selected run truth, else local form. */
  const paramsFromActiveRun = useMemo(() => {
    const src =
      (detail && isActiveStatus(detail.status) && detail.id === selectedId
        ? detail
        : null) || (liveRun && liveRun.id === selectedId ? liveRun : null);
    if (!src) return null;
    const suites = suitesFromRun(src);
    const meta = src.model_meta || {};
    const ctxLim = src.context_limit ?? meta.context_limit;
    const retLim = src.retrieval_query_limit ?? meta.retrieval_query_limit;
    const parallel = src.l1_max_parallel ?? meta.l1_max_parallel ?? 1;
    const corpusMode = String(
      src.retrieval_corpus_mode || meta.retrieval_corpus_mode || "full",
    );
    const datasetsRaw = src.retrieval_datasets || meta.retrieval_datasets || [];
    const datasets = Array.isArray(datasetsRaw) ? datasetsRaw : [];
    const scifactMicro =
      (corpusMode === "gold" || corpusMode === "micro") &&
      datasets.map((d) => String(d).toLowerCase()).includes("scifact");
    return {
      suites,
      contextTier: tierFromLimit(ctxLim, "context") as ContextTier,
      retrievalTier: (scifactMicro
        ? "scifact_micro"
        : tierFromLimit(retLim, "retrieval")) as RetrievalTier,
      parallel: Number(parallel) || 1,
      codingTier: String(src.coding_tier || meta.coding_tier || ""),
      codingHarness: Boolean(src.coding_harness ?? meta.coding_harness),
      workspaceIndexWaitReady: Boolean(
        src.workspace_index_wait_ready ?? meta.workspace_index_wait_ready,
      ),
      frozen: true as const,
    };
  }, [detail, liveRun, selectedId]);

  const displaySuites =
    paramsFromActiveRun?.suites ?? Array.from(selectedSuites);
  const displayContextTier = paramsFromActiveRun?.contextTier ?? contextTier;
  const displayRetrievalTier =
    paramsFromActiveRun?.retrievalTier ?? retrievalTier;
  const displayParallel = paramsFromActiveRun?.parallel ?? l1Parallel;
  const displayWaitReady =
    paramsFromActiveRun?.workspaceIndexWaitReady ?? workspaceIndexWaitReady;

  // Leaving a live run must detach SSE immediately — otherwise its logs keep
  // appending into the shared buffer while another (finished) run is selected.
  useEffect(() => {
    if (live.attachedRunId && selectedId !== live.attachedRunId) {
      detachLiveStream();
    }
    // Clear the live strip until an active run's SSE fills it.
    // Finished history must not re-hydrate this buffer (see loadDetail effect).
    resetLive();
    if (!selectedId) {
      historyDeepLinkDoneRef.current = false;
      setPagePane((p) => (p === "history" ? "live" : p));
      setPhaseHint("全过程：① 拉取（已有则跳过）→ ② 评测 → ③ 回归对比上次指标");
      setProgress({ done: 0, total: 0 });
    }
    // Stream methods are stable; selection is the intended reset trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  useEffect(() => {
    void (async () => {
      const body = await loadDetail();
      if (!body) return;
      if (isActiveStatus(body.status)) {
        historyDeepLinkDoneRef.current = true;
        setLastFinishedLiveId(null);
        setPagePane((p) => (p === "summary" ? p : "live"));
        applyRunSnapshot(body, { logs: false });
        // SSE replays in-memory history; only clear if this is a fresh attach.
        attachLiveStream(body.id, {
          resetLogs: live.attachedRunId !== body.id,
        });
      } else {
        // Finished / history: never dump logs into the 本轮 live strip.
        if (live.attachedRunId) detachLiveStream();
        // Deep-link / refresh onto a finished id → 历史 once.
        // After a live finish, stay on 本轮 (handoff banner); explicit 历史 click sets pane itself.
        if (!historyDeepLinkDoneRef.current) {
          historyDeepLinkDoneRef.current = true;
          setPagePane((p) => (p === "summary" ? p : "history"));
        }
      }
    })();
    // Loading a selected run is the trigger; the hook methods are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadDetail, applyRunSnapshot, attachLiveStream]);

  useEffect(() => {
    const box = logBoxRef.current;
    if (!box) return;
    // Only scroll the log pane — never scrollIntoView (that moves the whole page).
    box.scrollTop = box.scrollHeight;
  }, [liveLogs]);


  // Tick wall clock while a run is live so elapsed / ETA update.
  useEffect(() => {
    if (!busy) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [busy]);

  const applyPreset = (p: Preset) => {
    setSelectedSuites(suitesFromTargets(p.targets || []));
    setCodingTier(p.coding_tier || "n5");
    if (p.coding_n_instances != null) setCodingNInstances(p.coding_n_instances);
    setCodingCheckoutRepo(true);
    setRetrievalProd(p.retrieval_prod !== false);
    if (p.context_tier) setContextTier(p.context_tier);
    if (p.retrieval_tier) setRetrievalTier(p.retrieval_tier);
    if (p.l1_max_parallel != null) setL1Parallel(p.l1_max_parallel);
    setActiveProfileId(p.id);
    setProfileFormOpen(true);
  };

  const markCustomProfile = () => {
    setActiveProfileId(CUSTOM_PROFILE_ID);
    setProfileFormOpen(true);
  };

  const selectCustomProfile = () => {
    setActiveProfileId(CUSTOM_PROFILE_ID);
    setProfileFormOpen(true);
  };

  const profileButtons = (presets.length ? presets : L1_RUN_PROFILES).filter(
    (p) =>
      p.id !== "p1_lexical_micro" &&
      p.id !== "scifact_micro_l1" &&
      !(p.targets || []).includes("p1_lexical_micro"),
  );
  const activeProfileLabel =
    activeProfileId === CUSTOM_PROFILE_ID
      ? "自定义"
      : profileButtons.find((p) => p.id === activeProfileId)?.label || "自定义";
  const activeProfileHint =
    activeProfileId === CUSTOM_PROFILE_ID
      ? "在下方表单改参数；不再绑定预设档。"
      : profileButtons.find((p) => p.id === activeProfileId)?.hint || "";

  const toggleSuite = (id: SuiteId) => {
    if (!targetEnabled(id)) return;
    markCustomProfile();
    setSelectedSuites((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const startRun = async (opts?: {
    force?: boolean;
    suites?: SuiteId[];
    coding_tier?: string;
    coding_n_instances?: number | null;
    coding_harness?: boolean;
    retrieval_prod?: boolean;
    workspace_index_wait_ready?: boolean;
  }) => {
    const suites = (opts?.suites ?? Array.from(selectedSuites)).filter((s) =>
      targetEnabled(s),
    ) as SuiteId[];
    const apiTargets = suites.map((s) => (s === "coding" ? "coding" : s));
    if (apiTargets.length === 0) return;
    if (busy && !opts?.force) return;
    const tier = opts?.coding_tier ?? codingTier;
    const nInst =
      opts?.coding_n_instances ?? (tier === "custom" ? codingNInstances : null);
    // Coding always runs official SWE harness (API also forces this).
    const harness = suites.includes("coding");
    const prod = opts?.retrieval_prod ?? retrievalProd;
    const waitReady =
      opts?.workspace_index_wait_ready ?? workspaceIndexWaitReady;
    if (
      suites.includes("coding") &&
      tier === "custom" &&
      (nInst == null || nInst < 3)
    ) {
      setError("自定义编码档位需要 N ≥ 3（且 ≤ 300）");
      return;
    }
    if (suites.includes("coding") && tier === "full300") {
      const ok = window.confirm(
        "全量 SWE-bench Lite（300 题）耗时长、负载大。确认以 full300 启动？",
      );
      if (!ok) return;
    }
    const needModel =
      suites.includes("context") ||
      suites.includes("coding") ||
      suites.includes("retrieval") ||
      suites.includes("retrieval_zh");
    const hasKey = Boolean(
      modelApiKey.trim() && modelName.trim() && modelProvider.trim(),
    );
    if (needModel && !hasKey) {
      const onlyRet =
        (suites.includes("retrieval") || suites.includes("retrieval_zh")) &&
        !suites.includes("context") &&
        !suites.includes("coding");
      setError(
        onlyRet
          ? "L1 检索需走真实 Turn：请填写下方评测模型（供应商 / model / api_key）并点保存。"
          : "已选套件需评测模型：请填写下方评测模型（供应商 / model / api_key）。",
      );
      return;
    }
    let modelPayload:
      | {
          provider: string;
          api_style: ApiStyle;
          model_name: string;
          api_key: string;
          base_url?: string;
          context_window_tokens?: number;
        }
      | undefined;
    if (needModel && hasKey) {
      const cw = Number(modelContextWindow);
      const provider = modelProvider.trim() || "custom";
      modelPayload = {
        provider,
        api_style: inferApiStyle(provider, modelApiStyle),
        model_name: modelName.trim(),
        api_key: modelApiKey.trim(),
        base_url: modelBaseUrl.trim() || undefined,
        context_window_tokens:
          Number.isFinite(cw) && cw >= 1024 ? Math.floor(cw) : undefined,
      };
    }
    if (opts?.suites) {
      setSelectedSuites(new Set(suites));
      setCodingTier(tier);
      if (nInst != null) setCodingNInstances(nInst);
      setRetrievalProd(prod);
      setWorkspaceIndexWaitReady(waitReady);
    }
    setBusy(true);
    resetLive();
    setLastFinishedLiveId(null);
    setError(null);
    setTab("log");
    setPagePane("live");
    try {
      const resp = await fetch("/api/v1/ops/official/runs", {
        method: "POST",
        headers,
        body: JSON.stringify({
          targets: apiTargets,
          context_dry: false,
          coding_skip_api: false,
          coding_tier: tier,
          coding_n_instances: tier === "custom" ? nInst : null,
          coding_harness: harness,
          coding_checkout_repo: true,
          workspace_index_wait_ready: waitReady,
          retrieval_prod: prod,
          eval_path: "agent",
          retrieval_arm: "free",
          context_arm: "free",
          context_limit: contextTier !== "full" ? Number(contextTier) : 0,
          retrieval_query_limit:
            retrievalTier === "scifact_micro"
              ? 20
              : retrievalTier !== "full"
                ? Number(retrievalTier)
                : 0,
          l1_max_parallel: l1Parallel,
          retrieval_datasets:
            retrievalTier === "scifact_micro" ? ["scifact"] : [],
          retrieval_corpus_mode:
            retrievalTier === "scifact_micro" ? "micro" : "full",
          force: Boolean(opts?.force),
          model: modelPayload ?? null,
        }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        const msg = opsApiErrorText(text, text || `HTTP ${resp.status}`);
        if (
          String(msg).includes("official_run_already_active") &&
          !opts?.force
        ) {
          setError(
            "已有 Bench 在跑（或上次未干净结束）。可点右上角「取消」，或点「强制重开」。",
          );
          setBusy(false);
          return;
        }
        throw new Error(msg);
      }
      const created = (await resp.json()) as OfficialRun;
      setProgress({
        done: 0,
        total: created.progress_total || apiTargets.length,
      });
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
    setPhaseHint("正在停止…");
    setSuiteDetails({ _: { kind: "idle", label: "正在停止…", pct: null } });
    const resp = await fetch(`/api/v1/ops/official/runs/${id}/stop`, {
      method: "POST",
      headers,
    });
    if (!resp.ok) {
      const text = await resp.text();
      setError(opsApiErrorText(text, text || `停止失败 HTTP ${resp.status}`));
    } else {
      // Live SSE may still deliver run_finished; DB-only cancel won't.
      const body = (await resp.json().catch(() => null)) as OfficialRun | null;
      if (body?.phase_hint) {
        setPhaseHint(cleanPhase(body.phase_hint));
      }
      if (body && !isActiveStatus(body.status)) {
        setBusy(false);
        setLastFinishedLiveId(id);
        resetLive();
        setPhaseHint(
          "全过程：① 拉取（已有则跳过）→ ② 评测 → ③ 回归对比上次指标",
        );
        setProgress({ done: 0, total: 0 });
        navigate(opsOfficialPath(secret), { replace: true });
      } else {
        // Force UI out of infinite「正在停止…」even if SSE is wedged.
        window.setTimeout(() => {
          void (async () => {
            const latest = await loadDetail();
            if (!latest || !isActiveStatus(latest.status)) {
              setBusy(false);
              setLastFinishedLiveId(id);
              resetLive();
              setPhaseHint(
                "全过程：① 拉取（已有则跳过）→ ② 评测 → ③ 回归对比上次指标",
              );
              navigate(opsOfficialPath(secret), { replace: true });
              return;
            }
            setBusy(false);
            setPhaseHint("停止超时 — 可强制重开");
            setSuiteDetails({
              _: { kind: "idle", label: "停止超时", pct: null },
            });
            setError("停止超过约 8s 仍未终态。可刷新或点「强制重开」。");
            await loadList();
          })();
        }, 8000);
      }
    }
    await loadList();
  };

  const deleteHistory = async (opts: {
    ids?: string[];
    before?: string;
    force?: boolean;
    confirmLabel: string;
  }) => {
    if (clearingHistory) return;
    const ok = window.confirm(opts.confirmLabel);
    if (!ok) return;
    setClearingHistory(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/ops/official/runs/delete", {
        method: "POST",
        headers,
        body: JSON.stringify({
          ids: opts.ids ?? [],
          before: opts.before ?? null,
          include_filesystem: true,
          force: Boolean(opts.force),
        }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(opsApiErrorText(text, text || `HTTP ${resp.status}`));
      }
      const deletedIds = new Set(opts.ids || []);
      const wipeAll = !opts.ids?.length && !opts.before;
      if (wipeAll || (selectedId && deletedIds.has(selectedId))) {
        detachLiveStream();
        setDetail(null);
        resetLive(true);
        if (selectedId) {
          navigate(opsOfficialPath(secret), { replace: true });
        }
      } else if (opts.before && selectedId) {
        const sel = runs.find((r) => r.id === selectedId);
        if (sel?.created_at) {
          const cut = Date.parse(opts.before);
          const created = Date.parse(sel.created_at);
          if (
            Number.isFinite(cut) &&
            Number.isFinite(created) &&
            created < cut
          ) {
            detachLiveStream();
            setDetail(null);
            navigate(opsOfficialPath(secret), { replace: true });
          }
        }
      }
      setCheckedRunIds(new Set());
      if (wipeAll) setHistorySelectMode(false);
      await loadList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setClearingHistory(false);
    }
  };

  const clearHistory = async () => {
    if (runs.length === 0) return;
    const hasActive = runs.some((r) => isActiveStatus(r.status));
    await deleteHistory({
      force: hasActive,
      confirmLabel: hasActive
        ? `清空全部 Bench 历史（约 ${runs.length} 条）？\n含进行中的任务会先强制停止再删。\n保留 BEIR/LongBench 数据缓存。`
        : `清空全部 Bench 历史（约 ${runs.length} 条）？\n会删除数据库记录与报告目录，保留 BEIR/LongBench 数据缓存。`,
    });
  };

  const deleteSelectedHistory = async () => {
    const ids = Array.from(checkedRunIds);
    if (ids.length === 0) return;
    const hasActive = runs.some(
      (r) => checkedRunIds.has(r.id) && isActiveStatus(r.status),
    );
    await deleteHistory({
      ids,
      force: hasActive,
      confirmLabel: `删除选中的 ${ids.length} 条历史？${
        hasActive ? "\n含进行中的会先强制停止。" : ""
      }`,
    });
  };

  const clearHistoryBefore = async (hoursAgo: number, label: string) => {
    const before = new Date(Date.now() - hoursAgo * 3600 * 1000).toISOString();
    const n = runs.filter((r) => {
      if (!r.created_at) return false;
      const t = Date.parse(r.created_at);
      return Number.isFinite(t) && t < Date.parse(before);
    }).length;
    if (n === 0) {
      setError(`没有早于「${label}」的历史可删`);
      return;
    }
    const hasActive = runs.some((r) => {
      if (!isActiveStatus(r.status) || !r.created_at) return false;
      const t = Date.parse(r.created_at);
      return Number.isFinite(t) && t < Date.parse(before);
    });
    await deleteHistory({
      before,
      force: hasActive,
      confirmLabel: `删除「${label}」之前的约 ${n} 条历史？${
        hasActive ? "\n含进行中的会先强制停止。" : ""
      }`,
    });
  };

  const toggleCheckedRun = (id: string) => {
    setCheckedRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const rerunFrom = async (r: OfficialRun) => {
    const suites = suitesFromRun(r).filter((s) => targetEnabled(s));
    if (suites.length === 0) {
      setError("该记录没有可重跑的目标（或当前镜像不支持）。");
      return;
    }
    await startRun({
      force: true,
      suites,
      coding_tier: r.coding_tier ?? r.model_meta?.coding_tier ?? "n25",
      coding_n_instances:
        r.coding_n_instances ?? r.model_meta?.coding_n_instances ?? null,
      coding_harness: r.coding_harness ?? r.model_meta?.coding_harness ?? false,
      retrieval_prod: r.retrieval_prod ?? r.model_meta?.retrieval_prod ?? true,
      workspace_index_wait_ready: Boolean(
        r.workspace_index_wait_ready ??
          r.model_meta?.workspace_index_wait_ready ??
          false,
      ),
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
      ? Math.max(4, Math.round(suitePct * 0.35 + detailPct * 0.65))
      : suitePct || (busy ? 4 : 0);

  // Live SSE feeds liveLogItems; detail.logs stays stale until suite/run finish refresh.
  // Tab keeps errors + milestones only; the scrolling pane keeps the full stream.
  const logTabItems = useMemo(() => {
    const raw =
      busy && liveLogItems.length > 0 ? liveLogItems : detail?.logs || [];
    return raw.filter(isOpsKeyLogItem);
  }, [busy, liveLogItems, detail?.logs]);

  const suitesRemaining =
    progress.total > 0 ? Math.max(0, progress.total - progress.done) : null;
  const currentSuiteNo =
    progress.total > 0 && busy
      ? Math.min(
          progress.total,
          progress.done + (suitesRemaining && suitesRemaining > 0 ? 1 : 0),
        )
      : null;
  const activeSuiteName = detailProgress.suiteKey
    ? SUITE_DETAIL_LABEL[detailProgress.suiteKey] || detailProgress.suiteKey
    : null;
  // Prefer live suite over the coarse backend "② L1 评测中…" strip.
  const displayPhaseHint =
    busy && activeSuiteName && detailProgress.kind === "eval"
      ? `② L1 评测 · ${activeSuiteName}中…`
      : phaseHint;
  // L1 pipeline suites = retrieval / context / coding (at most 3), NOT BEIR datasets / queries.
  const suiteProgressLabel =
    progress.total > 0
      ? busy && suitesRemaining != null && suitesRemaining > 0
        ? `L1套件 ${progress.done}/${progress.total}` +
          (activeSuiteName
            ? ` · 进行中：${activeSuiteName}`
            : ` · 进行中第 ${currentSuiteNo} 套`)
        : `L1套件 ${progress.done}/${progress.total}`
      : null;
  const itemsRemainLabel =
    detailProgress.remain != null && detailProgress.unit
      ? busy && (detailProgress.done ?? 0) < (detailProgress.total ?? 0)
        ? `${activeSuiteName || "套内"} 已完成 ${detailProgress.done ?? 0}/${detailProgress.total ?? "?"} · 进行中`
        : `${activeSuiteName || "套内"} ${detailProgress.done ?? 0}/${detailProgress.total ?? "?"} · 剩 ${detailProgress.remain} ${detailProgress.unit}`
      : null;
  const remainLabel = (() => {
    const parts: string[] = [];
    if (itemsRemainLabel) parts.push(itemsRemainLabel);
    if (suiteProgressLabel) parts.push(suiteProgressLabel);
    return parts.length ? parts.join(" · ") : null;
  })();

  const runStartedAt = detail?.created_at || null;
  const runFinishedAt = busy ? null : detail?.finished_at || null;
  const elapsedSec = elapsedSeconds(runStartedAt, runFinishedAt, nowMs);
  const timingLabel = (() => {
    if (elapsedSec == null) return null;
    if (busy) {
      const rem = remainLabel ? ` · ${remainLabel}` : "";
      return `已用 ${formatDuration(elapsedSec)}${rem}`;
    }
    if (runFinishedAt) return `用时 ${formatDuration(elapsedSec)}`;
    return `已用 ${formatDuration(elapsedSec)}`;
  })();

  const filteredRuns = useMemo(() => {
    if (!suiteFilter) return runs;
    return runs.filter((r) =>
      (r.official_suite || r.model_meta?.official_suite || "").includes(
        suiteFilter,
      ),
    );
  }, [runs, suiteFilter]);

  /** History list keeps all statuses; aggregates only completed (+ effect-eligible). */
  const summaryRuns = useMemo(
    () => filteredRuns.filter((r) => isEffectEligible(r)),
    [filteredRuns],
  );

  const metricAggs = useMemo(
    () => aggregateMetrics(summaryRuns),
    [summaryRuns],
  );
  const scoredRunCount = useMemo(
    () =>
      summaryRuns.filter((r) => Object.keys(runMetrics(r)).length > 0).length,
    [summaryRuns],
  );

  const detailMetrics = runMetrics(detail);

  const goLivePane = () => {
    setPagePane("live");
    const selIsLive =
      (liveRun && liveRun.id === selectedId) ||
      (detail && selectedId === detail.id && isActiveStatus(detail.status));
    if (selectedId && !selIsLive && !busy) {
      navigate(opsOfficialPath(secret), { replace: true });
      setLastFinishedLiveId(null);
    }
  };

  const goHistoryPane = () => {
    historyDeepLinkDoneRef.current = true;
    setPagePane("history");
  };

  return (
    <OpsShell
      wide
      secret={secret}
      title="Bench"
      subtitle="BEIR · LongBench · SWE-bench Lite · 指标与过程"
      actions={
        <>
          <div className="flex rounded-md border border-border p-0.5 text-xs">
            <button
              type="button"
              onClick={goLivePane}
              className={`rounded px-2.5 py-1 ${
                pagePane === "live"
                  ? "bg-foreground text-background"
                  : "hover:bg-muted"
              }`}
            >
              本轮
            </button>
            <button
              type="button"
              onClick={goHistoryPane}
              className={`rounded px-2.5 py-1 ${
                pagePane === "history"
                  ? "bg-foreground text-background"
                  : "hover:bg-muted"
              }`}
            >
              历史
              {filteredRuns.length > 0 ? (
                <span className="ml-1 tabular-nums opacity-70">
                  ({filteredRuns.length})
                </span>
              ) : null}
            </button>
            <button
              type="button"
              onClick={() => setPagePane("summary")}
              className={`rounded px-2.5 py-1 ${
                pagePane === "summary"
                  ? "bg-foreground text-background"
                  : "hover:bg-muted"
              }`}
            >
              指标汇总
            </button>
          </div>
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
          {opsDisplayText(error)?.includes("已有 Bench") ? (
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
          {opsDisplayText(error)}
        </p>
      ) : null}

      {showCriteria ? (
        <section className="mb-5 space-y-4">
          {BENCH_SCENARIO_GROUPS.map((group) => {
            const items = criteria.filter((c) => {
              const id = String(c.id || "");
              if (group.suiteIds.length === 0) return false;
              return group.suiteIds.some(
                (sid) => id === sid || id.startsWith(`${sid}`),
              );
            });
            // Fallback: map known criterion ids when API uses suite names
            const mapped =
              items.length > 0
                ? items
                : criteria.filter((c) =>
                    group.suiteIds.includes(c.id as SuiteId),
                  );
            if (mapped.length === 0 && group.suiteIds.length === 0) {
              return (
                <div key={group.id}>
                  <div className="mb-2 flex flex-wrap items-baseline gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {group.label}
                    </h3>
                    <span className="text-[11px] text-muted-foreground">
                      {group.hint}
                    </span>
                  </div>
                  <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                    尚无挂接的官方套件（产品主栏 Closed-Loop Suite 规划中）。
                  </p>
                </div>
              );
            }
            if (mapped.length === 0) return null;
            return (
              <div key={group.id}>
                <div className="mb-2 flex flex-wrap items-baseline gap-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {group.label}
                  </h3>
                  <span className="text-[11px] text-muted-foreground">
                    {group.hint}
                  </span>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  {mapped.map((c) => (
                    <article
                      key={c.id}
                      className="rounded-lg border border-border bg-card/50 p-3 text-xs"
                    >
                      <h3 className="font-semibold tracking-tight">
                        {c.title}
                      </h3>
                      <p className="mt-0.5 text-muted-foreground">
                        {c.official}
                      </p>
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
                </div>
              </div>
            );
          })}
          {/* Any criterion not mapped to a known scenario group */}
          {(() => {
            const known = new Set(
              BENCH_SCENARIO_GROUPS.flatMap((g) => [...g.suiteIds]),
            );
            const orphan = criteria.filter((c) => !known.has(c.id as SuiteId));
            if (orphan.length === 0) return null;
            return (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  其他
                </h3>
                <div className="grid gap-3 md:grid-cols-3">
                  {orphan.map((c) => (
                    <article
                      key={c.id}
                      className="rounded-lg border border-border bg-card/50 p-3 text-xs"
                    >
                      <h3 className="font-semibold tracking-tight">
                        {c.title}
                      </h3>
                      <p className="mt-0.5 text-muted-foreground">
                        {c.official}
                      </p>
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
                </div>
              </div>
            );
          })()}
        </section>
      ) : null}

      {pagePane === "live" ? (
        <LivePane model={{
          busy, selectedSuites, targetEnabled, startRun, error, opsDisplayText,
          profileButtons, activeProfileId, profileFormOpen, setProfileFormOpen,
          applyPreset, selectCustomProfile, CUSTOM_PROFILE_ID, activeProfileLabel,
          activeProfileHint, suitesLabelZh, displaySuites, paramsFromActiveRun,
          codingTier, codingNInstances, setCodingNInstances, retrievalTierLabel, displayRetrievalTier,
          contextTierLabel, displayContextTier, displayParallel, BENCH_SCENARIO_GROUPS,
          targetsMeta, FALLBACK_SUITE_META, markCustomProfile,
          toggleSuite, retrievalTier, setRetrievalTier, contextTier, setContextTier,
          l1Parallel, setL1Parallel, codingTierMeta, setCodingTier,
          workspaceIndexWaitReady, setWorkspaceIndexWaitReady, displayWaitReady,
          caps,
          needsLiveModel, modelProvider, applyProviderPreset, PROVIDER_PRESETS,
          modelApiStyle, setModelApiStyle, modelName, setModelName, modelBaseUrl,
          setModelBaseUrl, apiKeySaveFlash, apiKeyStored, apiKeyEditing, setApiKeyEditing, apiKeyDirty,
          storedApiKey, modelApiKey, setModelApiKey, clearApiKey, saveApiKey,
          modelContextWindow, setModelContextWindow, probeBusy, probeModel,
          probeMessage, probeOk, lastFinishedLiveId, shortId, historyDeepLinkDoneRef,
          setPagePane, navigate, opsOfficialPath, secret, setLastFinishedLiveId,
          selectedId, liveRun, runSuitesLabel, displayPhaseHint, timingLabel,
          detailProgress, detailPct, suiteProgressLabel, progress, itemsRemainLabel,
          suitePct, barPct, codingRows, codingSummary, HARNESS_STAGE_LABEL,
          shortCaseToken, astIndexRows, astIndexSummary, astIndexExpanded,
          setAstIndexExpanded, ChevronUp, ChevronDown, logBoxRef, liveLogs,
          liveLogLineClass, OfficialLogLine, nowMs, formatDuration,
        }} />
      ) : pagePane === "history" ? (
        <HistoryPane model={{
          filteredRuns, runs, historySelectMode, setHistorySelectMode,
          setCheckedRunIds, checkedRunIds, clearingHistory, deleteSelectedHistory,
          clearHistory, clearHistoryBefore, loadList, selectedId, loadDetail,
          shortId, toggleCheckedRun, runMetrics, historyHeadlineMetric,
          elapsedSeconds, isActiveStatus, nowMs, setPagePane,
          historyDeepLinkDoneRef, navigate, opsOfficialPath, secret,
          runSuitesLabel, statusClass, formatTime, formatDuration, detail,
          elapsedSec, busy, remainLabel, targetEnabled, rerunFrom,
          openAuthorizedHtml, setError, opsDisplayText, downloadAuthorizedFile,
          opsRunPath, tab, setTab, MetricBars, detailMetrics, ArtifactsPanel,
          artifacts, artifactsLoading, artifactsError, logTabItems,
          isOpsErrorLogLine,
        }} />
      ) : (
        <SummaryPane model={{ scoredRunCount, suiteFilter, setSuiteFilter, metricAggs }} />
      )}
    </OpsShell>
  );
}
