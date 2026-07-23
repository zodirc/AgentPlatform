import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { OpsShell, opsRunPath, secretFromOpsPath, statusClass } from "./OpsShell";

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
  mode: string;
  restart_runtime: boolean;
  restart_available?: boolean;
  cases: CaseResult[];
  error?: string | null;
};

type Mode = "stub" | "live";

export function EvalConsolePage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const secret = secretFromOpsPath(pathname);
  const [authError, setAuthError] = useState<string | null>(null);
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [tagFilter, setTagFilter] = useState("");
  const [scenarioFilter, setScenarioFilter] = useState("");
  const [mode, setMode] = useState<Mode>("stub");
  const [provider, setProvider] = useState("deepseek");
  const [modelName, setModelName] = useState("deepseek-chat");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [restartRuntime, setRestartRuntime] = useState(false);
  const [restartAvailable, setRestartAvailable] = useState(false);
  const [run, setRun] = useState<EvalRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);

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
    const data = (await resp.json()) as { restart_available?: boolean };
    setRestartAvailable(Boolean(data.restart_available));
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
    setSelected(new Set(data.cases.map((c) => c.id)));
    setAuthError(null);
  }, [headers, scenarioFilter, tagFilter]);

  useEffect(() => {
    void (async () => {
      const ok = await loadMeta();
      if (ok) await loadCases();
    })();
  }, [loadMeta, loadCases]);

  const resultById = useMemo(() => {
    const map = new Map<string, CaseResult>();
    for (const c of run?.cases ?? []) map.set(c.case_id, c);
    return map;
  }, [run]);

  const toggleAll = (on: boolean) => {
    setSelected(on ? new Set(cases.map((c) => c.id)) : new Set());
  };

  const refreshRun = async (runId: string) => {
    const resp = await fetch(`/api/v1/ops/eval/runs/${runId}`, { headers });
    if (!resp.ok) return;
    setRun((await resp.json()) as EvalRun);
  };

  const startRun = async () => {
    if (selected.size === 0) return;
    if (mode === "live" && !apiKey.trim()) {
      setAuthError("live 模式需要填写评测专用 API Key");
      return;
    }
    setBusy(true);
    setLogLines([]);
    setAuthError(null);
    try {
      const body: Record<string, unknown> = {
        mode,
        case_ids: Array.from(selected),
        restart_runtime: restartRuntime && restartAvailable,
      };
      if (mode === "live") {
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
              `${data.status === "pass" ? "✓" : "✗"} ${data.case_id}`,
            ]);
          }
          void refreshRun(created.id);
          if (kind === "run_finished") {
            es.close();
            setBusy(false);
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
      title="Golden Turn 评测台"
      subtitle="对当前运行的 api/runtime 发 Turn；默认不重启容器。"
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
      </section>

      <section className="space-y-3 border-b border-border py-5">
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
      </section>

      <section className="space-y-3 pt-5">
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

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={busy || selected.size === 0}
            onClick={() => void startRun()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {busy ? "运行中…" : `Run（${selected.size}）`}
          </button>
          {run ? (
            <>
              <span className="text-sm text-muted-foreground">
                run {run.id.slice(0, 8)} · {run.status}
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
