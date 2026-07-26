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
import {
  buildTimeline,
  messagesFromPayload,
  roleBadgeClass,
  toolCatalogNames,
  toolsFromPayload,
  type ContentSegment,
  type TimelineRow,
} from "./opsMessageParse";
import { formatJsonContent } from "./OpsTextViewerModal";

type ViewMode = "flow" | "json";

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
    if (m.start > cursor) nodes.push(content.slice(cursor, m.start));
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
  if (cursor < content.length) nodes.push(content.slice(cursor));
  return nodes;
}

function SegmentBody({ segment }: { segment: ContentSegment }) {
  if (segment.kind === "text") {
    return (
      <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">
        {segment.text || "（空）"}
      </pre>
    );
  }
  if (segment.kind === "tool_call") {
    let editOld = "";
    let editNew = "";
    if (segment.name === "edit_file" && segment.detail) {
      try {
        const parsed = JSON.parse(segment.detail) as Record<string, unknown>;
        editOld = typeof parsed.old_text === "string" ? parsed.old_text : "";
        editNew = typeof parsed.new_text === "string" ? parsed.new_text : "";
      } catch {
        /* keep raw detail */
      }
    }
    return (
      <div className="rounded-md border border-warning/30 bg-warning/5 px-2.5 py-2">
        <p className="text-[11px] font-medium text-foreground">
          调用工具 <span className="font-mono">{segment.name}</span>
        </p>
        {editOld || editNew ? (
          <div className="mt-2 space-y-2">
            <div>
              <p className="mb-0.5 text-[10px] font-medium text-destructive">− old_text</p>
              <pre className="whitespace-pre-wrap break-words rounded border border-destructive/20 bg-background/60 px-2 py-1.5 font-mono text-[11px] text-foreground">
                {editOld || "（空）"}
              </pre>
            </div>
            <div>
              <p className="mb-0.5 text-[10px] font-medium text-success">+ new_text</p>
              <pre className="whitespace-pre-wrap break-words rounded border border-success/20 bg-background/60 px-2 py-1.5 font-mono text-[11px] text-foreground">
                {editNew || "（空）"}
              </pre>
            </div>
          </div>
        ) : segment.detail ? (
          <pre className="mt-1.5 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-muted-foreground">
            {segment.detail}
          </pre>
        ) : (
          <p className="mt-1 text-[11px] text-muted-foreground">（无参数）</p>
        )}
      </div>
    );
  }
  if (segment.kind === "tool_result") {
    return (
      <div className="rounded-md border border-border bg-muted/30 px-2.5 py-2">
        {segment.toolUseId ? (
          <p className="mb-1 font-mono text-[10px] text-muted-foreground">
            tool_use_id={segment.toolUseId}
          </p>
        ) : null}
        <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-foreground">
          {segment.text || "（空结果）"}
        </pre>
      </div>
    );
  }
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-[11px] text-muted-foreground">
      {segment.text}
    </pre>
  );
}

