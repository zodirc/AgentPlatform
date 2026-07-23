import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  OpsShell,
  opsHistoryPath,
  opsRunPath,
  secretFromOpsPath,
  statusClass,
} from "./OpsShell";

type EvalCase = {
  id: string;
  path: string;
  scenario_id: string;
  phase: string;
  tags: string[];
  description: string;
  model_mode?: string | null;
};

type CaseResult = {
  case_id: string;
  status: string;
  events: string[];
  error?: string | null;
  turn_id?: string | null;
};

type EvalRun = {
  id: string;
  status: string;
  suite?: string;
  mode: string;
  restart_runtime: boolean;
  restart_available?: boolean;
  proof_available?: boolean;
  cancel_requested?: boolean;
  cases: CaseResult[];
  error?: string | null;
};

type HistoryItem = {
  id: string;
  status: string;
  suite?: string;
  mode: string;
  created_at?: string | null;
  summary?: { pass?: number; fail?: number; total?: number };
};

type CiProofCase = {
  id: string;
  step: string;
  description: string;
};

type Mode = "stub" | "live";
type Suite = "golden" | "ci";

export function EvalConsolePage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const secret = secretFromOpsPath(pathname);
  const [authError, setAuthError] = useState<string | null>(null);
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [tagFilter, setTagFilter] = useState("");
  const [scenarioFilter, setScenarioFilter] = useState("");
  const [suite, setSuite] = useState<Suite>("ci");
  const [mode, setMode] = useState<Mode>("stub");
  const [provider, setProvider] = useState("deepseek");
  const [modelName, setModelName] = useState("deepseek-chat");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [restartRuntime, setRestartRuntime] = useState(false);
  const [restartAvailable, setRestartAvailable] = useState(false);
  const [proofAvailable, setProofAvailable] = useState(false);
  const [ciProofCases, setCiProofCases] = useState<CiProofCase[]>([]);
  const [run, setRun] = useState<EvalRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [recent, setRecent] = useState<HistoryItem[]>([]);

  const headers = useMemo(
    () => ({
      Authorization: `Bearer ${secret}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    }),
    [secret],
  );

  const loadMeta = useCallback(async () => {
    const resp = await fetch("/api/v1/ops/eval/meta", { headers });
    if (resp.status === 401 || resp.status === 403 || resp.status === 404) {
      setAuthError("无效密钥或评测台未启用");
      return false;
    }
    if (!resp.ok) {
      setAuthError(`无法加载元数据：HTTP ${resp.status}`);
      return false;
    }
    const data = (await resp.json()) as {
      restart_available?: boolean;
      proof_available?: boolean;
      ci_proof_cases?: CiProofCase[];
    };
    setRestartAvailable(Boolean(data.restart_available));
    setProofAvailable(Boolean(data.proof_available));
    setCiProofCases(data.ci_proof_cases || []);
    if (data.ci_proof_cases?.length) {
      setSelected(new Set(data.ci_proof_cases.map((c) => c.id)));
    }
    if (!data.proof_available) {
      setSuite("golden");
    }
    setAuthError(null);
    return true;
  }, [headers]);

  const loadCases = useCallback(async () => {
    const params = new URLSearchParams();
    if (scenarioFilter) params.set("scenario", scenarioFilter);
    if (tagFilter) params.set("tag", tagFilter);
    const qs = params.toString();
    const resp = await fetch(`/api/v1/ops/eval/cases${qs ? `?${qs}` : ""}`, { headers });
    if (resp.status === 401 || resp.status === 403 || resp.status === 404) {
      setAuthError("无效密钥或评测台未启用");
      return;
    }
    if (!resp.ok) {
      setAuthError(`无法加载用例：HTTP ${resp.status}`);
      return;
    }
    const data = (await resp.json()) as { cases: EvalCase[] };
    setCases(data.cases);
    setAuthError(null);
  }, [headers, scenarioFilter, tagFilter]);

  const loadRecent = useCallback(async () => {
    const resp = await fetch("/api/v1/ops/eval/runs?limit=8", { headers });
    if (!resp.ok) return;
    const data = (await resp.json()) as { runs: HistoryItem[] };
    setRecent(data.runs || []);
  }, [headers]);

  useEffect(() => {
    void (async () => {
      const ok = await loadMeta();
      if (ok) {
        await loadCases();
        await loadRecent();
      }
    })();
  }, [loadMeta, loadCases, loadRecent]);

  useEffect(() => {
    if (suite === "ci") {
      setSelected(new Set(ciProofCases.map((c) => c.id)));
    } else {
      setSelected(new Set(cases.map((c) => c.id)));
    }
    // Reset selection when switching suite (or when CI catalog first loads).
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: avoid wiping CI checks on golden case refresh
  }, [suite, ciProofCases]);

  const resultById = useMemo(() => {
    const map = new Map<string, CaseResult>();
    for (const c of run?.cases ?? []) map.set(c.case_id, c);
    return map;
  }, [run]);

  const toggleAll = (on: boolean) => {
    if (suite === "ci") {
      setSelected(on ? new Set(ciProofCases.map((c) => c.id)) : new Set());
    } else {
      setSelected(on ? new Set(cases.map((c) => c.id)) : new Set());
    }
  };

  const refreshRun = async (runId: string) => {
    const resp = await fetch(`/api/v1/ops/eval/runs/${runId}`, { headers });
    if (!resp.ok) return;
    setRun((await resp.json()) as EvalRun);
  };

  const stopRun = async () => {
    if (!run?.id) return;
    try {
      const resp = await fetch(`/api/v1/ops/eval/runs/${run.id}/stop`, {
        method: "POST",
        headers,
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `HTTP ${resp.status}`);
      }
      setRun((await resp.json()) as EvalRun);
      setLogLines((prev) => [...prev, "■ stop requested"]);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : String(err));
    }
  };

  const startRun = async () => {
    if (selected.size === 0) return;
    if (suite === "ci" && !proofAvailable) {
      setAuthError("完整 CI 证明不可用：需要 Docker socket 与仓库挂载 (/repo)");
      return;
    }
    if (suite === "golden" && mode === "live" && !apiKey.trim()) {
      setAuthError("live 模式需要填写评测专用 API Key");
      return;
    }
    setBusy(true);
    setLogLines([]);
    setAuthError(null);
    try {
      const body: Record<string, unknown> = {
        suite,
        mode: suite === "ci" ? "stub" : mode,
        case_ids: Array.from(selected),
        restart_runtime: suite === "golden" && restartRuntime && restartAvailable,
      };
      if (suite === "golden" && mode === "live") {
        body.model = {
          provider,
          model_name: modelName,
          api_key: apiKey,
          base_url: baseUrl || null,
        };
      }
      const resp = await fetch("/api/v1/ops/eval/runs", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `HTTP ${resp.status}`);
      }
      const created = (await resp.json()) as EvalRun;
      setRun(created);
      navigate(opsRunPath(secret, created.id));

      const es = new EventSourcePolyfill(
        `/api/v1/ops/eval/runs/${created.id}/stream`,
        secret,
      );
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as Record<string, unknown>;
          const kind = String(data.kind || "");
          if (kind === "log") {
            setLogLines((prev) => [...prev, String(data.message || "")]);
          } else if (kind === "case_started") {
            setLogLines((prev) => [...prev, `→ ${data.case_id}`]);
          } else if (kind === "case_finished") {
            setLogLines((prev) => [
              ...prev,
              `${data.status === "pass" ? "✓" : data.status === "skipped" ? "○" : "✗"} ${data.case_id}`,
            ]);
          }
          void refreshRun(created.id);
          if (kind === "run_finished") {
            es.close();
            setBusy(false);
            void loadRecent();
          }
        } catch {
          /* ignore */
        }
      };
      es.onerror = () => {
        es.close();
        void refreshRun(created.id).finally(() => setBusy(false));
      };
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  if (authError && cases.length === 0) {
    return (
      <OpsShell secret={secret} title="Golden Turn 评测台">
        <p className="text-sm text-destructive">{authError}</p>
      </OpsShell>
    );
  }

  return (
    <OpsShell
      secret={secret}
      title="评测台"
      subtitle={
        suite === "ci"
          ? "完整证明 ≡ CI（unit + make gate）。耗时长；gate 会重建 runtime 并在结束后恢复日常栈。"
          : "Golden 切片：对当前 api/runtime 点选。切片绿 ≠ 合并证明。"
      }
      actions={
        run ? (
          <Link
            to={opsRunPath(secret, run.id)}
            className="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-foreground hover:bg-primary/15"
          >
            查看输出 / 日志
          </Link>
        ) : null
      }
    >
      <section className="space-y-3 border-b border-border pb-5">
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="inline-flex items-center gap-2">
            <input
              type="radio"
              name="suite"
              checked={suite === "ci"}
              disabled={!proofAvailable}
              onChange={() => setSuite("ci")}
            />
            完整证明（≡ CI）
            {!proofAvailable ? <span className="text-xs text-muted-foreground">不可用</span> : null}
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              type="radio"
              name="suite"
              checked={suite === "golden"}
              onChange={() => setSuite("golden")}
            />
            Golden 切片
          </label>
        </div>

        {suite === "golden" ? (
          <>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  name="mode"
                  checked={mode === "stub"}
                  onChange={() => setMode("stub")}
                />
                stub
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  name="mode"
                  checked={mode === "live"}
                  onChange={() => setMode("live")}
                />
                live
              </label>
            </div>

            {mode === "live" ? (
              <div className="grid max-w-lg gap-2">
                <input
                  className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm"
                  placeholder="provider"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                />
                <input
                  className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm"
                  placeholder="model_name"
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                />
                <input
                  className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm"
                  placeholder="base_url"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
                <input
                  className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm"
                  type="password"
                  placeholder="评测专用 api_key（不写入用户设置）"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </div>
            ) : null}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            勾选要跑的 CI 步骤（与 GitHub Actions 同脚本）。gate 含 smoke + 全量 golden，耗时最长。
          </p>
        )}
      </section>

      <section className="space-y-3 border-b border-border py-5">
        {suite === "ci" ? (
          <>
            <div className="flex flex-wrap gap-2">
              <GhostBtn onClick={() => toggleAll(true)}>全选</GhostBtn>
              <GhostBtn onClick={() => toggleAll(false)}>清空</GhostBtn>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="border-b border-border px-1.5 py-2 font-medium" />
                    <th className="border-b border-border px-1.5 py-2 font-medium">状态</th>
                    <th className="border-b border-border px-1.5 py-2 font-medium">步骤</th>
                    <th className="border-b border-border px-1.5 py-2 font-medium">说明</th>
                  </tr>
                </thead>
                <tbody>
                  {ciProofCases.map((c) => {
                    const result = resultById.get(c.id);
                    const st = result?.status ?? "pending";
                    return (
                      <tr key={c.id} className="align-top">
                        <td className="border-b border-border/70 px-1.5 py-2">
                          <input
                            type="checkbox"
                            checked={selected.has(c.id)}
                            disabled={busy}
                            onChange={(e) => {
                              setSelected((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(c.id);
                                else next.delete(c.id);
                                return next;
                              });
                            }}
                          />
                        </td>
                        <td className={`border-b border-border/70 px-1.5 py-2 font-semibold ${statusClass(st)}`}>
                          {st}
                        </td>
                        <td className="border-b border-border/70 px-1.5 py-2 font-mono text-xs">{c.id}</td>
                        <td className="border-b border-border/70 px-1.5 py-2 text-muted-foreground">
                          {c.description}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <select
                className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                value={scenarioFilter}
                onChange={(e) => setScenarioFilter(e.target.value)}
              >
                <option value="">全部 scenario</option>
                <option value="writing">writing</option>
                <option value="agent">agent</option>
                <option value="interview">interview</option>
              </select>
              <input
                className="w-40 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                placeholder="tag 过滤"
                value={tagFilter}
                onChange={(e) => setTagFilter(e.target.value)}
              />
              <GhostBtn onClick={() => void loadCases()}>刷新用例</GhostBtn>
              <GhostBtn onClick={() => toggleAll(true)}>全选</GhostBtn>
              <GhostBtn onClick={() => toggleAll(false)}>清空</GhostBtn>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="border-b border-border px-1.5 py-2 font-medium" />
                    <th className="border-b border-border px-1.5 py-2 font-medium">状态</th>
                    <th className="border-b border-border px-1.5 py-2 font-medium">用例</th>
                    <th className="border-b border-border px-1.5 py-2 font-medium">scenario</th>
                    <th className="border-b border-border px-1.5 py-2 font-medium">tags</th>
                    <th className="border-b border-border px-1.5 py-2 font-medium">说明</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c) => {
                    const result = resultById.get(c.id);
                    const st = result?.status ?? "pending";
                    return (
                      <tr key={c.id} className="align-top">
                        <td className="border-b border-border/70 px-1.5 py-2">
                          <input
                            type="checkbox"
                            checked={selected.has(c.id)}
                            onChange={(e) => {
                              setSelected((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(c.id);
                                else next.delete(c.id);
                                return next;
                              });
                            }}
                          />
                        </td>
                        <td className={`border-b border-border/70 px-1.5 py-2 font-semibold ${statusClass(st)}`}>
                          {st}
                        </td>
                        <td className="border-b border-border/70 px-1.5 py-2">{c.id}</td>
                        <td className="border-b border-border/70 px-1.5 py-2">{c.scenario_id}</td>
                        <td className="border-b border-border/70 px-1.5 py-2 text-muted-foreground">
                          {c.tags.join(", ")}
                        </td>
                        <td className="border-b border-border/70 px-1.5 py-2 text-muted-foreground">
                          {c.description}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="space-y-3 pt-5">
        {suite === "golden" ? (
          <label
            className={`inline-flex items-center gap-2 text-sm ${
              restartAvailable ? "" : "opacity-50"
            }`}
            title={
              restartAvailable
                ? "跑前 force-recreate / restart runtime"
                : "当前环境无 Docker socket / CLI"
            }
          >
            <input
              type="checkbox"
              disabled={!restartAvailable}
              checked={restartRuntime && restartAvailable}
              onChange={(e) => setRestartRuntime(e.target.checked)}
            />
            高级：跑前重建 runtime
            {!restartAvailable ? "（不可用）" : null}
          </label>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={
              busy ||
              selected.size === 0 ||
              (suite === "ci" && !proofAvailable)
            }
            onClick={() => void startRun()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {busy
              ? "运行中…"
              : suite === "ci"
                ? `跑选中步骤（${selected.size}）`
                : `Run（${selected.size}）`}
          </button>
            {busy && run ? (
            <button
              type="button"
              onClick={() => void stopRun()}
              disabled={run.status === "cancelling" || Boolean(run.cancel_requested)}
              className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-2 text-sm font-medium text-destructive hover:bg-destructive/15 disabled:opacity-50"
            >
              {run.status === "cancelling" || run.cancel_requested ? "停止中…" : "停止"}
            </button>
          ) : null}
          {run ? (
            <>
              <span className="text-sm text-muted-foreground">
                run {run.id.slice(0, 8)} · {run.suite || "golden"} · {run.status}
                {run.error ? ` · ${run.error}` : ""}
              </span>
              <Link
                to={opsRunPath(secret, run.id)}
                className="text-sm text-primary underline-offset-2 hover:underline"
              >
                打开输出页
              </Link>
            </>
          ) : null}
        </div>
        {authError ? <p className="text-sm text-destructive">{authError}</p> : null}
        {logLines.length > 0 ? (
          <pre className="max-h-48 overflow-auto rounded-md border border-border bg-card p-3 text-[11px] text-muted-foreground">
            {logLines.join("\n")}
          </pre>
        ) : null}
      </section>

      <section className="mt-8 space-y-3 border-t border-border pt-5">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium text-foreground">最近结果</h2>
          <Link
            to={opsHistoryPath(secret)}
            className="text-xs text-primary underline-offset-2 hover:underline"
          >
            全部历史 →
          </Link>
        </div>
        {recent.length === 0 ? (
          <p className="text-xs text-muted-foreground">尚无历史。跑完一次后会出现在这里（Postgres 持久化）。</p>
        ) : (
          <ul className="space-y-1.5">
            {recent.map((r) => {
              const s = r.summary || {};
              return (
                <li key={r.id}>
                  <Link
                    to={opsRunPath(secret, r.id)}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card/50 px-2.5 py-2 text-xs hover:bg-muted/60"
                  >
                    <span className="font-mono text-muted-foreground">{r.id.slice(0, 8)}…</span>
                    <span className={statusClass(r.status)}>{r.status}</span>
                    <span className="text-muted-foreground">{r.suite || r.mode}</span>
                    <span>
                      <span className="text-success">{s.pass ?? 0}</span>
                      <span className="text-muted-foreground">/</span>
                      <span className={(s.fail ?? 0) > 0 ? "text-destructive" : "text-muted-foreground"}>
                        {s.fail ?? 0}
                      </span>
                    </span>
                    <span className="text-muted-foreground">
                      {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </OpsShell>
  );
}

function GhostBtn({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md border border-border px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
    >
      {children}
    </button>
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
