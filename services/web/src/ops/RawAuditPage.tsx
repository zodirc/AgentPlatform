import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { OpsShell, secretFromOpsPath, turnIdFromSearch } from "./OpsShell";
import { OpsTurnLinks } from "./OpsTurnLinks";
import { OpsPayloadViewerModal } from "./OpsPayloadViewerModal";
import {
  OPS_TURN_LIST_FILTERS,
  OpsListFilters,
  OpsListPagination,
  useOpsListParams,
} from "./OpsListFilters";

type SnapshotItem = {
  step_index: number;
  tools_fingerprint?: string | null;
  message_count: number;
  messages: unknown[];
  created_at?: string | null;
};

type RawResponse = {
  turn_id: string;
  count: number;
  snapshots: SnapshotItem[];
};

type RecentItem = {
  turn_id: string;
  session_id: string;
  scenario_id?: string;
  status?: string;
  user_preview?: string | null;
  owner_user_id?: string | null;
  snapshot_count: number;
  max_step_index?: number | null;
  last_at?: string | null;
};

type ViewerState = {
  title: string;
  subtitle: string;
  downloadName: string;
  payload: unknown;
};

function authHeaders(secret: string): HeadersInit {
  return { Authorization: `Bearer ${secret}` };
}

export function RawAuditPage() {
  const { pathname, search } = useLocation();
  const secret = secretFromOpsPath(pathname);
  const list = useOpsListParams(["status", "scenario"]);
  const [turnId, setTurnId] = useState("");
  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<RawResponse | null>(null);
  const [viewer, setViewer] = useState<ViewerState | null>(null);

  const qs = list.queryString();

  const loadRecent = useCallback(async () => {
    if (!secret) return;
    setListLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/ops/raw/recent?${qs}`, {
        headers: authHeaders(secret),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      const body = (await res.json()) as {
        items?: RecentItem[];
        total?: number;
        error?: string;
      };
      setRecent(body.items || []);
      setTotal(typeof body.total === "number" ? body.total : (body.items || []).length);
      if (body.error) setError(body.error);
    } catch (e) {
      setRecent([]);
      setTotal(0);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setListLoading(false);
    }
  }, [secret, qs]);

  const loadTurn = useCallback(
    async (id: string) => {
      const trimmed = id.trim();
      if (!trimmed || !secret) return;
      setTurnId(trimmed);
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/v1/ops/raw/turns/${encodeURIComponent(trimmed)}`, {
          headers: authHeaders(secret),
        });
        if (!res.ok) {
          const body = await res.text();
          throw new Error(body || `HTTP ${res.status}`);
        }
        setData((await res.json()) as RawResponse);
      } catch (e) {
        setData(null);
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [secret],
  );

  useEffect(() => {
    void loadRecent();
  }, [loadRecent]);

  const listOffset = list.offset;
  const goPage = list.goPage;
  useEffect(() => {
    if (!listLoading && total > 0 && listOffset >= total) {
      goPage(1);
    }
  }, [listLoading, total, listOffset, goPage]);

  useEffect(() => {
    const fromQuery = turnIdFromSearch(search);
    if (fromQuery) void loadTurn(fromQuery);
  }, [search, loadTurn]);

  const openSnapshot = (item: SnapshotItem, turn: string) => {
    setViewer({
      title: `raw messages · step ${item.step_index}`,
      subtitle: `${turn} · messages=${item.message_count}`,
      downloadName: `raw-${turn.slice(0, 8)}-step-${item.step_index}.json`,
      payload: item.messages,
    });
  };

  return (
    <OpsShell
      secret={secret}
      title="Raw 快照"
      subtitle="只读原件仓（HM2）· 点「查看」以文件预览方式打开 · 旁路观测"
    >
      <OpsListFilters
        searchPlaceholder="turn / session / 用户输入…"
        qInput={list.qInput}
        onQChange={list.setQInput}
        filterDefs={OPS_TURN_LIST_FILTERS}
        filters={list.filters}
        onFilterChange={list.setFilter}
        hasFilters={list.hasFilters}
        onClear={list.clearFilters}
        total={total}
        page={list.page}
        loading={listLoading}
        onRefresh={() => void loadRecent()}
      />

      <div className="mb-4 rounded-md border border-border">
        <div className="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
          最近 Raw Turn
        </div>
        {!recent.length && !listLoading ? (
          <p className="px-3 py-4 text-sm text-muted-foreground">
            {list.hasFilters
              ? "没有匹配的 Turn，试试放宽筛选。"
              : "暂无 raw 快照。跑过 Turn 后再刷新。"}
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {recent.map((item) => {
              const selected = data?.turn_id === item.turn_id;
              return (
                <li key={item.turn_id}>
                  <button
                    type="button"
                    onClick={() => void loadTurn(item.turn_id)}
                    className={`w-full px-3 py-2.5 text-left text-sm hover:bg-muted/60 ${
                      selected ? "bg-primary/10" : ""
                    }`}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-medium text-foreground">
                        {item.user_preview || "(no preview)"}
                      </span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {item.last_at || "—"}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-muted-foreground">
                      <span>{item.scenario_id}</span>
                      <span>snapshots={item.snapshot_count}</span>
                      {item.max_step_index != null ? (
                        <span>max_step={item.max_step_index}</span>
                      ) : null}
                      <span className="truncate">{item.turn_id}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <OpsListPagination
        page={list.page}
        total={total}
        itemCount={recent.length}
        onPage={list.goPage}
      />

      <details className="mb-4 mt-4 rounded-md border border-border px-3 py-2 text-sm">
        <summary className="cursor-pointer text-muted-foreground">精确跳转（可选 turn_id）</summary>
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            className="min-w-[280px] flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm font-mono"
            placeholder="turn_id (UUID)"
            value={turnId}
            onChange={(e) => setTurnId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void loadTurn(turnId);
            }}
          />
          <button
            type="button"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
            onClick={() => void loadTurn(turnId)}
            disabled={loading || !turnId.trim()}
          >
            {loading ? "加载中…" : "打开"}
          </button>
        </div>
      </details>

      {error ? <p className="mb-4 text-sm text-destructive">{error}</p> : null}

      {data ? (
        <div className="space-y-3">
          <OpsTurnLinks secret={secret} turnId={data.turn_id} current="raw" />
          <p className="text-sm text-muted-foreground">
            turn={data.turn_id} · snapshots={data.count}
          </p>
          <p className="text-xs text-muted-foreground">
            用途：坏例回放 / 摘要重建对照。内容不进模型请求。
          </p>
          {data.snapshots.map((item, i) => (
            <div
              key={`${item.step_index}-${item.created_at || i}`}
              className="rounded-md border border-border bg-card px-3 py-2 text-xs"
            >
              <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
                <span>step={item.step_index}</span>
                <span>messages={item.message_count}</span>
                {item.tools_fingerprint ? (
                  <span className="truncate">fp={item.tools_fingerprint}</span>
                ) : null}
                <button
                  type="button"
                  className="ml-auto rounded-md border border-border px-2 py-1 text-[11px] text-foreground hover:bg-muted"
                  onClick={() => openSnapshot(item, data.turn_id)}
                >
                  查看
                </button>
              </div>
            </div>
          ))}
          {!data.snapshots.length ? (
            <p className="text-sm text-muted-foreground">该 Turn 无 raw 快照。</p>
          ) : null}
        </div>
      ) : null}

      <OpsPayloadViewerModal
        open={Boolean(viewer)}
        title={viewer?.title || ""}
        subtitle={viewer?.subtitle}
        downloadName={viewer?.downloadName}
        payload={viewer?.payload}
        onClose={() => setViewer(null)}
      />
    </OpsShell>
  );
}
