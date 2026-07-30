import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

export const OPS_LIST_PAGE_SIZE = 30;

export type OpsListFilterDef = {
  key: string;
  label: string;
  options: { value: string; label: string }[];
};

const TURN_STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "running", label: "running" },
  { value: "completed", label: "completed" },
  { value: "failed", label: "failed" },
  { value: "cancelled", label: "cancelled" },
];

const SCENARIO_OPTIONS = [
  { value: "", label: "全部" },
  { value: "writing", label: "writing" },
  { value: "agent", label: "agent" },
  { value: "intel", label: "intel" },
];

/** Common turn-list filters for retrieval / envelope / raw. */
export const OPS_TURN_LIST_FILTERS: OpsListFilterDef[] = [
  { key: "status", label: "状态", options: TURN_STATUS_OPTIONS },
  { key: "scenario", label: "场景", options: SCENARIO_OPTIONS },
];

function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

export type OpsListParams = {
  q: string;
  page: number;
  offset: number;
  filters: Record<string, string>;
  setQInput: (v: string) => void;
  qInput: string;
  setFilter: (key: string, value: string) => void;
  goPage: (page: number) => void;
  clearFilters: () => void;
  hasFilters: boolean;
  queryString: (extra?: Record<string, string>) => string;
};

/**
 * URL-backed list params shared by Ops history / recent browse pages.
 * Preserves unrelated search keys (e.g. turn_id).
 */
export function useOpsListParams(
  filterKeys: string[],
  options?: { pageSize?: number; preserveKeys?: string[] },
): OpsListParams {
  const pageSize = options?.pageSize ?? OPS_LIST_PAGE_SIZE;
  const preserveKeys = options?.preserveKeys ?? ["turn_id"];
  const [searchParams, setSearchParams] = useSearchParams();

  const q = searchParams.get("q") ?? "";
  const page = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const filterKeySig = filterKeys.join("\0");
  const filters = useMemo(() => {
    const out: Record<string, string> = {};
    for (const key of filterKeySig.split("\0").filter(Boolean)) {
      out[key] = searchParams.get(key) ?? "";
    }
    return out;
  }, [filterKeySig, searchParams]);

  const [qInput, setQInput] = useState(q);
  const debouncedQ = useDebounced(qInput, 300);

  const patchParams = useCallback(
    (mutate: (params: URLSearchParams) => void) => {
      const params = new URLSearchParams(searchParams);
      mutate(params);
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  useEffect(() => {
    const next = debouncedQ.trim();
    if (next === q) return;
    patchParams((params) => {
      if (next) params.set("q", next);
      else params.delete("q");
      params.delete("page");
    });
  }, [debouncedQ, q, patchParams]);

  useEffect(() => {
    setQInput(q);
  }, [q]);

  const setFilter = useCallback(
    (key: string, value: string) => {
      patchParams((params) => {
        if (value) params.set(key, value);
        else params.delete(key);
        params.delete("page");
      });
    },
    [patchParams],
  );

  const goPage = useCallback(
    (next: number) => {
      patchParams((params) => {
        if (next <= 1) params.delete("page");
        else params.set("page", String(next));
      });
    },
    [patchParams],
  );

  const clearFilters = useCallback(() => {
    setQInput("");
    const params = new URLSearchParams();
    for (const key of preserveKeys) {
      const v = searchParams.get(key);
      if (v) params.set(key, v);
    }
    setSearchParams(params, { replace: true });
  }, [preserveKeys, searchParams, setSearchParams]);

  const hasFilters = Boolean(q.trim() || Object.values(filters).some(Boolean));

  const queryString = useCallback(
    (extra?: Record<string, string>) => {
      const params = new URLSearchParams({
        limit: String(pageSize),
        offset: String((page - 1) * pageSize),
        ...extra,
      });
      if (q.trim()) params.set("q", q.trim());
      for (const [key, value] of Object.entries(filters)) {
        if (value) params.set(key, value);
      }
      return params.toString();
    },
    [filters, page, pageSize, q],
  );

  return useMemo(
    () => ({
      q,
      page,
      offset: (page - 1) * pageSize,
      filters,
      setQInput,
      qInput,
      setFilter,
      goPage,
      clearFilters,
      hasFilters,
      queryString,
    }),
    [
      q,
      page,
      pageSize,
      filters,
      qInput,
      setFilter,
      goPage,
      clearFilters,
      hasFilters,
      queryString,
    ],
  );
}

export function OpsListFilters({
  searchPlaceholder,
  qInput,
  onQChange,
  filterDefs,
  filters,
  onFilterChange,
  hasFilters,
  onClear,
  total,
  page,
  pageSize = OPS_LIST_PAGE_SIZE,
  loading,
  onRefresh,
  extra,
}: {
  searchPlaceholder: string;
  qInput: string;
  onQChange: (v: string) => void;
  filterDefs: OpsListFilterDef[];
  filters: Record<string, string>;
  onFilterChange: (key: string, value: string) => void;
  hasFilters: boolean;
  onClear: () => void;
  total: number;
  page: number;
  pageSize?: number;
  loading?: boolean;
  onRefresh?: () => void;
  extra?: ReactNode;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="mb-4 flex flex-col gap-3 rounded-md border border-border bg-card/40 p-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-xs text-muted-foreground">
          搜索
          <input
            type="search"
            value={qInput}
            onChange={(e) => onQChange(e.target.value)}
            placeholder={searchPlaceholder}
            className="rounded-md border border-border bg-background px-2.5 py-1.5 text-sm text-foreground outline-none focus:border-primary"
          />
        </label>
        {filterDefs.map((def) => (
          <label
            key={def.key}
            className="flex flex-col gap-1 text-xs text-muted-foreground"
          >
            {def.label}
            <select
              value={filters[def.key] ?? ""}
              onChange={(e) => onFilterChange(def.key, e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
            >
              {def.options.map((opt) => (
                <option key={`${def.key}-${opt.value || "all"}`} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        ))}
        {extra}
        {onRefresh ? (
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="rounded-md border border-border px-2.5 py-1.5 text-xs text-foreground hover:bg-muted disabled:opacity-50"
          >
            {loading ? "刷新中…" : "刷新"}
          </button>
        ) : null}
        {hasFilters ? (
          <button
            type="button"
            onClick={onClear}
            className="rounded-md border border-border px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
          >
            清除筛选
          </button>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        共 <span className="text-foreground">{total}</span> 条
        {hasFilters ? "（当前筛选）" : ""}
        {total > 0 ? (
          <>
            {" "}
            · 第 {page}/{totalPages} 页
          </>
        ) : null}
      </p>
    </div>
  );
}

export function OpsListPagination({
  page,
  pageSize = OPS_LIST_PAGE_SIZE,
  total,
  itemCount,
  onPage,
}: {
  page: number;
  pageSize?: number;
  total: number;
  itemCount: number;
  onPage: (page: number) => void;
}) {
  if (total <= 0) return null;
  const offset = (page - 1) * pageSize;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="mt-3 flex items-center justify-between gap-2">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        className="rounded-md border border-border px-2.5 py-1.5 text-xs text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
      >
        上一页
      </button>
      <span className="text-xs text-muted-foreground">
        {offset + 1}–{Math.min(offset + itemCount, total)} / {total}
      </span>
      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
        className="rounded-md border border-border px-2.5 py-1.5 text-xs text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
      >
        下一页
      </button>
    </div>
  );
}
