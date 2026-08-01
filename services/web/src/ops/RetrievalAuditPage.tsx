import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { OpsShell, secretFromOpsPath, turnIdFromSearch } from "./OpsShell";
import { OpsTurnLinks } from "./OpsTurnLinks";
import {
  OPS_TURN_LIST_FILTERS,
  OpsListFilters,
  OpsListPagination,
  opsTurnListQueryString,
  useOpsListParams,
} from "./OpsListFilters";
import {
  OpsMasterDetail,
  OpsTurnListItem,
  OpsTurnNavButtons,
  useOpsAuditTurnSelection,
  useOpsTurnBrowse,
} from "./OpsMasterDetail";
import {
  diagnoseRetrievalAudit,
  layerOnlyIn,
  type AuditHitLike,
} from "./retrievalDiagnostics";

type AuditHit = AuditHitLike & {
  score?: number;
  excerpt?: string;
  source?: string;
  citation_id?: string;
  char_len?: number;
};

type RetrievalItem = {
  sequence: number;
  step_index?: number | null;
  ts?: string | null;
  query?: string;
  mode?: string;
  hit_count?: number;
  summary?: string;
  hits?: AuditHit[];
  audit?: {
    mode?: string;
    rank_method?: string | null;
    recall_pool?: AuditHit[];
    ranked?: AuditHit[];
    entered_context?: AuditHit[];
  } | null;
};

type AuditResponse = {
  turn_id: string;
  session_id: string;
  scenario_id?: string;
  status?: string;
  owner_user_id?: string | null;
  work_id?: string | null;
  retrieval_count: number;
  retrievals: RetrievalItem[];
};

type RecentItem = {
  turn_id: string;
  session_id: string;
  scenario_id?: string;
  status?: string;
  user_preview?: string | null;
  owner_user_id?: string | null;
  retrieval_count: number;
  last_retrieval_at?: string | null;
  last_query?: string | null;
  last_hit_count?: number | null;
};

