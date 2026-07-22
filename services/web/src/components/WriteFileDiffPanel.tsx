import { useState } from "react";
import type { WriteFilePreview } from "../shared/workbench/types";
import { previewText } from "../shared/workbench/filePreview";
import { DiffViewerModal } from "./DiffViewerModal";
import { UnifiedDiffView } from "./UnifiedDiffView";

type Props = {
  preview: WriteFilePreview;
  mode?: "approval" | "history";
};

const STATUS_LABEL: Record<string, string> = {
  pending: "待批准",
  applied: "已写入",
  denied: "已拒绝",
};

/** Soft cap for modal full-text diff (browser-side only). */
const FULL_CHAR_LIMIT = 200_000;
const FULL_LINE_LIMIT = 5_000;

export function WriteFileDiffPanel({ preview, mode = "history" }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const isNewFile = !preview.old_text.trim();
  const statusLabel =
    STATUS_LABEL[preview.status ?? ""] ?? preview.status ?? "unknown";

  const oldPreview = previewText(preview.old_text);
  const newPreview = previewText(preview.new_text);
  const compactTruncated =
    preview.truncated ||
    oldPreview.truncated ||
    newPreview.truncated ||
    (preview.new_size ?? 0) > 8000;

  const oldForDiff = isNewFile ? "" : oldPreview.text;
  const newForDiff = newPreview.text;

  const fullOld = previewText(preview.old_text, {
    charLimit: FULL_CHAR_LIMIT,
    lineLimit: FULL_LINE_LIMIT,
  });
  const fullNew = previewText(preview.new_text, {
    charLimit: FULL_CHAR_LIMIT,
    lineLimit: FULL_LINE_LIMIT,
  });

  return (
    <div className="rounded-lg border border-primary/40 bg-background/80 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-primary">
            {preview.path || "（无路径）"}
          </p>
          <p className="text-xs text-muted-foreground">
            {isNewFile ? "新建文件" : "覆盖文件"}
            {mode === "approval" ? " · 待批准" : ""}
            {preview.bytes_written != null
              ? ` · ${preview.bytes_written} 字节`
              : ""}
            {preview.new_size != null ? ` · 共 ${preview.new_size} 字符` : ""}
          </p>
        </div>
        <span className="rounded bg-muted px-2 py-0.5 text-xs text-foreground/90">
          {statusLabel}
        </span>
      </div>

      <UnifiedDiffView oldText={oldForDiff} newText={newForDiff} />

      <button
        type="button"
        className="mt-2 text-xs text-primary hover:underline"
        onClick={() => setModalOpen(true)}
      >
        {compactTruncated
          ? "在完整视图中打开（滚动 / 查找）"
          : "在完整视图中打开"}
      </button>

      <DiffViewerModal
        open={modalOpen}
        path={preview.path || "write_file"}
        oldText={isNewFile ? "" : fullOld.text}
        newText={fullNew.text}
        subtitle={
          fullOld.truncated || fullNew.truncated
            ? `${preview.path} · 内容过长已软截断`
            : preview.path
        }
        onClose={() => setModalOpen(false)}
      />
    </div>
  );
}
