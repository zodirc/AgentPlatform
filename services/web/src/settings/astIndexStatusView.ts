import type { AstIndexStatus } from "../shared/api/client";

export function statusLabel(status: AstIndexStatus | undefined): string {
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
  if (s === "stale") {
    const parts = ["落后"];
    const del = status?.pending_delete ?? 0;
    const up = status?.pending_upsert ?? 0;
    const remaining = status?.catchup_remaining ?? del + up;
    if (del > 0) parts.push(`待删 ${del}`);
    if (up > 0) parts.push(`待更新 ${up}`);
    if (del === 0 && up === 0 && remaining > 0) {
      parts.push(`待处理 ${remaining}`);
    }
    const indexed = status?.files_indexed;
    if (indexed != null && indexed > 0) parts.push(`内存 ${indexed} 文件`);
    if (parts.length === 1) parts.push("后台追平中");
    return parts.join(" · ");
  }
  if (s === "error") {
    return status?.error ? `失败 · ${status.error}` : "失败";
  }
  if (s === "cold") return "未建索引";
  return s;
}

/** Catch-up uses remaining/total; cold build uses files_done/files_total. */
export function progressPercent(status: AstIndexStatus | undefined): number | null {
  const s = status?.status;
  if (s === "stale" || s === "scan_pending") {
    const remaining =
      status?.catchup_remaining ??
      (status?.pending_delete ?? 0) + (status?.pending_upsert ?? 0);
    const total = status?.catchup_total ?? 0;
    if (total > 0) {
      return Math.min(100, Math.max(0, Math.round(((total - remaining) / total) * 100)));
    }
    if (remaining > 0) return 0;
    return null;
  }
  const total = status?.files_total ?? 0;
  if (total <= 0) return null;
  const done = status?.files_done ?? 0;
  return Math.min(100, Math.round((done / total) * 100));
}

export function catchupHint(status: AstIndexStatus | undefined): string | null {
  if (!status || status.status !== "stale") return null;
  const remaining = status.catchup_remaining ?? 0;
  const running = status.jobs_running ?? 0;
  const pending = status.jobs_pending ?? 0;
  const stored = status.files_stored;
  const indexed = status.files_indexed;
  if (remaining > 0 && running === 0 && pending === 0) {
    return "后台索引器还没领取任务。确认 ast-indexer 已启动，或点「重建索引」。";
  }
  if (running > 0) {
    return stored != null && indexed != null
      ? `后台正在写库 · 库中 ${stored} 行 / 内存 ${indexed} 文件`
      : "后台正在写库";
  }
  if (pending > 0) {
    return `已排队 ${pending} 个后台任务`;
  }
  return null;
}
