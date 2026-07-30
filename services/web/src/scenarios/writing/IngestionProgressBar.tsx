import type { SourcesIndexStatus } from "../../shared/api/client";
import { progressPercent } from "./sourcesIndexStatus";

/** Compact ingestion progress bar (IX3 — never claims effect quality). */
export function IngestionProgressBar({
  status,
}: {
  status: SourcesIndexStatus | null | undefined;
}) {
  const progress = status?.progress;
  const building =
    status?.status === "building" ||
    status?.status === "pending" ||
    progress?.status === "building";
  if (!building && !progress) return null;

  const pct = progressPercent(progress);
  const show = building || (pct != null && pct < 100);
  if (!show) return null;

  return (
    <div className="mt-2 space-y-1" aria-label="索引摄取进度">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary/70 transition-[width] duration-500"
          style={{
            width: pct != null ? `${pct}%` : "35%",
            ...(pct == null
              ? { animation: "pulse 1.4s ease-in-out infinite" }
              : null),
          }}
        />
      </div>
      <p className="text-[10px] text-muted-foreground/90">
        摄取面进度 · 非效果闸（prod-bench / 难句）
      </p>
    </div>
  );
}
