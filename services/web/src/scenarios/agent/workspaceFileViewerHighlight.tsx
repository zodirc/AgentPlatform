import { EditorView } from "@codemirror/view";
import type { ReactNode } from "react";

export type MatchRange = { start: number; end: number };

export const FONT_MIN = 11;
export const FONT_MAX = 28;
export const FONT_DEFAULT = 13;
export const FONT_STEP = 1;

export function findMatches(content: string, query: string): MatchRange[] {
  const q = query.trim();
  if (!q || !content) return [];
  const lower = content.toLowerCase();
  const needle = q.toLowerCase();
  const out: MatchRange[] = [];
  let from = 0;
  while (from <= lower.length - needle.length) {
    const i = lower.indexOf(needle, from);
    if (i < 0) break;
    out.push({ start: i, end: i + needle.length });
    from = i + Math.max(needle.length, 1);
  }
  return out;
}

export function renderHighlighted(
  content: string,
  matches: MatchRange[],
  activeIndex: number,
  setActiveEl: (el: HTMLElement | null) => void,
): ReactNode {
  if (!matches.length) return content;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  matches.forEach((m, i) => {
    if (m.start > cursor) {
      nodes.push(content.slice(cursor, m.start));
    }
    const active = i === activeIndex;
    nodes.push(
      <mark
        key={`${m.start}-${i}`}
        ref={active ? setActiveEl : undefined}
        className={
          active
            ? "rounded-sm bg-warning px-0.5 text-warning-foreground"
            : "rounded-sm bg-primary/25 px-0.5 text-foreground"
        }
      >
        {content.slice(m.start, m.end)}
      </mark>,
    );
    cursor = m.end;
  });
  if (cursor < content.length) {
    nodes.push(content.slice(cursor));
  }
  return nodes;
}

/** Shared monospace look for read <pre> and edit CodeMirror. */
export function viewerTypography(fontSize: number) {
  return {
    fontSize: `${fontSize}px`,
    lineHeight: 1.65,
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  } as const;
}

/** Explicit px theme so zoom beats global `.cm-content { font-size: 12px }` and triggers CM remeasure. */
export function viewerFontTheme(fontSize: number) {
  const typo = viewerTypography(fontSize);
  return EditorView.theme({
    "&": {
      height: "100%",
      fontSize: typo.fontSize,
      backgroundColor: "transparent",
    },
    "&.cm-focused": { outline: "none" },
    ".cm-scroller": {
      fontFamily: typo.fontFamily,
      lineHeight: String(typo.lineHeight),
      overflow: "auto",
    },
    ".cm-content": {
      fontFamily: typo.fontFamily,
      fontSize: typo.fontSize,
      lineHeight: String(typo.lineHeight),
      padding: "1.25rem",
      caretColor: "hsl(var(--foreground))",
      color: "hsl(var(--foreground))",
    },
    ".cm-line": {
      padding: "0",
    },
    ".cm-cursor": {
      borderLeftColor: "hsl(var(--foreground))",
    },
    ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
      backgroundColor: "hsl(var(--primary) / 0.28) !important",
    },
  });
}
