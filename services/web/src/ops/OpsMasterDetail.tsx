import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from "react-router-dom";

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return Boolean(el.closest("[contenteditable='true']"));
}

/**
 * Browse turns in the current page list: prev/next + j/k / arrow keys.
 * Does not cross pages.
 */
export function useOpsTurnBrowse({
  turnIds,
  selectedId,
  onSelect,
  enabled = true,
}: {
  turnIds: string[];
  selectedId: string;
  onSelect: (turnId: string) => void;
  enabled?: boolean;
}) {
  const index = useMemo(() => {
    if (!selectedId) return -1;
    return turnIds.indexOf(selectedId);
  }, [turnIds, selectedId]);

  const canPrev = index > 0;
  const canNext = index >= 0 && index < turnIds.length - 1;

  const selectPrev = useCallback(() => {
    if (!canPrev) return;
    onSelect(turnIds[index - 1]!);
  }, [canPrev, index, onSelect, turnIds]);

  const selectNext = useCallback(() => {
    if (!canNext) return;
    onSelect(turnIds[index + 1]!);
  }, [canNext, index, onSelect, turnIds]);

  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      const key = e.key;
      if (key === "j" || key === "ArrowDown") {
        e.preventDefault();
        selectNext();
        return;
      }
      if (key === "k" || key === "ArrowUp") {
        e.preventDefault();
        selectPrev();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, selectNext, selectPrev]);

  return { index, canPrev, canNext, selectPrev, selectNext };
}

/** Write `?turn=` without clobbering other list params. */
export function useSetOpsTurnParam() {
  const [, setSearchParams] = useSearchParams();
  return useCallback(
    (turnId: string) => {
      const next = turnId.trim();
      if (!next) return;
      setSearchParams(
        (prev) => {
          if ((prev.get("turn") ?? "").trim() === next) return prev;
          const params = new URLSearchParams(prev);
          params.set("turn", next);
          return params;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
}

export function OpsTurnNavButtons({
  canPrev,
  canNext,
  onPrev,
  onNext,
  index,
  total,
}: {
  canPrev: boolean;
  canNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  index: number;
  total: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <button
        type="button"
        disabled={!canPrev}
        onClick={onPrev}
        className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
        title="上一条 (k / ↑)"
      >
        上一条
      </button>
      <button
        type="button"
        disabled={!canNext}
        onClick={onNext}
        className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
        title="下一条 (j / ↓)"
      >
        下一条
      </button>
      {total > 0 && index >= 0 ? (
        <span className="font-mono text-[11px] text-muted-foreground">
          {index + 1}/{total}
          <span className="ml-1.5 opacity-70">j/k</span>
        </span>
      ) : null}
    </div>
  );
}

/**
 * Mail-client style master–detail for Ops audit pages.
 * Put pagination under the grid (sibling), not inside the list pane.
 */
export function OpsMasterDetail({
  listHeader,
  list,
  listFooter,
  detailHeader,
  detail,
  emptyDetail,
}: {
  listHeader?: ReactNode;
  list: ReactNode;
  listFooter?: ReactNode;
  detailHeader?: ReactNode;
  detail: ReactNode | null;
  emptyDetail?: ReactNode;
}) {
  return (
    <div className="grid min-h-[min(70vh,720px)] gap-3 lg:grid-cols-[minmax(260px,360px)_minmax(0,1fr)] lg:items-stretch">
      <aside className="flex min-h-[240px] max-h-[50vh] flex-col overflow-hidden rounded-md border border-border lg:max-h-none lg:min-h-0">
        {listHeader ? (
          <div className="shrink-0 border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
            {listHeader}
          </div>
        ) : null}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{list}</div>
        {listFooter ? (
          <div className="shrink-0 border-t border-border px-2 py-2">{listFooter}</div>
        ) : null}
      </aside>
      <section className="flex min-h-[280px] min-w-0 flex-col overflow-hidden rounded-md border border-border lg:min-h-0">
        {detailHeader ? (
          <div className="shrink-0 border-b border-border px-3 py-2">{detailHeader}</div>
        ) : null}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">
          {detail ?? emptyDetail ?? (
            <p className="text-sm text-muted-foreground">选择左侧一条 Turn 查看详情。</p>
          )}
        </div>
      </section>
    </div>
  );
}

/** Highlight selected row; scroll only if outside the list viewport. */
export function OpsTurnListItem({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const wasSelected = useRef(false);

  useEffect(() => {
    if (selected && !wasSelected.current) {
      const el = ref.current;
      const root = el?.closest(".overflow-y-auto");
      if (el && root instanceof HTMLElement) {
        const er = el.getBoundingClientRect();
        const rr = root.getBoundingClientRect();
        if (er.top < rr.top || er.bottom > rr.bottom) {
          el.scrollIntoView({ block: "nearest" });
        }
      }
    }
    wasSelected.current = selected;
  }, [selected]);

  return (
    <li>
      <button
        ref={ref}
        type="button"
        onClick={onClick}
        className={`w-full px-3 py-2 text-left text-sm hover:bg-muted/60 ${
          selected ? "bg-primary/10" : ""
        }`}
      >
        {children}
      </button>
    </li>
  );
}

/**
 * Shared selection + fetch guard for audit pages.
 * Prevents URL/selected oscillation when clicking 上一条/下一条.
 */
export function useOpsAuditTurnSelection(secret: string) {
  const [selectedId, setSelectedId] = useState("");
  const [jumpId, setJumpId] = useState("");
  const [loading, setLoading] = useState(false);
  const setTurnInUrl = useSetOpsTurnParam();
  const desiredRef = useRef("");
  const loadedRef = useRef("");
  const loadingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const beginLoad = useCallback(
    (id: string): AbortSignal | null => {
      const trimmed = id.trim();
      if (!trimmed || !secret) return null;
      // Same turn already loaded or in flight — do not restart (stops URL fight).
      if (trimmed === desiredRef.current) {
        setSelectedId(trimmed);
        setJumpId(trimmed);
        if (trimmed === loadedRef.current || loadingRef.current) return null;
      }

      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      desiredRef.current = trimmed;
      loadingRef.current = true;
      setSelectedId(trimmed);
      setJumpId(trimmed);
      setTurnInUrl(trimmed);
      setLoading(true);
      return ac.signal;
    },
    [secret, setTurnInUrl],
  );

  const endLoad = useCallback((id: string, ok: boolean) => {
    if (desiredRef.current !== id.trim()) return;
    if (ok) loadedRef.current = id.trim();
    else if (loadedRef.current === id.trim()) loadedRef.current = "";
    loadingRef.current = false;
    setLoading(false);
  }, []);

  const isStale = useCallback((id: string, signal?: AbortSignal) => {
    return Boolean(signal?.aborted || desiredRef.current !== id.trim());
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  return {
    selectedId,
    jumpId,
    setJumpId,
    loading,
    beginLoad,
    endLoad,
    isStale,
  };
}
