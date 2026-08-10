import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { opsDisplayText } from "./opsDisplayText";

type Locale = "zh" | "en";

const LOCALE_KEY = "ops.overview.locale";

type Overview = {
  agent?: {
    container?: string;
    status?: string | null;
    source?: string;
    embedding_backend?: string | null;
    embedding_model?: string | null;
    retrieval_mode?: string | null;
    retrieval_backend?: string | null;
    app_env?: string | null;
    usage?: {
      users_total?: number;
      users_active?: number;
      works_total?: number;
      sessions_active?: number;
      sessions_updated_24h?: number;
      turns_24h?: number;
      model_profiles_total?: number;
      model_profiles_active?: number;
      users_with_active_model?: number;
      active_providers?: Array<{ provider: string; count: number }>;
      error?: string;
    };
  };
  bench?: {
    container?: string;
    status?: string | null;
    healthy?: boolean;
    retrieval_backend?: string;
    retrieval_model?: string;
    bench_model_api_key_configured?: boolean;
    data_dir?: string;
    caps?: {
      sentence_transformers?: boolean;
      retrieval_prod?: boolean;
    };
  };
  host?: {
    hostname?: string;
    cpu_count?: number | null;
    memory_total_mb?: number | null;
    memory_available_mb?: number | null;
    virt?: {
      kind?: string;
      cpu_model?: string | null;
      label?: string;
    };
    loadavg?: {
      load_1?: number | null;
      load_5?: number | null;
      load_15?: number | null;
    };
    disks?: Array<{
      path: string;
      source?: string | null;
      fstype?: string | null;
      total_mb?: number;
      used_mb?: number;
      available_mb?: number;
      used_pct?: number | null;
    }>;
    docker?: {
      available?: boolean;
      server_version?: string;
      containers_running?: number;
      containers_total?: number;
    };
  };
  containers?: {
    available?: boolean;
    count_running?: number;
    count_listed?: number;
    error?: string;
    hint?: string;
    items?: Array<{
      id?: string | null;
      name: string;
      image?: string | null;
      status: string;
      ports?: string;
      created?: string;
      cpu_pct?: number | null;
      mem_usage_mib?: number | null;
      mem_limit_mib?: number | null;
      mem_pct?: number | null;
      mem_usage_raw?: string | null;
    }>;
  };
};

type BrowserBenchModel = {
  v?: number;
  provider?: string;
  api_style?: string;
  model_name?: string;
  base_url?: string;
  api_key?: string;
  remember_api_key?: boolean;
  suites?: string[];
};

