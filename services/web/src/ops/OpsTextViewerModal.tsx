import {
  ChevronDown,
  ChevronUp,
  Download,
  Search,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Input } from "../components/ui/input";

type MatchRange = { start: number; end: number };

function findMatches(content: string, query: string): MatchRange[] {
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

function renderHighlighted(
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

export type OpsTextViewerModalProps = {
  open: boolean;
  title: string;
  subtitle?: string;
  /** Filename hint for download, e.g. envelope-step-0.json */
  downloadName?: string;
  content: string;
  onClose: () => void;
};

/** File-viewer style modal for Ops JSON / text (same UX as workspace file preview). */
export function OpsTextViewerModal({
  open,
  title,
  subtitle,
  downloadName,
  content,
  onClose,
}: OpsTextViewerModalProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const activeMatchRef = useRef<HTMLElement | null>(null);

  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const matches = useMemo(() => findMatches(content, query), [content, query]);

  useEffect(() => {
    if (!open) return;
    setSearchOpen(false);
    setQuery("");
    setActiveIndex(0);
    scrollRef.current?.scrollTo({ top: 0 });
  }, [open, title, content]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (!searchOpen || matches.length === 0) return;
    activeMatchRef.current?.scrollIntoView({
      block: "center",
      behavior: "smooth",
    });
  }, [activeIndex, matches.length, searchOpen, query]);

  const goNext = useCallback(() => {
    if (matches.length === 0) return;
    setActiveIndex((i) => (i + 1) % matches.length);
  }, [matches.length]);

  const goPrev = useCallback(() => {
    if (matches.length === 0) return;
    setActiveIndex((i) => (i - 1 + matches.length) % matches.length);
  }, [matches.length]);

  const openSearch = useCallback(() => {
    setSearchOpen(true);
    requestAnimationFrame(() => searchInputRef.current?.focus());
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "f") {
        e.preventDefault();
        openSearch();
        return;
      }
      if (e.key === "Escape") {
        if (searchOpen) {
          e.preventDefault();
          setSearchOpen(false);
          setQuery("");
        }
        // Modal itself closes only via the X button (not Esc / backdrop).
        return;
      }
      if (!searchOpen) return;
      if (e.key === "Enter") {
        e.preventDefault();
        if (e.shiftKey) goPrev();
        else goNext();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, searchOpen, openSearch, goNext, goPrev]);

  const onDownload = useCallback(() => {
    const name = downloadName || `${title.replace(/\s+/g, "-")}.txt`;
    const blob = new Blob([content], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }, [content, downloadName, title]);

  if (!open) return null;

  const highlighted = renderHighlighted(
    content,
    searchOpen && query.trim() ? matches : [],
    activeIndex,
    (el) => {
      activeMatchRef.current = el;
    },
  );

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="flex h-[min(90vh,900px)] w-[min(96vw,1100px)] flex-col overflow-hidden rounded-xl border border-input bg-background shadow-2xl">
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground">{title}</p>
            {subtitle ? (
              <p className="truncate font-mono text-xs text-muted-foreground">{subtitle}</p>
            ) : null}
          </div>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onDownload}
            title="下载到本地"
            aria-label="下载"
          >
            <Download className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={openSearch}
            title="查找 (Ctrl/⌘F)"
            aria-label="查找"
          >
            <Search className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
            title="关闭 (Esc)"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {searchOpen ? (
          <div className="flex shrink-0 items-center gap-2 border-b border-border bg-muted/40 px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <Input
              ref={searchInputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="在内容中查找…"
              className="h-8 flex-1 bg-background text-sm"
              aria-label="查找内容"
            />
            <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
              {query.trim()
                ? matches.length === 0
                  ? "无结果"
                  : `${activeIndex + 1} / ${matches.length}`
                : "—"}
            </span>
            <button
              type="button"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
              onClick={goPrev}
              disabled={matches.length === 0}
              title="上一个 (Shift+Enter)"
              aria-label="上一个匹配"
            >
              <ChevronUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
              onClick={goNext}
              disabled={matches.length === 0}
              title="下一个 (Enter)"
              aria-label="下一个匹配"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={() => {
                setSearchOpen(false);
                setQuery("");
              }}
              title="关闭查找 (Esc)"
              aria-label="关闭查找"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        <div
          ref={scrollRef}
          className="scrollbar-panel min-h-0 flex-1 overflow-y-scroll overflow-x-auto bg-card/50 p-4"
        >
          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">
            {highlighted}
          </pre>
        </div>
      </div>
    </div>
  );
}

export function formatJsonContent(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
