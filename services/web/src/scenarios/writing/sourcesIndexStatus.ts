import type {
  SourcesIndexProgress,
  SourcesIndexStatus,
} from "../../shared/api/client";

export type SourcesIndexStatusLabel = {
  text: string;
  tone: "pending" | "ok" | "err";
};

/** IX3: never imply upload/index-ready == retrieval quality. */
const EFFECT_DISCLAIMER = "效果闸仍看 prod-bench / 难句";

const PHASE_LABEL: Record<string, string> = {
  starting: "启动",
  loading_embedder: "加载嵌入模型",
  scope: "选择范围",
  scan: "扫描切块",
  plan: "计划嵌入",
  embed: "嵌入向量",
  write: "写入索引",
  finished: "完成",
  error: "失败",
};

export function formatEta(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) return `约 ${Math.ceil(seconds)}s`;
  const mins = Math.ceil(seconds / 60);
  return `约 ${mins} min`;
}

export function progressPercent(progress: SourcesIndexProgress | null | undefined): number | null {
  if (!progress) return null;
  const done = progress.chunks_embedded;
  const total = progress.chunks_total;
  if (
    done != null &&
    total != null &&
    Number.isFinite(done) &&
    Number.isFinite(total) &&
    total > 0
  ) {
    return Math.min(100, Math.max(0, (Number(done) / Number(total)) * 100));
  }
  const filesDone = progress.files_done;
  const filesTotal = progress.files_total;
  if (
    filesDone != null &&
    filesTotal != null &&
    Number.isFinite(filesDone) &&
    Number.isFinite(filesTotal) &&
    filesTotal > 0
  ) {
    return Math.min(100, Math.max(0, (Number(filesDone) / Number(filesTotal)) * 100));
  }
  return null;
}

/** Compact progress line for library / path status (ingestion plane). */
export function formatIngestionProgress(
  progress: SourcesIndexProgress | null | undefined,
): string | null {
  if (!progress) return null;
  const phase = progress.phase ? PHASE_LABEL[progress.phase] || progress.phase : null;
  const parts: string[] = [];
  if (phase) parts.push(phase);
  if (
    progress.chunks_embedded != null &&
    progress.chunks_total != null &&
    progress.chunks_total > 0
  ) {
    parts.push(`块 ${progress.chunks_embedded}/${progress.chunks_total}`);
  } else if (progress.files_done != null) {
    const total =
      progress.files_total != null ? `/${progress.files_total}` : "";
    parts.push(`文件 ${progress.files_done}${total}`);
  }
  if (progress.rate_chunks_per_s != null && progress.rate_chunks_per_s > 0) {
    parts.push(`${progress.rate_chunks_per_s}/s`);
  }
  const eta = formatEta(progress.eta_s);
  if (eta) parts.push(`剩余 ${eta}`);
  return parts.length ? parts.join(" · ") : null;
}

/** Per-path upload/paste status (ingestion plane). */
export function sourcesIndexStatusLabel(
  savedPath: string | null,
  status: SourcesIndexStatus | undefined,
  polling: boolean,
): SourcesIndexStatusLabel | null {
  if (!savedPath) return null;
  if (!status && polling) {
    return { text: `已保存 ${savedPath} · 正在确认投影…`, tone: "pending" };
  }
  if (!status) return { text: `已保存 ${savedPath}`, tone: "ok" };

  if (status.status === "error") {
    return {
      text: `已保存 ${savedPath} · 投影失败：${status.error || "未知错误"}`,
      tone: "err",
    };
  }
  if (
    status.status === "pending" ||
    status.status === "building" ||
    (polling && !status.path_current)
  ) {
    const detail = formatIngestionProgress(status.progress);
    return {
      text: detail
        ? `已保存 ${savedPath} · ${detail}`
        : status.status === "pending"
          ? `已保存 ${savedPath} · 等待后台投影…`
          : `已保存 ${savedPath} · 索引投影中…`,
      tone: "pending",
    };
  }
  if (status.path_current || status.status === "ready") {
    const chunks = status.last_result?.chunks ?? status.chunks;
    const base =
      chunks != null
        ? `已保存 ${savedPath} · 投影就绪（${chunks} 块，可被检索）`
        : `已保存 ${savedPath} · 投影就绪（可被检索）`;
    return {
      text: `${base} · ${EFFECT_DISCLAIMER}`,
      tone: "ok",
    };
  }
  return { text: `已保存 ${savedPath}`, tone: "ok" };
}

/** Library-wide sync status (IX1「同步资料库」; IX3 ingestion-only copy). */
export function libraryIndexStatusLabel(
  status: SourcesIndexStatus | undefined,
  polling: boolean,
): SourcesIndexStatusLabel | null {
  if (!status && polling) {
    return { text: "资料库索引投影中…", tone: "pending" };
  }
  if (!status) return null;

  if (status.status === "error") {
    return {
      text: `资料库投影失败：${status.error || "未知错误"}`,
      tone: "err",
    };
  }
  if (
    status.status === "pending" ||
    status.status === "building" ||
    polling
  ) {
    const detail = formatIngestionProgress(status.progress);
    return {
      text: detail
        ? `资料库投影中（不挡对话）· ${detail}`
        : "资料库索引投影中（不挡对话）…",
      tone: "pending",
    };
  }
  if (status.status === "ready" || status.status === "idle") {
    const files = status.indexed_files ?? status.last_result?.indexed_files;
    const chunks = status.chunks ?? status.last_result?.chunks;
    const parts: string[] = ["资料库投影就绪（摄取面）"];
    if (files != null) parts.push(`${files} 文件`);
    if (chunks != null) parts.push(`${chunks} 块`);
    const backend = status.embedding_backend;
    if (backend) parts.push(backend);
    parts.push(EFFECT_DISCLAIMER);
    return { text: parts.join(" · "), tone: "ok" };
  }
  return null;
}
