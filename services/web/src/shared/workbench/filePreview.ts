import type { WriteFilePreview } from "./types";

const PREVIEW_CHAR_LIMIT = 8000;
const PREVIEW_LINE_LIMIT = 120;

export function previewText(
  text: string,
  opts?: { charLimit?: number; lineLimit?: number },
): { text: string; truncated: boolean; totalChars: number; totalLines: number } {
  const charLimit = opts?.charLimit ?? PREVIEW_CHAR_LIMIT;
  const lineLimit = opts?.lineLimit ?? PREVIEW_LINE_LIMIT;
  const totalChars = text.length;
  const lines = text.split("\n");
  const totalLines = lines.length;

  let out = text;
  let truncated = false;

  if (lines.length > lineLimit) {
    out = lines.slice(0, lineLimit).join("\n");
    truncated = true;
  }
  if (out.length > charLimit) {
    out = out.slice(0, charLimit);
    truncated = true;
  }
  if (truncated) {
    out = `${out}\n\n…（预览已截断，共 ${totalLines} 行 / ${totalChars} 字符）`;
  }

  return { text: out, truncated, totalChars, totalLines };
}

export function artifactToWritePreview(item: Record<string, unknown>): WriteFilePreview {
  return {
    path: String(item.path ?? ""),
    old_text: String(item.old_text ?? ""),
    new_text: String(item.new_text ?? ""),
    status: String(item.status ?? "applied"),
    truncated: Boolean(item.truncated),
    new_size: typeof item.new_size === "number" ? item.new_size : undefined,
    bytes_written: typeof item.bytes_written === "number" ? item.bytes_written : undefined,
  };
}
