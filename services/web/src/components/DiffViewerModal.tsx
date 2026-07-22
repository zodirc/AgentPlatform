import {
  ChevronDown,
  ChevronUp,
  Search,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Input } from "./ui/input";
import { UnifiedDiffView } from "./UnifiedDiffView";
import { buildUnifiedDiffLines } from "./unifiedDiff";

type Props = {
  open: boolean;
  path: string;
  oldText: string;
  newText: string;
  subtitle?: string;
  onClose: () => void;
};

export function DiffViewerModal({
  open,
  path,
  oldText,
  newText,
  subtitle,
  onClose,
}: Props) {
  const fileName = path.split("/").pop() || path || "diff";
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const matchIndexes = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [] as number[];
    const lines = buildUnifiedDiffLines(oldText, newText);
    const hits: number[] = [];
    lines.forEach((line, i) => {
      if (line.text.toLowerCase().includes(q)) hits.push(i);
    });
    return hits;
  }, [oldText, newText, query]);

  useEffect(() => {
    if (!open) return;
    setSearchOpen(false);
    setQuery("");
    setActiveIndex(0);
  }, [open, path, oldText, newText]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  const openSearch = useCallback(() => {
    setSearchOpen(true);
    requestAnimationFrame(() => searchInputRef.current?.focus());
  }, []);

  const goNext = useCallback(() => {
    if (matchIndexes.length === 0) return;
    setActiveIndex((i) => (i + 1) % matchIndexes.length);
  }, [matchIndexes.length]);

  const goPrev = useCallback(() => {
    if (matchIndexes.length === 0) return;
    setActiveIndex((i) => (i - 1 + matchIndexes.length) % matchIndexes.length);
  }, [matchIndexes.length]);

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
          return;
        }
        onClose();
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

  if (!open) return null;

  const activeLineIndex =
    matchIndexes.length > 0 ? matchIndexes[activeIndex] : null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`查看 diff ${path}`}
      onClick={onClose}
    >
      <div
        className="flex h-[min(90vh,900px)] w-[min(96vw,1100px)] flex-col overflow-hidden rounded-xl border border-input bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground">
              {fileName}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {subtitle ?? path}
            </p>
          </div>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={openSearch}
            title="查找 (Ctrl/⌘F)"
            aria-label="在 diff 中查找"
          >
            <Search className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
            title="关闭 (Esc)"
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
              placeholder="在 diff 中查找…"
              className="h-8 flex-1 bg-background text-sm"
              aria-label="查找内容"
            />
            <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
              {query.trim()
                ? matchIndexes.length === 0
                  ? "无结果"
                  : `${activeIndex + 1} / ${matchIndexes.length}`
                : "—"}
            </span>
            <button
              type="button"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
              onClick={goPrev}
              disabled={matchIndexes.length === 0}
              title="上一个 (Shift+Enter)"
            >
              <ChevronUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
              onClick={goNext}
              disabled={matchIndexes.length === 0}
              title="下一个 (Enter)"
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
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        <div className="scrollbar-panel flex min-h-0 flex-1 flex-col overflow-hidden bg-card/50 p-4">
          <UnifiedDiffView
            oldText={oldText}
            newText={newText}
            maxHeightClass="min-h-0 flex-1"
            fillHeight
            highlightQuery={query.trim() || undefined}
            activeLineIndex={activeLineIndex}
          />
        </div>
      </div>
    </div>
  );
}
