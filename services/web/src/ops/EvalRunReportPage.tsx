import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { OpsShell, opsConsolePath, secretFromOpsPath, statusClass } from "./OpsShell";

type CaseStep = {
  at?: string;
  kind: string;
  message?: string;
  detail?: Record<string, unknown>;
};

type CaseResult = {
  case_id: string;
  status: string;
  events: string[];
  steps?: CaseStep[];
  error?: string | null;
  turn_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

type EvalRun = {
  id: string;
  status: string;
  suite?: string;
  mode: string;
  created_at: string;
  finished_at?: string | null;
  error?: string | null;
  cancel_requested?: boolean;
  summary?: { total: number; pass: number; fail: number; pending: number };
  cases: CaseResult[];
  logs?: Array<Record<string, unknown>>;
};

export function EvalRunReportPage() {
  const { pathname } = useLocation();
  const secret = secretFromOpsPath(pathname);
  const runId = pathname.match(/\/runs\/([^/]+)\/?$/)?.[1] || "";

  const [run, setRun] = useState<EvalRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [tab, setTab] = useState<"cases" | "log">("cases");
  const [stopping, setStopping] = useState(false);
  const doneRef = useRef(false);

  const headers = useMemo(
    () => ({
      Authorization: `Bearer ${secret}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    }),
    [secret],
  );

  const load = useCallback(async () => {
    if (!runId) return;
    const resp = await fetch(`/api/v1/ops/eval/runs/${runId}`, { headers });
    if (resp.status === 401 || resp.status === 403 || resp.status === 404) {
      setError(resp.status === 404 ? "Run 不存在或已过期" : "无效密钥");
      return;
    }
    if (!resp.ok) {
      setError(`加载失败 HTTP ${resp.status}`);
      return;
    }
    setRun((await resp.json()) as EvalRun);
    setError(null);
  }, [headers, runId]);

  useEffect(() => {
    doneRef.current = false;
    void load();
    const t = window.setInterval(() => {
      if (doneRef.current) return;
      void load();
    }, 2000);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (run && (run.status === "completed" || run.status === "failed" || run.status === "cancelled")) {
      doneRef.current = true;
    } else {
      doneRef.current = false;
    }
  }, [run]);

  const stopRun = async () => {
    if (!runId || stopping) return;
    setStopping(true);
    setError(null);
    try {
      const resp = await fetch(`/api/v1/ops/eval/runs/${runId}/stop`, {
        method: "POST",
        headers,
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `HTTP ${resp.status}`);
      }
      setRun((await resp.json()) as EvalRun);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStopping(false);
      void load();
    }
  };

  if (error && !run) {
    return (
      <OpsShell secret={secret} title="评测输出">
        <p className="text-sm text-destructive">{error}</p>
      </OpsShell>
    );
  }

  if (!run) {
    return (
      <OpsShell secret={secret} title="评测输出">
        <p className="text-sm text-muted-foreground">加载中…</p>
      </OpsShell>
    );
  }

  const summary = run.summary ?? {
    total: run.cases.length,
    pass: run.cases.filter((c) => c.status === "pass").length,
    fail: run.cases.filter((c) => c.status === "fail").length,
    pending: run.cases.filter((c) => c.status === "pending" || c.status === "running")
      .length,
  };
  const running =
    run.status === "queued" || run.status === "running" || run.status === "cancelling";

  return (
    <OpsShell
      secret={secret}
      title="评测输出"
      subtitle={`run ${run.id} · ${run.suite || run.mode} · ${run.status}`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {running ? (
            <button
              type="button"
              disabled={stopping || run.cancel_requested}
              onClick={() => void stopRun()}
              className="rounded-md border border-destructive/50 bg-destructive/10 px-2 py-1 text-destructive hover:bg-destructive/15 disabled:opacity-50"
            >
              {run.cancel_requested || stopping ? "停止中…" : "停止"}
            </button>
          ) : null}
          <Link
            to={opsConsolePath(secret)}
            className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted"
          >
            返回控制台
          </Link>
        </div>
      }
    >
      <section className="mb-6 grid gap-3 sm:grid-cols-4">
        <Stat label="总计" value={String(summary.total)} />
        <Stat label="通过" value={String(summary.pass)} tone="success" />
        <Stat label="失败" value={String(summary.fail)} tone="danger" />
        <Stat label="进行中" value={String(summary.pending)} tone="warn" />
      </section>

      {run.error ? (
        <p className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {run.error}
        </p>
      ) : null}

      <div className="mb-4 flex gap-2">
        <TabBtn active={tab === "cases"} onClick={() => setTab("cases")}>
          用例结果
        </TabBtn>
        <TabBtn active={tab === "log"} onClick={() => setTab("log")}>
          运行日志
        </TabBtn>
      </div>

      {tab === "log" ? (
        <pre className="max-h-[70vh] overflow-auto rounded-lg border border-border bg-card p-3 text-[11px] leading-relaxed text-muted-foreground">
          {(run.logs || [])
            .map((line) => JSON.stringify(line))
            .join("\n") || "(empty)"}
        </pre>
      ) : (
        <div className="space-y-2">
          {run.cases.map((c) => {
            const open = expanded === c.case_id;
            return (
              <article
                key={c.case_id}
                className="rounded-lg border border-border bg-card/60"
              >
                <button
                  type="button"
                  className="flex w-full items-start justify-between gap-3 px-3 py-2.5 text-left"
                  onClick={() => setExpanded(open ? null : c.case_id)}
                >
                  <div>
                    <div className="font-medium text-foreground">{c.case_id}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {c.turn_id ? `turn ${c.turn_id.slice(0, 8)}…` : "—"}
                      {c.started_at ? ` · ${c.started_at}` : ""}
                    </div>
                  </div>
                  <span className={`text-sm font-semibold ${statusClass(c.status)}`}>
                    {c.status}
                  </span>
                </button>
                {open ? (
                  <div className="border-t border-border px-3 py-3">
                    {c.error ? (
                      <p className="mb-3 whitespace-pre-wrap text-xs text-destructive">
                        {c.error}
                      </p>
                    ) : null}
                    <h3 className="mb-2 text-xs font-medium text-muted-foreground">
                      测试步骤
                    </h3>
                    <ol className="mb-4 space-y-1.5">
                      {(c.steps || []).length === 0 ? (
                        <li className="text-xs text-muted-foreground">(no steps yet)</li>
                      ) : (
                        (c.steps || []).map((step, idx) => (
                          <li
                            key={`${c.case_id}-${idx}`}
                            className="rounded-md bg-muted/40 px-2 py-1.5 text-xs"
                          >
                            <div className="flex flex-wrap gap-2">
                              <span className="text-muted-foreground">{idx + 1}.</span>
                              <span className="font-medium text-foreground">{step.kind}</span>
                              {step.message ? (
                                <span className="text-muted-foreground">{step.message}</span>
                              ) : null}
                            </div>
                            {step.detail && Object.keys(step.detail).length > 0 ? (
                              <pre className="mt-1 overflow-auto text-[10px] text-muted-foreground">
                                {JSON.stringify(step.detail, null, 2)}
                              </pre>
                            ) : null}
                          </li>
                        ))
                      )}
                    </ol>
                    <h3 className="mb-2 text-xs font-medium text-muted-foreground">
                      事件序列
                    </h3>
                    <pre className="overflow-auto rounded-md bg-muted/40 p-2 text-[11px] text-muted-foreground">
                      {(c.events || []).join("\n") || "(no events)"}
                    </pre>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </OpsShell>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "success" | "danger" | "warn";
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "danger"
        ? "text-destructive"
        : tone === "warn"
          ? "text-warning"
          : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card/60 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-3 py-1.5 text-xs ${
        active
          ? "border-primary/50 bg-primary/10 text-foreground"
          : "border-border text-muted-foreground hover:bg-muted"
      }`}
    >
      {children}
    </button>
  );
}
