import { useQuery } from "@tanstack/react-query";
import {
  formatEta,
  formatIngestionProgress,
  progressPercent,
} from "../scenarios/writing/sourcesIndexStatus";
import type { SourcesIndexStatus } from "../shared/api/client";

function authHeaders(secret: string): HeadersInit {
  return { Authorization: `Bearer ${secret}` };
}

async function fetchOpsIndexStatus(secret: string): Promise<SourcesIndexStatus> {
  const res = await fetch("/api/v1/ops/ingestion/index-status", {
    headers: authHeaders(secret),
  });
  if (!res.ok) {
    throw new Error(`ops index-status failed: ${res.status}`);
  }
  return res.json();
}

/** Read-only ingestion strip for Ops pages (IX3 — not an effect gate). */
export function OpsIngestionStrip({ secret }: { secret: string }) {
  const query = useQuery({
    queryKey: ["ops-ingestion-index-status", secret],
    queryFn: () => fetchOpsIndexStatus(secret),
    enabled: Boolean(secret),
    refetchInterval: (q) => {
      const data = q.state.data;
      if (
        data?.status === "building" ||
        data?.status === "pending" ||
        data?.progress?.status === "building"
      ) {
        return 1500;
      }
      return 8000;
    },
  });

  const status = query.data;
  const progress = status?.progress;
  const building =
    status?.status === "building" ||
    status?.status === "pending" ||
    progress?.status === "building";
  const pct = progressPercent(progress);
  const detail = formatIngestionProgress(progress);
  const eta = formatEta(progress?.eta_s ?? null);

  if (query.isError) {
    return (
      <div className="mb-4 rounded-md border border-border bg-card/40 px-3 py-2 text-xs text-muted-foreground">
        摄取状态不可用（{String((query.error as Error)?.message || "error")}）·
        plane=ingestion · effect_ready=false
      </div>
    );
  }

  if (!status) {
    return (
      <div className="mb-4 rounded-md border border-border bg-card/40 px-3 py-2 text-xs text-muted-foreground">
        摄取面 · 加载索引状态…
      </div>
    );
  }

  return (
    <div
      className="mb-4 rounded-md border border-border bg-card/40 px-3 py-2"
      aria-label="索引摄取状态"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted-foreground">
          索引摄取（Ingestion）
        </p>
        <p className="text-[11px] text-muted-foreground">
          plane=ingestion · effect_ready=false · 效果仍看 prod-bench
        </p>
      </div>
      <p
        className={`mt-1 text-sm ${
          status.status === "error"
            ? "text-destructive"
            : building
              ? "text-warning"
              : "text-foreground"
        }`}
      >
        {status.status === "error"
          ? `错误：${status.error || "unknown"}`
          : building
            ? detail || "投影进行中…"
            : `就绪 · ${status.indexed_files ?? "—"} 文件 · ${status.chunks ?? "—"} 块 · ${
                status.embedding_backend || "—"
              }`}
        {building && eta ? ` · 剩余 ${eta}` : null}
      </p>
      {building ? (
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary/70 transition-[width] duration-500"
            style={{ width: pct != null ? `${pct}%` : "30%" }}
          />
        </div>
      ) : null}
    </div>
  );
}
