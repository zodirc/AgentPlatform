import { useEffect, useState } from "react";

import type { OpeningPondItem, OpeningPondsArtifact } from "./openingPonds";

type Props = {
  ponds: OpeningPondsArtifact | null;
  interactive?: boolean;
  disabled?: boolean;
  onSelect?: (item: OpeningPondItem) => void;
  onMore?: () => void;
};

function PondCard({
  item,
  expanded,
  onToggle,
  interactive,
  disabled,
  onSelect,
}: {
  item: OpeningPondItem;
  expanded: boolean;
  onToggle: () => void;
  interactive?: boolean;
  disabled?: boolean;
  onSelect?: (item: OpeningPondItem) => void;
}) {
  const blurb =
    item.summary ||
    [item.who, item.where].filter(Boolean).join(" · ") ||
    item.want ||
    item.chapter_job ||
    "";
  return (
    <li className="rounded-md border border-border/70 bg-background/80">
      <div className="flex w-full items-start gap-2 px-2.5 py-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-start gap-2 text-left hover:bg-muted/40"
          aria-expanded={expanded}
          onClick={onToggle}
        >
          <span
            className="mt-0.5 w-3 shrink-0 text-[10px] text-muted-foreground"
            aria-hidden
          >
            {expanded ? "▼" : "▶"}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-medium text-foreground">
              {item.title}
            </span>
            {!expanded && blurb ? (
              <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">
                {blurb}
              </span>
            ) : null}
          </span>
        </button>
        {interactive && onSelect && !expanded ? (
          <button
            type="button"
            className="shrink-0 self-center rounded-md bg-amber-600 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm hover:bg-amber-500 disabled:opacity-40"
            disabled={disabled}
            onClick={() => onSelect(item)}
          >
            采用
          </button>
        ) : null}
      </div>
      {expanded ? (
        <div className="space-y-1.5 border-t border-border/50 px-2.5 py-2 pl-7">
          {item.who ? (
            <p className="text-[12px] leading-relaxed text-foreground/90">
              <span className="text-muted-foreground">跟着谁 · </span>
              {item.who}
            </p>
          ) : null}
          {item.where ? (
            <p className="text-[12px] leading-relaxed text-foreground/90">
              <span className="text-muted-foreground">站在哪 · </span>
              {item.where}
            </p>
          ) : null}
          {item.want ? (
            <p className="text-[12px] leading-relaxed text-foreground/90">
              <span className="text-muted-foreground">眼下要什么 · </span>
              {item.want}
            </p>
          ) : null}
          {item.chapter_job ? (
            <p className="text-[12px] leading-relaxed text-foreground/90">
              <span className="text-muted-foreground">这一章 · </span>
              {item.chapter_job}
            </p>
          ) : null}
          {interactive && onSelect ? (
            <div className="flex justify-end pt-1">
              <button
                type="button"
                className="rounded-md bg-amber-600 px-3 py-1.5 text-[12px] font-semibold text-white shadow-sm hover:bg-amber-500 disabled:opacity-40"
                disabled={disabled}
                onClick={() => onSelect(item)}
              >
                采用此开篇
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export function OpeningPondsPanel({
  ponds,
  interactive = false,
  disabled = false,
  onSelect,
  onMore,
}: Props) {
  const items = ponds?.items ?? [];
  const firstId = items[0]?.id ?? null;
  const [open, setOpen] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(firstId);

  useEffect(() => {
    setOpen(true);
    setExpandedId(firstId);
  }, [ponds?.ponds_id, firstId]);

  if (items.length < 2) return null;

  return (
    <div className="rounded-lg border-l-[3px] border-l-amber-500 bg-amber-500/10 px-3 py-2.5">
      <button
        type="button"
        className="flex w-full items-start justify-between gap-2 rounded text-left hover:opacity-90"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-amber-800 dark:text-amber-200">
              开篇
            </span>
            <span className="text-[12px] font-medium text-foreground">
              开篇候选
            </span>
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {items.length} 个
            </span>
          </div>
          {interactive ? (
            <p className="mt-1 text-[11px] font-medium text-amber-800/90 dark:text-amber-200/90">
              点选一份写第一章，或要其他的
            </p>
          ) : (
            <p className="mt-1 text-[11px] text-muted-foreground">
              {ponds?.summary || "互不换皮的近池"}
            </p>
          )}
        </div>
      </button>
      {open ? (
        <>
          {ponds?.summary ? (
            <p className="mt-2 text-[12px] leading-relaxed text-foreground/80">
              {ponds.summary}
            </p>
          ) : null}
          <ul className="mt-2 space-y-1.5 border-t border-amber-500/20 pt-2">
            {items.map((item) => (
              <PondCard
                key={item.id}
                item={item}
                expanded={expandedId === item.id}
                onToggle={() =>
                  setExpandedId((cur) => (cur === item.id ? null : item.id))
                }
                interactive={interactive}
                disabled={disabled}
                onSelect={onSelect}
              />
            ))}
          </ul>
          {interactive && onMore ? (
            <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-amber-500/25 pt-2.5">
              <p className="text-[11px] text-amber-900/80 dark:text-amber-100/80">
                这几份都不对也可以换一组
              </p>
              <button
                type="button"
                className="shrink-0 rounded-md border border-amber-600/40 bg-background px-3 py-1.5 text-[12px] font-medium text-foreground hover:bg-muted disabled:opacity-40"
                disabled={disabled}
                onClick={onMore}
              >
                我要其他的
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
