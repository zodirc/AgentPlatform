import type { WriteFilePreview } from "./types";

const PREVIEW_CHAR_LIMIT = 8000;
const PREVIEW_LINE_LIMIT = 120;

export function previewText(
  text: string,
  opts?: { charLimit?: number; lineLimit?: number },
): {
  text: string;
  truncated: boolean;
  totalChars: number;
  totalLines: number;
} {
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

export function artifactToWritePreview(
  item: Record<string, unknown>,
): WriteFilePreview {
  const toolName = String(item.tool_name ?? item.kind ?? "write_file");
  return {
    path: String(item.path ?? ""),
    old_text: String(item.old_text ?? ""),
    new_text: String(item.new_text ?? ""),
    status: String(item.status ?? "applied"),
    truncated: Boolean(item.truncated),
    new_size: typeof item.new_size === "number" ? item.new_size : undefined,
    bytes_written:
      typeof item.bytes_written === "number" ? item.bytes_written : undefined,
    kind:
      item.kind === "edit_file" || toolName === "edit_file"
        ? "edit_file"
        : "write_file",
  };
}

/** Build diff preview from approval.requested payload (write_file or edit_file). */
export function writePreviewFromApprovalPayload(
  payload: Record<string, unknown>,
): WriteFilePreview | null {
  const toolName = String(payload.tool_name ?? "");
  if (toolName !== "write_file" && toolName !== "edit_file") return null;
  const args = (payload.arguments ?? {}) as Record<string, unknown>;
  const path = String(payload.path ?? args.path ?? "");
  let newRaw = "";
  let oldRaw = "";
  if (toolName === "edit_file") {
    oldRaw = String(payload.old_text ?? args.old_text ?? "");
    newRaw = String(payload.new_text ?? args.new_text ?? "");
  } else {
    newRaw = String(payload.new_text ?? args.content ?? "");
    oldRaw = String(payload.old_text ?? "");
  }
  if (!path && !newRaw && !oldRaw) return null;
  const newPreview = previewText(newRaw);
  const oldPreview = previewText(oldRaw);
  return {
    path,
    old_text: oldPreview.text,
    new_text: newPreview.text,
    status: "pending",
    truncated: newPreview.truncated || oldPreview.truncated,
    new_size: newRaw.length,
    kind: toolName === "edit_file" ? "edit_file" : "write_file",
  };
}

/**
 * Resolve write/edit diff for a timeline row by matching projected file_write artifacts.
 * Prefer tool_call_id; fall back to path + tool name.
 */
export function writePreviewFromTimeline(
  item: Record<string, unknown>,
  artifacts: Array<Record<string, unknown>>,
): WriteFilePreview | null {
  const toolName = String(item.tool_name ?? "");
  if (toolName !== "write_file" && toolName !== "edit_file") return null;
  const toolCallId = item.tool_call_id;
  const fileWrites = artifacts.filter((a) => a.type === "file_write");
  let match: Record<string, unknown> | undefined;
  if (toolCallId != null && toolCallId !== "") {
    match = fileWrites.find((a) => a.tool_call_id === toolCallId);
  }
  if (!match) {
    const pathHint = String(item.path ?? item.output_path ?? "");
    match = fileWrites.find((a) => {
      const kind = String(a.kind ?? a.tool_name ?? "");
      if (kind && kind !== toolName) return false;
      if (!pathHint) return false;
      return String(a.path ?? "") === pathHint;
    });
  }
  if (!match) return null;
  const preview = artifactToWritePreview(match);
  if (!preview.path && !preview.old_text && !preview.new_text) return null;
  return preview;
}
