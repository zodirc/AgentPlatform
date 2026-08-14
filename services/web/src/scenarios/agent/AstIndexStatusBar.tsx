import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchAstIndexStatus,
  fetchDefaultWork,
  type AstIndexStatus,
} from "../../shared/api/client";
import { progressPercent } from "../../settings/astIndexStatusView";

function labelFor(status: AstIndexStatus | undefined): string {
  const s = status?.status || "cold";
  if (s === "disabled") return "";
  if (s === "building" || s === "scan_pending") {
    const done = status?.files_done ?? 0;
    const total = status?.files_total ?? 0;
    return total > 0
      ? `代码索引 building (${done}/${total})`
      : "代码索引 building…";
  }
  if (s === "ready") return "代码索引 ready";
  if (s === "stale") {
    const del = status?.pending_delete ?? 0;
    const up = status?.pending_upsert ?? 0;
    const remaining = status?.catchup_remaining ?? del + up;
    if (del || up || remaining) {
      const bits = ["代码索引 stale"];
      if (del) bits.push(`待删 ${del}`);
      if (up) bits.push(`待更新 ${up}`);
      if (!del && !up && remaining) bits.push(`待处理 ${remaining}`);
      return bits.join(" · ");
    }
    return "代码索引 stale（后台追平）";
  }
  if (s === "error") return `代码索引 error${status?.error ? ` · ${status.error}` : ""}`;
  if (s === "cold") return "代码索引 cold";
  return `代码索引 ${s}`;
}

/** Collapsible AST index progress — agent-workbench only (§6.2). Not RAG. */
export function AstIndexStatusBar() {
  const [collapsed, setCollapsed] = useState(false);
  const work = useQuery({
    queryKey: ["works", "default"],
    queryFn: fetchDefaultWork,
    staleTime: 60_000,
  });
  const workId = work.data?.id;
  const query = useQuery({
    queryKey: ["ast-index-status", workId ?? "default"],
    queryFn: () =>
      fetchAstIndexStatus({ enqueue: true, workId: workId }),
    enabled: Boolean(workId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      const remaining = q.state.data?.catchup_remaining ?? 0;
      if (
        s === "building" ||
        s === "cold" ||
        s === "stale" ||
        s === "scan_pending" ||
        remaining > 0
      ) {
        return 1500;
      }
      return 12_000;
    },
    retry: 1,
  });

  const status = query.data;
  if (!status || status.enabled === false || status.status === "disabled") {
    return null;
  }
  if (collapsed && status.status === "ready") {
    return null;
  }

  const text = labelFor(status);
  if (!text) return null;

  const catchingUp =
    status.status === "building" ||
    status.status === "cold" ||
    status.status === "stale" ||
    status.status === "scan_pending" ||
    (status.catchup_remaining ?? 0) > 0;
  const pct = progressPercent(status);

  return (
    <div
      className="shrink-0 border-b border-border px-4 py-1.5"
      aria-label="工作区 AST 索引进度"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] text-muted-foreground">{text}</p>
        <button
          type="button"
          className="text-[10px] text-muted-foreground hover:text-foreground"
          onClick={() => setCollapsed(true)}
        >
          收起
        </button>
      </div>
      {catchingUp ? (
        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-foreground/40 transition-[width] duration-500"
            style={{
              width: pct != null ? `${Math.max(pct, pct === 0 ? 4 : 0)}%` : "30%",
              ...(pct == null || pct === 0
                ? { animation: "pulse 1.4s ease-in-out infinite" }
                : null),
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
