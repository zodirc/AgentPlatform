import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAstIndexStatus,
  fetchDefaultWork,
  rebuildAstIndex,
  type AstIndexStatus,
} from "../shared/api/client";

function statusLabel(status: AstIndexStatus | undefined): string {
  const s = status?.status || "cold";
  if (s === "disabled") return "未启用";
  if (s === "building" || s === "scan_pending") {
    const done = status?.files_done ?? 0;
    const total = status?.files_total ?? 0;
    return total > 0 ? `构建中 · ${done}/${total}` : "构建中…";
  }
  if (s === "ready") {
    const n = status?.files_indexed ?? status?.files_done ?? status?.files_total;
    return n != null && n > 0 ? `就绪 · ${n} 文件` : "就绪";
  }
  if (s === "stale") return "落后 · 后台追平中";
  if (s === "error") {
    return status?.error ? `失败 · ${status.error}` : "失败";
  }
  if (s === "cold") return "未建索引";
  return s;
}

function progressPercent(status: AstIndexStatus | undefined): number | null {
  const total = status?.files_total ?? 0;
  if (total <= 0) return null;
  const done = status?.files_done ?? 0;
  return Math.min(100, Math.round((done / total) * 100));
}

/** Settings · 当前账号默认 Work 的 AST 索引进度（非 RAG）。 */
export function AstIndexSettingsCard() {
  const queryClient = useQueryClient();
  const work = useQuery({
    queryKey: ["works", "default"],
    queryFn: fetchDefaultWork,
    staleTime: 60_000,
  });
  const workId = work.data?.id;

  const indexQuery = useQuery({
    queryKey: ["ast-index-status", workId ?? "default"],
    queryFn: () =>
      fetchAstIndexStatus({
        enqueue: false,
        workId: workId,
      }),
    enabled: Boolean(workId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s === "building" || s === "cold" || s === "stale" || s === "scan_pending") {
        return 1500;
      }
      return 12_000;
    },
    retry: 1,
  });

  const rebuildMut = useMutation({
    mutationFn: () => rebuildAstIndex({ workId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ast-index-status"] });
    },
  });

  const status = indexQuery.data;
  const disabled =
    status?.enabled === false || status?.status === "disabled";
  const building =
    status?.status === "building" ||
    status?.status === "cold" ||
    status?.status === "scan_pending" ||
    status?.status === "stale";
  const pct = progressPercent(status);
  const barActive = building || (pct != null && pct < 100);

  return (
    <section
      className="rounded-xl border border-border bg-card/60 p-4"
      aria-label="工作区 AST 索引"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-medium text-foreground">
            工作区代码索引（AST）
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            仅当前账号的默认 Work；供 Agent 结构定位，与资料库 RAG
            无关。打开 Agent 工作台会按需冷启动。
          </p>
        </div>
        <button
          type="button"
          className="shrink-0 rounded border border-border bg-background px-3 py-1.5 text-xs text-foreground hover:bg-muted disabled:opacity-50"
          disabled={
            !workId || disabled || rebuildMut.isPending || indexQuery.isLoading
          }
          onClick={() => rebuildMut.mutate()}
        >
          {rebuildMut.isPending ? "已提交…" : "重建索引"}
        </button>
      </div>

      {!workId && work.isLoading ? (
        <p className="mt-4 text-xs text-muted-foreground">加载 Work…</p>
      ) : null}
      {work.isError ? (
        <p className="mt-4 text-xs text-destructive">无法加载默认 Work</p>
      ) : null}

      {workId ? (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span className="text-foreground">
              {indexQuery.isLoading && !status
                ? "读取状态…"
                : indexQuery.isError
                  ? "状态不可用"
                  : statusLabel(status)}
            </span>
            <span className="font-mono text-[11px] text-muted-foreground">
              {status?.generation != null
                ? `gen ${status.generation}`
                : null}
              {pct != null ? ` · ${pct}%` : null}
            </span>
          </div>

          <div
            className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct ?? undefined}
            aria-label="AST 索引进度"
          >
            <div
              className={`h-full rounded-full transition-[width] duration-500 ${
                status?.status === "error"
                  ? "bg-destructive/70"
                  : status?.status === "ready"
                    ? "bg-foreground/50"
                    : "bg-primary/70"
              }`}
              style={{
                width:
                  status?.status === "ready"
                    ? "100%"
                    : pct != null
                      ? `${pct}%`
                      : barActive
                        ? "35%"
                        : "0%",
                ...(barActive && pct == null
                  ? { animation: "pulse 1.4s ease-in-out infinite" }
                  : null),
              }}
            />
          </div>

          {status?.status === "error" && status.error ? (
            <p className="text-[11px] text-destructive">{status.error}</p>
          ) : null}
          {rebuildMut.isError ? (
            <p className="text-[11px] text-destructive">
              {(rebuildMut.error as Error)?.message || "重建失败"}
            </p>
          ) : null}
          {rebuildMut.isSuccess ? (
            <p className="text-[11px] text-muted-foreground">
              已排队重建；进度条会自动刷新。
            </p>
          ) : null}
          {disabled ? (
            <p className="text-[11px] text-muted-foreground">
              当前部署未启用工作区 AST 索引。
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
