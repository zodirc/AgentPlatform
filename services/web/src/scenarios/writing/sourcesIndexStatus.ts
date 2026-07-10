import type { SourcesIndexStatus } from "../../shared/api/client";

export type SourcesIndexStatusLabel = {
  text: string;
  tone: "pending" | "ok" | "err";
};

export function sourcesIndexStatusLabel(
  savedPath: string | null,
  status: SourcesIndexStatus | undefined,
  polling: boolean,
): SourcesIndexStatusLabel | null {
  if (!savedPath) return null;
  if (!status && polling) {
    return { text: `已保存 ${savedPath} · 正在确认索引…`, tone: "pending" };
  }
  if (!status) return { text: `已保存 ${savedPath}`, tone: "ok" };

  if (status.status === "error") {
    return {
      text: `已保存 ${savedPath} · 索引失败：${status.error || "未知错误"}`,
      tone: "err",
    };
  }
  if (
    status.status === "pending" ||
    status.status === "building" ||
    (polling && !status.path_current)
  ) {
    return {
      text:
        status.status === "pending"
          ? `已保存 ${savedPath} · 等待后台索引…`
          : `已保存 ${savedPath} · 索引重建中…`,
      tone: "pending",
    };
  }
  if (status.path_current || status.status === "ready") {
    const chunks = status.last_result?.chunks ?? status.chunks;
    return {
      text:
        chunks != null
          ? `已保存 ${savedPath} · 索引完成，可检索（${chunks} 块）`
          : `已保存 ${savedPath} · 索引完成，可检索`,
      tone: "ok",
    };
  }
  return { text: `已保存 ${savedPath}`, tone: "ok" };
}
