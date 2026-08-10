import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { OpsShell, secretFromOpsPath, turnIdFromSearch } from "./OpsShell";
import { OpsTurnLinks } from "./OpsTurnLinks";
import { OpsPayloadViewerModal } from "./OpsPayloadViewerModal";
import { opsDisplayText } from "./opsDisplayText";
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

type EnvelopeItem = {
  step_index: number;
  content_hash: string;
  fill_ratio?: number | null;
  has_full_envelope: boolean;
  envelope?: unknown;
  created_at?: string | null;
};

type EnvelopeResponse = {
  turn_id: string;
  count: number;
  envelopes: EnvelopeItem[];
};

type RecentItem = {
  turn_id: string;
  session_id: string;
  scenario_id?: string;
  status?: string;
  user_preview?: string | null;
  owner_user_id?: string | null;
  envelope_count: number;
  full_count: number;
  last_at?: string | null;
  max_fill_ratio?: number | null;
};

type ViewerState = {
  index: number;
};

function authHeaders(secret: string): HeadersInit {
  return { Authorization: `Bearer ${secret}` };
}

export function EnvelopeAuditPage() {
  const { pathname, search } = useLocation();
  const secret = secretFromOpsPath(pathname);
  const list = useOpsListParams(["within", "status", "scenario"]);
  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<EnvelopeResponse | null>(null);
  const [viewer, setViewer] = useState<ViewerState | null>(null);
  const {
    beginLoad,
    endLoad,
    isStale,
    selectedId,
    jumpId,
    setJumpId,
    loading,
  } = useOpsAuditTurnSelection(secret);

  const qs = opsTurnListQueryString(list);
  const turnIds = useMemo(() => recent.map((r) => r.turn_id), [recent]);
  const firstTurnId = recent[0]?.turn_id ?? "";
  const viewable = useMemo(
    () => (data?.envelopes || []).filter((e) => e.has_full_envelope),
    [data],
  );

  const loadRecent = useCallback(async () => {
    if (!secret) return;
    setListLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/ops/envelopes/recent?${qs}`, {
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
      if (body.error) setError(opsDisplayText(body.error));
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
      setViewer(null);
      setError(null);
      try {
        const res = await fetch(`/api/v1/ops/envelopes/turns/${encodeURIComponent(trimmed)}`, {
          headers: authHeaders(secret),
          signal,
        });
        if (!res.ok) {
          const body = await res.text();
          throw new Error(body || `HTTP ${res.status}`);
        }
        const body = (await res.json()) as EnvelopeResponse;
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
    enabled: Boolean(secret) && !viewer,
  });

  const openAt = (indexInViewable: number) => {
    if (indexInViewable < 0 || indexInViewable >= viewable.length) return;
    setViewer({ index: indexInViewable });
  };

  const openEnvelope = (item: EnvelopeItem) => {
    if (!item.has_full_envelope) return;
    const idx = viewable.findIndex(
      (e) => e.step_index === item.step_index && e.content_hash === item.content_hash,
    );
    if (idx >= 0) openAt(idx);
  };

  const activeItem = viewer ? viewable[viewer.index] : undefined;
  const turn = data?.turn_id || "";

  return (
    <OpsShell
      secret={secret}
      title="模型信封"
      subtitle="最近有信封落盘的 Turn · 点 step 行打开全文 · 只读旁路"
    >
      <div className="space-y-3">
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

        {error ? (
          <p className="text-sm text-destructive">{opsDisplayText(error)}</p>
        ) : null}

        <OpsMasterDetail
          listHeader="最近信封 Turn"
          list={
            !recent.length && !listLoading ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">
                {list.hasFilters
                  ? "没有匹配的 Turn，试试放宽筛选。"
                  : "暂无信封。跑一轮后刷新；full 行可点开查看。"}
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
                        {item.user_preview || "(no preview)"}
                      </span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {item.last_at || "—"}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-muted-foreground">
                      <span>{item.scenario_id}</span>
                      <span>
                        env={item.envelope_count} full={item.full_count}
                      </span>
                      {item.max_fill_ratio != null ? (
                        <span>max_fill={item.max_fill_ratio}</span>
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
                  className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs"
                  placeholder="turn uuid"
                  value={jumpId}
                  onChange={(e) => setJumpId(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void loadTurn(jumpId);
                  }}
                />
                <button
                  type="button"
                  className="rounded-md border border-border px-2 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
                  onClick={() => void loadTurn(jumpId)}
                  disabled={loading || !jumpId.trim()}
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
              <div className="space-y-3">
                <OpsTurnLinks secret={secret} turnId={data.turn_id} current="envelopes" />
                <p className="text-sm text-muted-foreground">
                  turn={data.turn_id} · envelopes={data.count}
                </p>
                {data.envelopes.map((item, i) => {
                  const clickable = item.has_full_envelope;
                  return (
                    <button
                      key={`${item.step_index}-${item.content_hash}-${i}`}
                      type="button"
                      disabled={!clickable}
                      onClick={() => openEnvelope(item)}
                      className={`w-full rounded-md border border-border bg-card px-3 py-2 text-left text-xs ${
                        clickable
                          ? "hover:bg-muted/60"
                          : "cursor-default opacity-70"
                      }`}
                    >
                      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
                        <span>step={item.step_index}</span>
                        <span className="truncate">hash={item.content_hash}</span>
                        {item.fill_ratio != null ? <span>fill={item.fill_ratio}</span> : null}
                        <span>{item.has_full_envelope ? "full" : "hash-only"}</span>
                        {clickable ? (
                          <span className="ml-auto text-muted-foreground">打开 →</span>
                        ) : null}
                      </div>
                    </button>
                  );
                })}
                {!data.envelopes.length ? (
                  <p className="text-sm text-muted-foreground">该 Turn 无信封记录。</p>
                ) : null}
              </div>
            ) : null
          }
          emptyDetail={
            <p className="text-sm text-muted-foreground">
              {listLoading ? "加载列表…" : "选择左侧一条 Turn 查看信封。"}
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

      <OpsPayloadViewerModal
        open={Boolean(viewer && activeItem)}
        title={activeItem ? `envelope · step ${activeItem.step_index}` : ""}
        subtitle={
          activeItem
            ? `${turn} · hash=${activeItem.content_hash.slice(0, 16)}…`
            : undefined
        }
        downloadName={
          activeItem
            ? `envelope-${turn.slice(0, 8)}-step-${activeItem.step_index}.json`
            : undefined
        }
        payload={activeItem?.envelope ?? null}
        onClose={() => setViewer(null)}
        canPrevItem={Boolean(viewer && viewer.index > 0)}
        canNextItem={Boolean(viewer && viewer.index < viewable.length - 1)}
        onPrevItem={() =>
          setViewer((v) => (v && v.index > 0 ? { index: v.index - 1 } : v))
        }
        onNextItem={() =>
          setViewer((v) =>
            v && v.index < viewable.length - 1 ? { index: v.index + 1 } : v,
          )
        }
        itemPositionLabel={
          viewer && viewable.length
            ? `${viewer.index + 1}/${viewable.length}`
            : undefined
        }
      />
    </OpsShell>
  );
}
