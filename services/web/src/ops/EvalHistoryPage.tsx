import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  OpsShell,
  opsRunPath,
  secretFromOpsPath,
  statusClass,
} from "./OpsShell";
import {
  OpsListFilters,
  OpsListPagination,
  useOpsListParams,
  type OpsListFilterDef,
} from "./OpsListFilters";

type RunSummary = {
  id: string;
  status: string;
  mode: string;
  suite?: string;
  created_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  summary?: {
    total?: number;
    pass?: number;
    fail?: number;
    skipped?: number;
    pending?: number;
  };
  model_meta?: { provider?: string; model_name?: string };
};

const FILTER_KEYS = ["status", "mode", "suite"];

const HISTORY_FILTERS: OpsListFilterDef[] = [
  {
    key: "status",
    label: "状态",
    options: [
      { value: "", label: "全部" },
      { value: "queued", label: "queued" },
      { value: "running", label: "running" },
      { value: "completed", label: "completed" },
      { value: "failed", label: "failed" },
      { value: "cancelled", label: "cancelled" },
      { value: "cancelling", label: "cancelling" },
    ],
  },
  {
    key: "mode",
    label: "模式",
    options: [
      { value: "", label: "全部" },
      { value: "stub", label: "stub" },
      { value: "live", label: "live" },
    ],
  },
  {
    key: "suite",
    label: "套件",
    options: [
      { value: "", label: "全部" },
      { value: "ci", label: "ci" },
      { value: "golden", label: "golden" },
      { value: "official", label: "bench" },
    ],
  },
];

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function EvalHistoryPage() {
  const { pathname } = useLocation();
  const secret = secretFromOpsPath(pathname);
  const list = useOpsListParams(FILTER_KEYS);

  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const headers = useMemo(
    () => ({
      Authorization: `Bearer ${secret}`,
      Accept: "application/json",
    }),
    [secret],
  );

  const qs = list.queryString();

  const load = useCallback(async () => {
    const resp = await fetch(`/api/v1/ops/eval/runs?${qs}`, { headers });
    if (resp.status === 401 || resp.status === 403 || resp.status === 404) {
      setError("无效密钥或评测台未启用");
      setLoading(false);
      return;
    }
    if (!resp.ok) {
      setError(`加载历史失败 HTTP ${resp.status}`);
      setLoading(false);
      return;
    }
    const data = (await resp.json()) as { runs: RunSummary[]; total?: number };
    setRuns(data.runs || []);
    setTotal(typeof data.total === "number" ? data.total : (data.runs || []).length);
    setError(null);
    setLoading(false);
  }, [headers, qs]);

  useEffect(() => {
    setLoading(true);
    void load();
    const t = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(t);
  }, [load]);

  const listOffset = list.offset;
  const goPage = list.goPage;
  useEffect(() => {
    if (!loading && total > 0 && listOffset >= total) {
      goPage(1);
    }
  }, [loading, total, listOffset, goPage]);

  return (
    <OpsShell
      secret={secret}
      title="评测历史"
      subtitle="后端持久化的历次自动化测试结果；可用筛选与搜索定位。"
    >
      <OpsListFilters
        searchPlaceholder="例如 uuid 前缀、cancelled…"
        qInput={list.qInput}
        onQChange={list.setQInput}
        filterDefs={HISTORY_FILTERS}
        filters={list.filters}
        onFilterChange={list.setFilter}
        hasFilters={list.hasFilters}
        onClear={list.clearFilters}
        total={total}
        page={list.page}
        loading={loading}
        onRefresh={() => void load()}
      />

      {error ? <p className="mb-4 text-sm text-destructive">{error}</p> : null}
      {loading && runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {list.hasFilters
            ? "没有匹配的历史记录，试试放宽筛选条件。"
            : "还没有历史记录。去控制台跑一次 stub/live 评测即可。"}
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="border-b border-border px-2 py-2 font-medium">时间</th>
                  <th className="border-b border-border px-2 py-2 font-medium">状态</th>
                  <th className="border-b border-border px-2 py-2 font-medium">套件</th>
                  <th className="border-b border-border px-2 py-2 font-medium">模式</th>
                  <th className="border-b border-border px-2 py-2 font-medium">通过/失败</th>
                  <th className="border-b border-border px-2 py-2 font-medium">Run</th>
                  <th className="border-b border-border px-2 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const s = r.summary || {};
                  const pass = s.pass ?? 0;
                  const fail = s.fail ?? 0;
                  const totalCases = s.total ?? 0;
                  return (
                    <tr key={r.id} className="align-top">
                      <td className="border-b border-border/70 px-2 py-2 text-muted-foreground">
                        {formatTime(r.created_at)}
                      </td>
                      <td
                        className={`border-b border-border/70 px-2 py-2 font-semibold ${statusClass(r.status)}`}
                      >
                        {r.status}
                      </td>
                      <td className="border-b border-border/70 px-2 py-2">{r.suite || "—"}</td>
                      <td className="border-b border-border/70 px-2 py-2">{r.mode}</td>
                      <td className="border-b border-border/70 px-2 py-2">
                        <span className="text-success">{pass}</span>
                        <span className="text-muted-foreground"> / </span>
                        <span className={fail ? "text-destructive" : "text-muted-foreground"}>
                          {fail}
                        </span>
                        <span className="text-muted-foreground"> · {totalCases}</span>
                      </td>
                      <td className="border-b border-border/70 px-2 py-2 font-mono text-xs text-muted-foreground">
                        <span title={r.id}>{r.id.slice(0, 8)}…</span>
                        {r.error ? (
                          <div className="mt-1 max-w-xs truncate text-destructive" title={r.error}>
                            {r.error}
                          </div>
                        ) : null}
                      </td>
                      <td className="border-b border-border/70 px-2 py-2 text-right">
                        <Link
                          to={opsRunPath(secret, r.id)}
                          className="text-primary underline-offset-2 hover:underline"
                        >
                          查看输出
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <OpsListPagination
            page={list.page}
            total={total}
            itemCount={runs.length}
            onPage={list.goPage}
          />
        </>
      )}
      <p className="mt-4 text-xs text-muted-foreground">
        列表来自 `GET /api/v1/ops/eval/runs`（支持 q / status / mode / suite / offset）；明细写入
        Postgres `ops_eval_runs`。
      </p>
    </OpsShell>
  );
}