const COPY = {
  zh: {
    title: "配置概览",
    poll: "15s 刷新",
    refresh: "刷新",
    close: "关闭",
    closeAria: "关闭配置概览",
    panelAria: "评测台配置概览",
    httpError: (n: number) => `概览 HTTP ${n}`,
    secRuntime: "1. 运行时",
    secBench: "2. 评测台",
    secHost: "3. 主机",
    secContainers: "4. 容器",
    container: "容器",
    status: "状态",
    users: "用户",
    works: "Works",
    sessions: "会话",
    sessions24h: "会话 24h",
    turns24h: "回合 24h",
    modelProfiles: "模型档案",
    profilesFmt: (users: number, active: number) => `${users} 用户 · ${active} 启用`,
    providers: "供应商",
    retrievalBackend: "检索后端",
    retrievalMode: "检索模式",
    embeddingModel: "向量模型",
    embeddingBackend: "嵌入后端",
    inspectUnavailable: "无法 inspect runtime · make up-ops-eval",
    health: "健康",
    healthOk: "正常",
    healthDown: "异常",
    stReady: "ST 就绪",
    retrievalProd: "真向量",
    modelApiKey: "环境 API Key",
    dataDir: "数据目录",
    browserPrefs: "浏览器评测模型",
    unset: "未配置",
    set: "已保存",
    inspectHint: "容器状态需 make up-ops-eval（挂 docker.sock）",
    envKeyHint: "指 .env 的 BENCH_MODEL_API_KEY；页面里配的 Key 见下方「浏览器评测模型」",
    provider: "供应商",
    apiStyle: "API 协议",
    model: "模型",
    baseUrl: "Base URL",
    apiKey: "API Key",
    suites: "套件",
    hostname: "主机名",
    virt: "虚拟化",
    cpu: "CPU",
    vcpu: "逻辑核",
    loadAvg: "平均负载",
    memory: "内存",
    memFmt: (free: string, total: string) => `${free} 可用 / ${total}`,
    docker: "Docker",
    dockerContainers: "容器数",
    dockerFmt: (up: number, total: string | number) => `${up} 运行 / ${total}`,
    mounts: "挂载",
    free: "可用",
    containersUnavailable: "不可用",
    containersSummary: (running: number, listed: number) =>
      `${running} 运行 · ${listed} 列出`,
    yes: "是",
    no: "否",
    virtKind: {
      wsl: "WSL2",
      "wsl+container": "WSL2 / 容器",
      vm: "虚拟机",
      "vm+container": "虚拟机 / 容器",
      container: "容器",
      bare_metal: "物理机",
    } as Record<string, string>,
  },
  en: {
    title: "Overview",
    poll: "15s poll",
    refresh: "Refresh",
    close: "Close",
    closeAria: "Close overview",
    panelAria: "Ops overview",
    httpError: (n: number) => `Overview HTTP ${n}`,
    secRuntime: "1. Runtime",
    secBench: "2. Bench",
    secHost: "3. Host",
    secContainers: "4. Containers",
    container: "Container",
    status: "Status",
    users: "Users",
    works: "Works",
    sessions: "Sessions",
    sessions24h: "Sessions 24h",
    turns24h: "Turns 24h",
    modelProfiles: "Model profiles",
    profilesFmt: (users: number, active: number) =>
      `${users} users · ${active} active`,
    providers: "Providers",
    retrievalBackend: "Retrieval backend",
    retrievalMode: "Retrieval mode",
    embeddingModel: "Embedding model",
    embeddingBackend: "Embedding backend",
    inspectUnavailable: "runtime inspect unavailable · make up-ops-eval",
    health: "Health",
    healthOk: "ok",
    healthDown: "down",
    stReady: "sentence-transformers",
    retrievalProd: "retrieval_prod",
    modelApiKey: "Env API key",
    dataDir: "DATA_DIR",
    browserPrefs: "Browser model prefs",
    unset: "unset",
    set: "set",
    inspectHint: "Container status needs make up-ops-eval (docker.sock)",
    envKeyHint: "BENCH_MODEL_API_KEY in .env — browser keys are under Browser model prefs",
    provider: "provider",
    apiStyle: "API style",
    model: "model",
    baseUrl: "base_url",
    apiKey: "api_key",
    suites: "suites",
    hostname: "Hostname",
    virt: "Virt",
    cpu: "CPU",
    vcpu: "vCPU",
    loadAvg: "Load average",
    memory: "Memory",
    memFmt: (free: string, total: string) => `${free} free / ${total}`,
    docker: "Docker",
    dockerContainers: "Containers",
    dockerFmt: (up: number, total: string | number) => `${up} up / ${total}`,
    mounts: "Mounts",
    free: "free",
    containersUnavailable: "unavailable",
    containersSummary: (running: number, listed: number) =>
      `${running} running · ${listed} listed`,
    yes: "yes",
    no: "no",
    virtKind: {
      wsl: "WSL2",
      "wsl+container": "WSL2 / container",
      vm: "VM",
      "vm+container": "VM / container",
      container: "container",
      bare_metal: "bare metal",
    } as Record<string, string>,
  },
} as const;

function readLocale(): Locale {
  try {
    const v = localStorage.getItem(LOCALE_KEY);
    if (v === "en" || v === "zh") return v;
  } catch {
    /* ignore */
  }
  return "zh";
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-x-2 gap-y-0.5 text-[11px] leading-snug">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-all font-medium text-foreground">{value ?? "—"}</dd>
    </div>
  );
}

type OverviewCopy = (typeof COPY)[Locale];

function yn(
  v: boolean | null | undefined,
  t: Pick<OverviewCopy, "yes" | "no">,
): string {
  if (v === true) return t.yes;
  if (v === false) return t.no;
  return "—";
}

function fmtLoad(host: Overview["host"]): string {
  const l = host?.loadavg;
  if (!l || l.load_1 == null) return "—";
  return [l.load_1, l.load_5, l.load_15]
    .map((n) => (n == null ? "—" : n.toFixed(2)))
    .join(" / ");
}