function HitList({
  title,
  rows,
  highlightKeys,
}: {
  title: string;
  rows: AuditHit[];
  highlightKeys?: Set<string>;
}) {
  if (!rows.length) {
    return (
      <div className="rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
        {title}：空
      </div>
    );
  }
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2">
      <p className="text-xs font-medium text-foreground">
        {title}（{rows.length}）
      </p>
      <ul className="mt-2 space-y-2">
        {rows.map((h, i) => {
          const key = (h.chunk_id || h.path || "").trim();
          const marked = key && highlightKeys?.has(key);
          return (
            <li
              key={`${h.chunk_id || h.path || i}-${i}`}
              className={`text-xs text-muted-foreground ${
                marked ? "rounded border border-warning/40 bg-warning/10 px-1.5 py-1" : ""
              }`}
            >
              <div className="flex flex-wrap gap-2 font-mono text-[11px] text-primary">
                <span className="truncate">{h.path || "(no path)"}</span>
                {h.score != null ? <span>score={h.score}</span> : null}
                {h.source ? <span>src={h.source}</span> : null}
                {h.truncated ? <span className="text-warning">truncated</span> : null}
                {marked ? <span className="text-warning">only-here</span> : null}
              </div>
              {h.chunk_id ? (
                <div className="truncate font-mono text-[10px] opacity-80">{h.chunk_id}</div>
              ) : null}
              {h.excerpt ? <p className="mt-0.5 break-words">{h.excerpt}</p> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function authHeaders(secret: string): HeadersInit {
  return { Authorization: `Bearer ${secret}` };
}

export function RetrievalAuditPage() {
  const { pathname, search } = useLocation();
  const secret = secretFromOpsPath(pathname);
  const list = useOpsListParams(["within", "status", "scenario"]);
  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<AuditResponse | null>(null);
  const { beginLoad, endLoad, isStale, selectedId, jumpId, setJumpId, loading } =
    useOpsAuditTurnSelection(secret);

  const qs = opsTurnListQueryString(list);
  const turnIds = useMemo(() => recent.map((r) => r.turn_id), [recent]);
  const firstTurnId = recent[0]?.turn_id ?? "";

  const loadRecent = useCallback(async () => {
    if (!secret) return;
    setListLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/ops/retrieval/recent?${qs}`, {
        headers: authHeaders(secret),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`${res.status}: ${body.slice(0, 200)}`);
      }
      const body = (await res.json()) as { items?: RecentItem[]; total?: number };
      setRecent(body.items || []);
      setTotal(typeof body.total === "number" ? body.total : (body.items || []).length);
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
      const signal = beginLoad(id);
      if (!signal) return;
      const trimmed = id.trim();
      setError(null);
      try {
        const res = await fetch(`/api/v1/ops/retrieval/turns/${encodeURIComponent(trimmed)}`, {
          headers: authHeaders(secret),
          signal,
        });
        if (!res.ok) {
          const body = await res.text();
          throw new Error(`${res.status}: ${body.slice(0, 200)}`);
        }
        const body = (await res.json()) as AuditResponse;
        if (isStale(trimmed, signal)) return;
        setData(body);
        endLoad(trimmed, true);
      } catch (e) {
        if (isStale(trimmed, signal)) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        setData(null);
        setError(e instanceof Error ? e.message : String(e));
        endLoad(trimmed, false);
      }
    },
    [secret, beginLoad, endLoad, isStale],
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
    if (fromQuery) {
      void loadTurn(fromQuery);
      return;
    }
    if (!listLoading && firstTurnId) {
      void loadTurn(firstTurnId);
    }
  }, [search, listLoading, firstTurnId, loadTurn]);

  const browse = useOpsTurnBrowse({
    turnIds,
    selectedId,
    onSelect: (id) => void loadTurn(id),
    enabled: Boolean(secret),
  });

  const download = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `retrieval-audit-${data.turn_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <OpsShell
      secret={secret}
      title="检索审计"
      subtitle="最近有检索的真实用户 Turn · 左右对照召回 / 排序 / 进窗（HM5）· 只读旁路"
    >
      <div className="space-y-3">
        <OpsListFilters
          searchPlaceholder="turn / session / 用户输入 / 检索 query…"
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
          extra={
            <button
              type="button"
              disabled={!data}
              onClick={download}
              className="rounded-md border border-border px-2.5 py-1.5 text-xs text-foreground hover:bg-muted disabled:opacity-50"
            >
              导出当前 JSON
            </button>
          }
        />

        {error ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <OpsMasterDetail
          listHeader="最近检索 Turn"
          list={
            !recent.length && !listLoading ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">
                {list.hasFilters
                  ? "没有匹配的 Turn，试试放宽筛选。"
                  : "暂无 retrieval.completed。先在工作台跑一轮 search_sources，再刷新。"}
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {recent.map((item) => (
                  <OpsTurnListItem
                    key={item.turn_id}
                    selected={selectedId === item.turn_id}
                    onClick={() => void loadTurn(item.turn_id)}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-medium text-foreground">
                        {item.last_query || item.user_preview || "(no query)"}
                      </span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {item.last_retrieval_at || "—"}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-muted-foreground">
                      <span>{item.scenario_id}</span>
                      <span>×{item.retrieval_count}</span>
                      {item.last_hit_count != null ? (
                        <span>hits={item.last_hit_count}</span>
                      ) : null}
                      <span className="truncate">{item.turn_id}</span>
                    </div>
                  </OpsTurnListItem>
                ))}
              </ul>
            )
          }
          listFooter={
            <details className="px-1 text-xs">
              <summary className="cursor-pointer text-muted-foreground">精确跳转</summary>
              <div className="mt-2 flex flex-wrap gap-2">
                <input
                  value={jumpId}
                  onChange={(e) => setJumpId(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void loadTurn(jumpId);
                  }}
                  placeholder="turn uuid"
                  className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs"
                />
                <button
                  type="button"
                  disabled={loading || !jumpId.trim()}
                  onClick={() => void loadTurn(jumpId)}
                  className="rounded-md border border-border px-2 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
                >
                  打开
                </button>
              </div>
            </details>
          }
          detailHeader={
            <div className="flex flex-wrap items-center justify-between gap-2">
              <OpsTurnNavButtons
                canPrev={browse.canPrev}
                canNext={browse.canNext}
                onPrev={browse.selectPrev}
                onNext={browse.selectNext}
                index={browse.index}
                total={turnIds.length}
              />
              {loading ? (
                <span className="text-xs text-muted-foreground">加载中…</span>
              ) : null}
            </div>
          }
          detail={
            data ? (
              <div className="space-y-4">
                <OpsTurnLinks secret={secret} turnId={data.turn_id} current="retrieval" />
                <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                  <div>turn={data.turn_id}</div>
                  <div>
                    session={data.session_id} · scenario={data.scenario_id} · status=
                    {data.status}
                  </div>
                  <div>
                    owner={data.owner_user_id || "—"} · work={data.work_id || "—"} · retrievals=
                    {data.retrieval_count}
                  </div>
                </div>

                {!data.retrievals.length ? (
                  <p className="text-sm text-muted-foreground">
                    该 Turn 无 retrieval.completed 事件。
                  </p>
                ) : null}

                {data.retrievals.map((item) => {
                  const audit = item.audit;
                  const diags = diagnoseRetrievalAudit(audit, item.hits);
                  const onlyL1 = new Set(layerOnlyIn(audit?.recall_pool, audit?.ranked));
                  const onlyL2 = new Set(layerOnlyIn(audit?.ranked, audit?.entered_context));
                  return (
                    <section
                      key={item.sequence}
                      className="space-y-2 rounded-lg border border-border bg-background p-3"
                    >
                      <header className="text-sm text-foreground">
                        <span className="font-medium">#{item.sequence}</span>
                        {item.step_index != null ? (
                          <span className="ml-2 text-muted-foreground">
                            step {item.step_index}
                          </span>
                        ) : null}
                        <span className="ml-2 text-muted-foreground">{item.mode}</span>
                        {item.query ? (
                          <span className="ml-2 break-words">「{item.query}」</span>
                        ) : null}
                      </header>
                      {item.summary ? (
                        <p className="text-xs text-muted-foreground">{item.summary}</p>
                      ) : null}
                      {diags.length ? (
                        <ul className="space-y-1">
                          {diags.map((d) => (
                            <li
                              key={d.id}
                              className={`rounded-md border px-2 py-1 text-[11px] ${
                                d.level === "warn"
                                  ? "border-warning/40 bg-warning/10 text-foreground"
                                  : "border-border bg-muted/40 text-muted-foreground"
                              }`}
                            >
                              {d.message}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      <div className="grid gap-2 md:grid-cols-3">
                        <HitList
                          title="L1 recall_pool"
                          rows={audit?.recall_pool ?? []}
                          highlightKeys={onlyL1}
                        />
                        <HitList
                          title="L2 ranked"
                          rows={audit?.ranked ?? []}
                          highlightKeys={onlyL2}
                        />
                        <HitList
                          title="L3 entered_context"
                          rows={audit?.entered_context ?? item.hits ?? []}
                        />
                      </div>
                      {audit?.rank_method ? (
                        <p className="text-[11px] text-muted-foreground">
                          rank_method={audit.rank_method}
                        </p>
                      ) : null}
                    </section>
                  );
                })}
              </div>
            ) : null
          }
          emptyDetail={
            <p className="text-sm text-muted-foreground">
              {listLoading ? "加载列表…" : "选择左侧一条 Turn 查看检索审计。"}
            </p>
          }
        />

        <OpsListPagination
          page={list.page}
          total={total}
          itemCount={recent.length}
          onPage={list.goPage}
        />
      </div>
    </OpsShell>
  );
}