function FlowPanel({
  rows,
  toolNames,
}: {
  rows: TimelineRow[];
  toolNames: string[];
}) {
  const [toolsOpen, setToolsOpen] = useState(false);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-muted/20 px-3 py-2.5 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">怎么读</p>
        <p className="mt-1 leading-relaxed">
          下面按 <span className="text-foreground">#1 → #N</span>{" "}
          就是模型当步读窗顺序：先系统与运行时注入，再历史
          user/assistant/tool，最末往往是最新用户句。每条展示
          <span className="text-foreground">完整原文</span>
          （文本 / 工具参数 / 工具回传），不截断。
        </p>
      </div>

      {toolNames.length ? (
        <div className="rounded-lg border border-border px-3 py-2">
          <button
            type="button"
            className="flex w-full items-center justify-between gap-2 text-left text-xs"
            onClick={() => setToolsOpen((v) => !v)}
          >
            <span className="text-foreground">
              本步工具菜单（{toolNames.length}）
              <span className="ml-1 font-normal text-muted-foreground">
                · 仅目录，调用见下方 assistant
              </span>
            </span>
            <span className="text-muted-foreground">{toolsOpen ? "收起" : "展开"}</span>
          </button>
          {toolsOpen ? (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {toolNames.map((n) => (
                <li
                  key={n}
                  className="rounded-md border border-border bg-muted/40 px-2 py-1 font-mono text-[11px]"
                >
                  {n}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
              {toolNames.join(" · ")}
            </p>
          )}
        </div>
      ) : null}

      {!rows.length ? (
        <p className="text-sm text-muted-foreground">无 messages。</p>
      ) : (
        <ol className="space-y-3">
          {rows.map((row) => (
            <li
              key={row.index}
              className="rounded-xl border border-border bg-card px-3 py-3 shadow-sm"
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                  #{row.index + 1}
                </span>
                <span
                  className={`rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${roleBadgeClass(row.kind)}`}
                >
                  {row.role}
                </span>
                <span className="text-xs font-medium text-foreground">{row.title}</span>
              </div>
              <div className="space-y-2">
                {row.segments.map((seg, i) => (
                  <SegmentBody key={`${row.index}-${i}`} segment={seg} />
                ))}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export type OpsPayloadViewerModalProps = {
  open: boolean;
  title: string;
  subtitle?: string;
  downloadName?: string;
  payload: unknown;
  onClose: () => void;
};

/** Single flow (full text) + optional raw JSON — no fragmented three-tab dump. */
export function OpsPayloadViewerModal({
  open,
  title,
  subtitle,
  downloadName,
  payload,
  onClose,
}: OpsPayloadViewerModalProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const activeMatchRef = useRef<HTMLElement | null>(null);

  const [mode, setMode] = useState<ViewMode>("flow");
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const jsonText = useMemo(() => formatJsonContent(payload), [payload]);
  const messages = useMemo(() => messagesFromPayload(payload), [payload]);
  const tools = useMemo(() => toolsFromPayload(payload), [payload]);
  const rows = useMemo(() => buildTimeline(messages), [messages]);
  const toolNames = useMemo(() => toolCatalogNames(tools), [tools]);

  const matches = useMemo(
    () => (mode === "json" ? findMatches(jsonText, query) : []),
    [mode, jsonText, query],
  );

  useEffect(() => {
    if (!open) return;
    setMode("flow");
    setSearchOpen(false);
    setQuery("");
    setActiveIndex(0);
    scrollRef.current?.scrollTo({ top: 0 });
  }, [open, title, payload]);

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
    setMode("json");
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
        return;
      }
      if (!searchOpen || mode !== "json") return;
      if (e.key === "Enter") {
        e.preventDefault();
        if (e.shiftKey) goPrev();
        else goNext();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, searchOpen, mode, openSearch, goNext, goPrev]);

  const onDownload = useCallback(() => {
    const name = downloadName || `${title.replace(/\s+/g, "-")}.json`;
    const blob = new Blob([jsonText], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }, [downloadName, jsonText, title]);

  if (!open) return null;

  const highlighted = renderHighlighted(
    jsonText,
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
        <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground">{title}</p>
            {subtitle ? (
              <p className="truncate font-mono text-xs text-muted-foreground">{subtitle}</p>
            ) : null}
          </div>
          <div className="flex rounded-md border border-border p-0.5 text-xs">
            <button
              type="button"
              className={`rounded px-2.5 py-1 ${
                mode === "flow"
                  ? "bg-primary/15 font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => {
                setMode("flow");
                setSearchOpen(false);
                setQuery("");
              }}
            >
              交互流程
            </button>
            <button
              type="button"
              className={`rounded px-2.5 py-1 ${
                mode === "json"
                  ? "bg-primary/15 font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setMode("json")}
            >
              原始 JSON
            </button>
          </div>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onDownload}
            title="下载完整 JSON"
            aria-label="下载"
          >
            <Download className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={openSearch}
            title="在 JSON 中查找 (Ctrl/⌘F)"
            aria-label="查找"
          >
            <Search className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
            title="关闭"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {searchOpen && mode === "json" ? (
          <div className="flex shrink-0 items-center gap-2 border-b border-border bg-muted/40 px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <Input
              ref={searchInputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="在 JSON 中查找…"
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
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted disabled:opacity-40"
              onClick={goPrev}
              disabled={matches.length === 0}
              aria-label="上一个匹配"
            >
              <ChevronUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted disabled:opacity-40"
              onClick={goNext}
              disabled={matches.length === 0}
              aria-label="下一个匹配"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted"
              onClick={() => {
                setSearchOpen(false);
                setQuery("");
              }}
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
          {mode === "flow" ? (
            <FlowPanel rows={rows} toolNames={toolNames} />
          ) : (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">
              {highlighted}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
