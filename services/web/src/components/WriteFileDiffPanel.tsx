import { useState } from "react";
import type { WriteFilePreview } from "../shared/workbench/types";
import { previewText } from "../shared/workbench/filePreview";
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

export function WriteFileDiffPanel({ preview, mode = "history" }: Props) {
  const [expanded, setExpanded] = useState(false);
  const isNewFile = !preview.old_text.trim();
  const statusLabel =
    STATUS_LABEL[preview.status ?? ""] ?? preview.status ?? "unknown";

  const oldPreview = previewText(preview.old_text, {
    charLimit: expanded ? 50000 : 8000,
    lineLimit: expanded ? 500 : 120,
  });
  const newPreview = previewText(preview.new_text, {
    charLimit: expanded ? 50000 : 8000,
    lineLimit: expanded ? 500 : 120,
  });
  const showExpand =
    preview.truncated ||
    oldPreview.truncated ||
    newPreview.truncated ||
    (preview.new_size ?? 0) > 8000;

  // Diff against truncated previews to keep browser work bounded.
  const oldForDiff = isNewFile ? "" : oldPreview.text;
  const newForDiff = newPreview.text;

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

      {showExpand ? (
        <button
          type="button"
          className="mt-2 text-xs text-primary hover:text-primary"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "收起预览" : "展开完整预览后重算 diff"}
        </button>
      ) : null}
    </div>
  );
}