function fmtMb(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v >= 1024) return `${(v / 1024).toFixed(2)} GiB`;
  return `${Math.round(v)} MiB`;
}

function readBrowserBench(): BrowserBenchModel {
  try {
    const raw = localStorage.getItem("ops.bench.prefs");
    if (!raw) return {};
    const saved = JSON.parse(raw) as BrowserBenchModel;
    const hasKey = Boolean(saved.api_key);
    if ((saved.v ?? 0) < 2 && !hasKey) {
      return { suites: saved.suites };
    }
    return saved;
  } catch {
    return {};
  }
}

function browserModelConfigured(b: BrowserBenchModel): boolean {
  return Boolean(b.provider || b.model_name || b.api_key);
}

export function OpsOverviewSidebar({
  secret,
  open,
  onClose,
}: {
  secret: string;
  open: boolean;
  onClose: () => void;
}) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [browser, setBrowser] = useState<BrowserBenchModel>({});
  const [locale, setLocale] = useState<Locale>(() => readLocale());

  const t = useMemo(() => COPY[locale], [locale]);

  const setLocalePersist = useCallback((next: Locale) => {
    setLocale(next);
    try {
      localStorage.setItem(LOCALE_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  const load = useCallback(async () => {
    if (!secret) return;
    setLoading(true);
    setError(null);
    setBrowser(readBrowserBench());
    try {
      const resp = await fetch("/api/v1/ops/eval/overview", {
        headers: { Authorization: `Bearer ${secret}`, Accept: "application/json" },
      });
      if (!resp.ok) {
        setError(COPY[locale].httpError(resp.status));
        return;
      }
      setData((await resp.json()) as Overview);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [secret, locale]);

  useEffect(() => {
    if (!open) return;
    void load();
    const id = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(id);
  }, [open, load]);

  if (!open) return null;

  const agent = data?.agent;
  const bench = data?.bench;
  const host = data?.host;
  const containers = data?.containers;
  const virtLabel =
    (host?.virt?.kind && t.virtKind[host.virt.kind]) || host?.virt?.label || "—";

  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-40 bg-black/30 lg:bg-transparent"
        aria-label={t.closeAria}
        onClick={onClose}
      />
      <aside
        className="fixed inset-y-0 right-0 z-50 flex w-[min(100vw,22rem)] flex-col border-l border-border bg-background shadow-xl"
        aria-label={t.panelAria}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5">
          <div className="min-w-0">
            <p className="text-sm font-semibold">{t.title}</p>
            <p className="text-[10px] text-muted-foreground">{t.poll}</p>
          </div>
          <div className="flex shrink-0 gap-1.5">
            <div
              className="flex overflow-hidden rounded-md border border-border text-[11px]"
              role="group"
              aria-label="Language"
            >
              <button
                type="button"
                onClick={() => setLocalePersist("zh")}
                className={`px-1.5 py-1 ${
                  locale === "zh"
                    ? "bg-foreground/10 font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted"
                }`}
              >
                中文
              </button>
              <button
                type="button"
                onClick={() => setLocalePersist("en")}
                className={`px-1.5 py-1 ${
                  locale === "en"
                    ? "bg-foreground/10 font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted"
                }`}
              >
                EN
              </button>
            </div>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-md border border-border px-2 py-1 text-[11px] hover:bg-muted"
            >
              {loading ? "…" : t.refresh}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-border px-2 py-1 text-[11px] hover:bg-muted"
            >
              {t.close}
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          {error ? (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-xs">
              {opsDisplayText(error)}
            </p>
          ) : null}

          <section className="rounded-lg border border-border bg-card/40 p-2.5">
            <h3 className="mb-2 text-xs font-semibold tracking-tight">{t.secRuntime}</h3>
            <dl className="space-y-1.5">
              <Row label={t.container} value={agent?.container} />
              <Row label={t.status} value={agent?.status} />
              <Row
                label={t.users}
                value={
                  agent?.usage?.users_total != null
                    ? `${agent.usage.users_active ?? "—"} / ${agent.usage.users_total}`
                    : "—"
                }
              />
              <Row label={t.works} value={agent?.usage?.works_total ?? "—"} />
              <Row label={t.sessions} value={agent?.usage?.sessions_active ?? "—"} />
              <Row
                label={t.sessions24h}
                value={agent?.usage?.sessions_updated_24h ?? "—"}
              />
              <Row label={t.turns24h} value={agent?.usage?.turns_24h ?? "—"} />
              <Row
                label={t.modelProfiles}
                value={
                  agent?.usage?.users_with_active_model != null
                    ? t.profilesFmt(
                        agent.usage.users_with_active_model,
                        agent.usage.model_profiles_active ?? 0,
                      )
                    : "—"
                }
              />
              <Row
                label={t.providers}
                value={
                  (agent?.usage?.active_providers || [])
                    .map((p) => `${p.provider}×${p.count}`)
                    .join(" · ") || "—"
                }
              />
              {agent?.retrieval_backend ? (
                <Row label={t.retrievalBackend} value={agent.retrieval_backend} />
              ) : null}
              {agent?.retrieval_mode ? (
                <Row label={t.retrievalMode} value={agent.retrieval_mode} />
              ) : null}
              {agent?.embedding_model ? (
                <Row label={t.embeddingModel} value={agent.embedding_model} />
              ) : null}
              {agent?.embedding_backend ? (
                <Row label={t.embeddingBackend} value={agent.embedding_backend} />
              ) : null}
            </dl>
            {agent?.usage?.error ? (
              <p className="mt-1 text-[10px] text-destructive">
                {opsDisplayText(agent.usage.error)}
              </p>
            ) : null}
            {agent?.source === "unavailable" ? (
              <p className="mt-2 text-[10px] text-muted-foreground">
                {t.inspectUnavailable}
              </p>
            ) : null}
          </section>

          <section className="rounded-lg border border-border bg-card/40 p-2.5">
            <h3 className="mb-2 text-xs font-semibold tracking-tight">{t.secBench}</h3>
            <dl className="space-y-1.5">
              <Row label={t.container} value={bench?.container} />
              <Row
                label={t.status}
                value={bench?.status || "—"}
              />
              {!bench?.status ? (
                <p className="text-[10px] text-muted-foreground">{t.inspectHint}</p>
              ) : null}
              <Row
                label={t.health}
                value={bench?.healthy ? t.healthOk : t.healthDown}
              />
              <Row
                label={t.embeddingModel}
                value={bench?.retrieval_model || "—"}
              />
              <Row label={t.retrievalBackend} value={bench?.retrieval_backend} />
              <Row
                label={t.stReady}
                value={yn(bench?.caps?.sentence_transformers, t)}
              />
              <Row
                label={t.retrievalProd}
                value={yn(bench?.caps?.retrieval_prod, t)}
              />
              <Row
                label={t.modelApiKey}
                value={yn(bench?.bench_model_api_key_configured, t)}
              />
              <p className="text-[10px] text-muted-foreground">{t.envKeyHint}</p>
              <Row label={t.dataDir} value={bench?.data_dir} />
            </dl>
            <div className="mt-2 rounded-md border border-border/70 bg-background/70 px-2 py-1.5">
              <p className="mb-1 text-[10px] font-medium text-muted-foreground">
                {t.browserPrefs}
              </p>
              {!browserModelConfigured(browser) ? (
                <p className="text-[11px] text-muted-foreground">{t.unset}</p>
              ) : (
                <dl className="space-y-1">
                  <Row label={t.provider} value={browser.provider || "—"} />
                  <Row
                    label={t.apiStyle}
                    value={
                      browser.api_style === "anthropic"
                        ? "Anthropic"
                        : browser.api_style === "openai"
                          ? "OpenAI"
                          : browser.api_style || "—"
                    }
                  />
                  <Row label={t.model} value={browser.model_name || "—"} />
                  <Row label={t.baseUrl} value={browser.base_url || "—"} />
                  <Row
                    label={t.apiKey}
                    value={browser.api_key ? t.set : t.unset}
                  />
                  <Row
                    label={t.suites}
                    value={(browser.suites || []).join(" · ") || "—"}
                  />
                </dl>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-border bg-card/40 p-2.5">
            <h3 className="mb-2 text-xs font-semibold tracking-tight">{t.secHost}</h3>
            <dl className="space-y-1.5">
              <Row label={t.hostname} value={host?.hostname} />
              <Row label={t.virt} value={virtLabel} />
              <Row label={t.cpu} value={host?.virt?.cpu_model || "—"} />
              <Row label={t.vcpu} value={host?.cpu_count ?? "—"} />
              <Row label={t.loadAvg} value={fmtLoad(host)} />
              <Row
                label={t.memory}
                value={t.memFmt(
                  fmtMb(host?.memory_available_mb),
                  fmtMb(host?.memory_total_mb),
                )}
              />
              {host?.docker?.available ? (
                <>
                  <Row label={t.docker} value={host.docker.server_version} />
                  <Row
                    label={t.dockerContainers}
                    value={
                      host.docker.containers_running != null
                        ? t.dockerFmt(
                            host.docker.containers_running,
                            host.docker.containers_total ?? "?",
                          )
                        : "—"
                    }
                  />
                </>
              ) : null}
            </dl>
            {(host?.disks || []).length > 0 ? (
              <div className="mt-2 space-y-1.5">
                <p className="text-[10px] font-medium text-muted-foreground">
                  {t.mounts}
                </p>
                <ul className="space-y-1.5">
                  {(host?.disks || []).map((d) => (
                    <li
                      key={d.path}
                      className="rounded-md border border-border/60 bg-background/60 px-2 py-1.5 text-[10px]"
                    >
                      <div className="flex justify-between gap-2 font-medium text-[11px]">
                        <span>{d.path}</span>
                        <span>
                          {fmtMb(d.available_mb)} {t.free}
                          {d.used_pct != null ? ` · ${d.used_pct}%` : ""}
                        </span>
                      </div>
                      <div className="mt-0.5 text-muted-foreground">
                        {(d.source || "—") + (d.fstype ? ` · ${d.fstype}` : "")}
                        {" · "}
                        {fmtMb(d.used_mb)} / {fmtMb(d.total_mb)}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>

          <section className="rounded-lg border border-border bg-card/40 p-2.5">
            <h3 className="mb-2 text-xs font-semibold tracking-tight">
              {t.secContainers}
            </h3>
            {!containers?.available ? (
              <p className="text-[11px] text-muted-foreground">
                {opsDisplayText(
                  containers?.hint || containers?.error || t.containersUnavailable,
                )}
              </p>
            ) : (
              <>
                <p className="mb-2 text-[11px] text-muted-foreground">
                  {t.containersSummary(
                    containers.count_running ?? 0,
                    containers.count_listed ?? containers.items?.length ?? 0,
                  )}
                </p>
                <ul className="space-y-2">
                  {(containers.items || []).map((c) => (
                    <li
                      key={c.name}
                      className="rounded-md border border-border/60 bg-background/60 px-2 py-1.5"
                    >
                      <div className="flex items-start justify-between gap-2 text-[11px]">
                        <span className="font-medium">{c.name}</span>
                        <span className="shrink-0 text-right text-muted-foreground">
                          {c.status}
                        </span>
                      </div>
                      <div className="mt-1 space-y-0.5 text-[10px] text-muted-foreground">
                        <div className="truncate">
                          <span className="text-foreground/80">
                            {c.image || "—"}
                          </span>
                          {c.id ? ` · ${c.id}` : ""}
                        </div>
                        {c.ports ? (
                          <div className="break-all">PORTS {c.ports}</div>
                        ) : null}
                        {c.created ? <div>CREATED {c.created}</div> : null}
                        {c.cpu_pct != null || c.mem_usage_raw ? (
                          <div className="grid grid-cols-2 gap-1 pt-0.5">
                            <span>
                              CPU{" "}
                              <strong className="text-foreground">
                                {c.cpu_pct != null
                                  ? `${c.cpu_pct.toFixed(1)}%`
                                  : "—"}
                              </strong>
                            </span>
                            <span>
                              MEM{" "}
                              <strong className="text-foreground">
                                {c.mem_pct != null
                                  ? `${c.mem_pct.toFixed(1)}%`
                                  : c.mem_usage_raw || "—"}
                              </strong>
                            </span>
                            {c.mem_usage_mib != null ? (
                              <span className="col-span-2">
                                {fmtMb(c.mem_usage_mib)} / {fmtMb(c.mem_limit_mib)}
                              </span>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}
