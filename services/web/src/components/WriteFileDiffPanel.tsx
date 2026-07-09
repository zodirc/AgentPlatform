import { useState } from "react";
import type { WriteFilePreview } from "../shared/workbench/types";
import { previewText } from "../shared/workbench/filePreview";

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
  const isPending = preview.status === "pending";
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

  const leftTitle = isNewFile ? "原文件（不存在）" : "原内容";
  const rightTitle =
    isPending || mode === "approval" ? "待写入内容" : "写入内容";

  return (
    <div className="rounded-lg border border-violet-800/60 bg-slate-950/80 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-violet-100">
            {preview.path || "（无路径）"}
          </p>
          <p className="text-xs text-slate-500">
            {isNewFile ? "新建文件" : "覆盖文件"}
            {preview.bytes_written != null
              ? ` · ${preview.bytes_written} 字节`
              : ""}
            {preview.new_size != null ? ` · 共 ${preview.new_size} 字符` : ""}
          </p>
        </div>
        <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
          {statusLabel}
        </span>
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        <div>
          <p className="mb-1 text-xs text-slate-500">{leftTitle}</p>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-slate-900 p-2 text-xs text-slate-300">
            {isNewFile ? "（无）" : oldPreview.text || "（空文件）"}
          </pre>
        </div>
        <div>
          <p className="mb-1 text-xs text-slate-500">{rightTitle}</p>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-slate-900 p-2 text-xs text-slate-200">
            {newPreview.text || "（无内容）"}
          </pre>
        </div>
      </div>

      {showExpand ? (
        <button
          type="button"
          className="mt-2 text-xs text-violet-300 hover:text-violet-200"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "收起预览" : "展开完整预览"}
        </button>
      ) : null}
    </div>
  );
}
