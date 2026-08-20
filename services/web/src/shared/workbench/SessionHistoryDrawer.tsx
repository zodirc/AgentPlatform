import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteSession,
  deleteSessionsBulk,
  listSessions,
  type SessionListItem,
} from "../api/client";
import { Button } from "../../components/ui/button";

type Props = {
  open: boolean;
  currentSessionId: string | null;
  onClose: () => void;
  onSelect: (sessionId: string) => void;
  /** Called after deleting the currently open session so the workbench can switch away. */
  onDeletedCurrent: () => void;
};

type PeriodId = "none" | "today" | "7d" | "30d" | "older30" | "all";

const PERIOD_OPTIONS: Array<{ id: PeriodId; label: string }> = [
  { id: "none", label: "按时期筛选…" },
  { id: "today", label: "今天" },
  { id: "7d", label: "近 7 天" },
  { id: "30d", label: "近 30 天" },
  { id: "older30", label: "30 天以前" },
  { id: "all", label: "当前列表全部" },
];

function titleOf(item: SessionListItem): string {
  const raw = item.title?.trim() || item.last_user_preview?.trim();
  if (!raw) return "空会话";
  return raw.length > 48 ? `${raw.slice(0, 48)}…` : raw;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function startOfLocalDay(d = new Date()): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function matchesPeriod(item: SessionListItem, period: PeriodId): boolean {
  if (period === "none") return false;
  if (period === "all") return true;
  const ts = new Date(item.updated_at).getTime();
  if (Number.isNaN(ts)) return false;
  const now = Date.now();
  const day0 = startOfLocalDay().getTime();
  if (period === "today") return ts >= day0;
  if (period === "7d") return ts >= now - 7 * 24 * 60 * 60 * 1000;
  if (period === "30d") return ts >= now - 30 * 24 * 60 * 60 * 1000;
  if (period === "older30") return ts < now - 30 * 24 * 60 * 60 * 1000;
  return false;
}

export function SessionHistoryDrawer({
  open,
  currentSessionId,
  onClose,
  onSelect,
  onDeletedCurrent,
}: Props) {
  const queryClient = useQueryClient();
  const [bulkMode, setBulkMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [period, setPeriod] = useState<PeriodId>("none");
  const [bulkError, setBulkError] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["sessions", "mine"],
    queryFn: () => listSessions(50),
    enabled: open,
    staleTime: 10_000,
  });

  const items = useMemo(() => q.data ?? [], [q.data]);

  const removeOne = useMutation({
    mutationFn: (sessionId: string) => deleteSession(sessionId),
    onSuccess: (_data, sessionId) => {
      queryClient.setQueryData<SessionListItem[]>(["sessions", "mine"], (prev) =>
        (prev ?? []).filter((row) => row.id !== sessionId),
      );
      void queryClient.invalidateQueries({ queryKey: ["sessions", "mine"] });
      setSelected((prev) => {
        if (!prev.has(sessionId)) return prev;
        const next = new Set(prev);
        next.delete(sessionId);
        return next;
      });
      if (sessionId === currentSessionId) {
        onDeletedCurrent();
      }
    },
  });

  const removeMany = useMutation({
    mutationFn: (ids: string[]) => deleteSessionsBulk(ids),
    onSuccess: async ({ deleted, missing }, ids) => {
      const gone = new Set(deleted);
      if (gone.size > 0) {
        queryClient.setQueryData<SessionListItem[]>(["sessions", "mine"], (prev) =>
          (prev ?? []).filter((row) => !gone.has(row.id)),
        );
      }
      await queryClient.invalidateQueries({ queryKey: ["sessions", "mine"] });
      setSelected((prev) => {
        if (gone.size === 0) return prev;
        const next = new Set(prev);
        for (const id of gone) next.delete(id);
        return next;
      });
      if (deleted.length === 0 && ids.length > 0) {
        setBulkError("服务器没有删掉这些会话，请重试");
        return;
      }
      if (missing.length > 0) {
        setBulkError(`${missing.length} 条未找到或无权删除`);
      } else {
        setBulkError(null);
        setBulkMode(false);
        setPeriod("none");
        setSelected(new Set());
      }
      if (currentSessionId && gone.has(currentSessionId)) {
        onDeletedCurrent();
      }
    },
    onError: () => {
      setBulkError("批量删除失败，请稍后重试");
      void queryClient.invalidateQueries({ queryKey: ["sessions", "mine"] });
    },
  });

  const allSelected =
    items.length > 0 && items.every((item) => selected.has(item.id));

  const periodCount = useMemo(() => {
    if (period === "none") return 0;
    return items.filter((item) => matchesPeriod(item, period)).length;
  }, [items, period]);

  if (!open) return null;

  const exitBulk = () => {
    setBulkMode(false);
    setSelected(new Set());
    setPeriod("none");
    setBulkError(null);
  };

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (allSelected) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(items.map((item) => item.id)));
  };

  const applyPeriod = (next: PeriodId) => {
    setPeriod(next);
    if (next === "none") return;
    setSelected(
      new Set(
        items.filter((item) => matchesPeriod(item, next)).map((item) => item.id),
      ),
    );
  };

  const confirmDeleteOne = (item: SessionListItem) => {
    const label = titleOf(item);
    const ok = window.confirm(
      `确定删除会话「${label}」？\n将永久清除该会话的聊天记录，不可恢复。`,
    );
    if (!ok) return;
    removeOne.mutate(item.id);
  };

  const confirmDeleteSelected = () => {
    const ids = [...selected];
    if (ids.length === 0) return;
    const ok = window.confirm(
      `确定删除选中的 ${ids.length} 个会话？\n将永久清除这些会话的聊天记录，不可恢复。`,
    );
    if (!ok) return;
    setBulkError(null);
    removeMany.mutate(ids);
  };

  const busy = removeOne.isPending || removeMany.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-overlay"
      onClick={() => {
        if (!busy) onClose();
      }}
    >
      <aside
        className="flex h-full w-full max-w-md flex-col border-l border-border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">历史会话</h2>
          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              size="sm"
              variant={bulkMode ? "default" : "outline"}
              className="h-7 border-input px-2 text-xs"
              disabled={busy || (items.length === 0 && !bulkMode)}
              onClick={() => {
                if (bulkMode) exitBulk();
                else {
                  setBulkMode(true);
                  setBulkError(null);
                }
              }}
            >
              {bulkMode ? "完成" : "批量删除"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 border-input px-2 text-xs"
              disabled={busy}
              onClick={onClose}
            >
              关闭
            </Button>
          </div>
        </div>

        {bulkMode ? (
          <div className="space-y-2 border-b border-border px-4 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={items.length === 0 || busy}
                onClick={selectAll}
              >
                {allSelected ? "取消全选" : "全选"}
              </Button>
              <select
                className="h-7 min-w-[8.5rem] rounded-md border border-input bg-background px-2 text-xs text-foreground"
                value={period}
                disabled={items.length === 0 || busy}
                aria-label="按时期选择会话"
                onChange={(e) => applyPeriod(e.target.value as PeriodId)}
              >
                {PERIOD_OPTIONS.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
              {period !== "none" ? (
                <span className="text-[11px] text-muted-foreground">
                  命中 {periodCount} 条
                </span>
              ) : null}
              <Button
                type="button"
                size="sm"
                variant="destructive"
                className="h-7 px-2 text-xs"
                disabled={selected.size === 0 || busy}
                onClick={confirmDeleteSelected}
              >
                {removeMany.isPending
                  ? "删除中…"
                  : `删除所选（${selected.size}）`}
              </Button>
            </div>
            <p className="text-[11px] text-muted-foreground">
              列表最多显示最近 50 条；按时期会勾选当前列表中符合条件的会话。
            </p>
          </div>
        ) : null}

        <div className="flex-1 overflow-y-auto p-3">
          {removeMany.isPending ? (
            <p className="mb-2 text-xs text-muted-foreground">
              正在后台清理会话数据…
            </p>
          ) : null}
          {q.isLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : null}
          {q.isError ? (
            <p className="text-sm text-destructive">加载失败，请稍后重试</p>
          ) : null}
          {removeOne.isError ? (
            <p className="mb-2 text-sm text-destructive">删除失败，请稍后重试</p>
          ) : null}
          {bulkError ? (
            <p className="mb-2 text-sm text-destructive">{bulkError}</p>
          ) : null}
          {!q.isLoading && items.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无历史会话</p>
          ) : null}
          <ul className="flex flex-col gap-2">
            {items.map((item) => {
              const active = item.id === currentSessionId;
              const deleting =
                (removeOne.isPending && removeOne.variables === item.id) ||
                (removeMany.isPending && selected.has(item.id));
              const checked = selected.has(item.id);
              return (
                <li key={item.id}>
                  <div
                    className={`flex items-stretch gap-1 rounded-lg border transition ${
                      active
                        ? "border-primary/50 bg-primary/15"
                        : "border-border bg-card/50 hover:border-input"
                    }`}
                  >
                    {bulkMode ? (
                      <label className="flex shrink-0 items-center px-2">
                        <input
                          type="checkbox"
                          className="size-3.5 accent-primary"
                          checked={checked}
                          disabled={busy}
                          aria-label={`选择会话 ${titleOf(item)}`}
                          onChange={() => toggleOne(item.id)}
                        />
                      </label>
                    ) : null}
                    <button
                      type="button"
                      className="min-w-0 flex-1 px-3 py-2 text-left"
                      onClick={() => {
                        if (bulkMode) {
                          toggleOne(item.id);
                          return;
                        }
                        onSelect(item.id);
                      }}
                      disabled={deleting}
                    >
                      <div className="text-sm text-foreground">{titleOf(item)}</div>
                      <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                        <span>{formatTime(item.updated_at)}</span>
                        <span>{item.turn_count} 轮</span>
                        <span>{item.default_scenario_id}</span>
                      </div>
                    </button>
                    {!bulkMode ? (
                      <button
                        type="button"
                        className="shrink-0 self-center px-2 py-2 text-[11px] text-muted-foreground hover:text-destructive disabled:opacity-40"
                        title="删除会话"
                        aria-label={`删除会话 ${titleOf(item)}`}
                        disabled={deleting || busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          confirmDeleteOne(item);
                        }}
                      >
                        {deleting ? "…" : "删除"}
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </aside>
    </div>
  );
}
