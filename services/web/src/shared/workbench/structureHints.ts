/**
 * UX-only structure hints for patch preview (docs/28 PX2).
 * Client-side only — never sent to the model / never changes tool success.
 */

export type StructureHint = {
  code: string;
  message: string;
};

const HEADING_RE = /^(#{1,6})\s+(\S.*)$/gm;
const PLACEHOLDER_RE = /\b(TODO|TBD|FIXME|xxx)\b/gi;
const HTML_TAG_RE = /<\/?[a-zA-Z][^>]*>/;

/** Deterministic structural warnings for proposed new_text (not style/NLI). */
export function structureHints(newText: string): StructureHint[] {
  const text = newText ?? "";
  const issues: StructureHint[] = [];
  if (!text.trim()) {
    issues.push({ code: "empty_document", message: "新文本为空" });
    return issues;
  }

  const headings: { level: number; title: string }[] = [];
  HEADING_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = HEADING_RE.exec(text)) !== null) {
    headings.push({ level: m[1].length, title: m[2].trim() });
  }

  let prevLevel: number | null = null;
  for (const h of headings) {
    if (prevLevel !== null && h.level > prevLevel + 1) {
      issues.push({
        code: "heading_skip",
        message: `标题层级从 h${prevLevel} 跳到 h${h.level}（近 ${h.title}）`,
      });
    }
    prevLevel = h.level;
  }

  const parts = text.split(/(?=^#{1,6}\s+\S.*$)/m);
  for (const part of parts) {
    const hm = part.match(/^(#{1,6})\s+(\S.*)$/m);
    if (!hm) continue;
    const level = hm[1].length;
    if (level < 2) continue;
    const body = part.slice(hm[0].length).trim();
    if (!body) {
      issues.push({
        code: "empty_section",
        message: `空章节：${hm[0].trim()}`,
      });
    }
  }

  const placeholders = text.match(PLACEHOLDER_RE);
  if (placeholders && placeholders.length > 0) {
    const uniq = [...new Set(placeholders.map((p) => p.toUpperCase()))];
    issues.push({
      code: "placeholder",
      message: `含占位符：${uniq.join(", ")}`,
    });
  }

  if (HTML_TAG_RE.test(text)) {
    issues.push({ code: "html_forbidden", message: "含原始 HTML 标签" });
  }

  return issues;
}
