import type { OpeningPondItem, OpeningPondsArtifact } from "./openingPonds";
import { pondContrastLine, pondItemSelected } from "./openingPonds";

type Props = {
  ponds: OpeningPondsArtifact | null;
  interactive?: boolean;
  disabled?: boolean;
  selectedTitle?: string | null;
  choseMore?: boolean;
  onSelect?: (item: OpeningPondItem) => void;
  onMore?: () => void;
};

function Field({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <p className="text-[12px] leading-relaxed text-foreground/90">
      <span className="text-muted-foreground">{label} · </span>
      {value}
    </p>
  );
}

function ChoiceMark({ checked }: { checked: boolean }) {
  return (
    <span
      className={`mt-0.5 shrink-0 text-[13px] font-medium ${
        checked
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-muted-foreground"
      }`}
      aria-hidden
    >
      {checked ? "✓" : "○"}
    </span>
  );
}

function PondCard({
  item,
  interactive,
  disabled,
  selected,
  onSelect,
}: {
  item: OpeningPondItem;
  interactive?: boolean;
  disabled?: boolean;
  selected: boolean;
  onSelect?: (item: OpeningPondItem) => void;
}) {
  const clickable = Boolean(interactive && onSelect);
  const frame = `flex w-full items-start gap-2 rounded-md border px-2.5 py-2 text-left ${
    selected
      ? "border-amber-500 bg-amber-500/10"
      : "border-border/70 bg-background/80"
  }`;
  const body = (
    <>
      <ChoiceMark checked={selected} />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="text-[13px] font-medium text-foreground">{item.title}</p>
        <Field label="这本书" value={item.flavor} />
        <Field label="开篇" value={item.opening} />
      </div>
    </>
  );

  return (
    <li>
      {clickable ? (
        <button
          type="button"
          role="radio"
          aria-checked={selected}
          aria-label={`采用「${item.title}」`}
          className={`${frame} hover:border-amber-500/70 disabled:opacity-40`}
          disabled={disabled}
          onClick={() => onSelect?.(item)}
        >
          {body}
        </button>
      ) : (
        <div className={frame}>{body}</div>
      )}
    </li>
  );
}

export function OpeningPondsPanel({
  ponds,
  interactive = false,
  disabled = false,
  selectedTitle = null,
  choseMore = false,
  onSelect,
  onMore,
}: Props) {
  const items = ponds?.items ?? [];
  const contrast = pondContrastLine(items);

  if (items.length < 2) return null;

  return (
    <div className="rounded-lg border-l-[3px] border-l-amber-500 bg-amber-500/10 px-3 py-2.5">
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
            勾选一本要连载的书（这本书在玩什么 + 开篇怎么进）
          </p>
        ) : (
          <p className="mt-1 text-[11px] text-muted-foreground">
            {contrast || "对照轴不同的近池"}
          </p>
        )}
      </div>
      {contrast ? (
        <p className="mt-2 text-[12px] leading-relaxed text-foreground/80">
          {contrast}
        </p>
      ) : null}
      <ul
        className="mt-2 space-y-1.5 border-t border-amber-500/20 pt-2"
        role={interactive ? "radiogroup" : undefined}
        aria-label={interactive ? "开篇候选" : undefined}
      >
        {items.map((item) => (
          <PondCard
            key={item.id}
            item={item}
            interactive={interactive}
            disabled={disabled}
            selected={pondItemSelected(item, selectedTitle)}
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
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-amber-600/40 bg-background px-3 py-1.5 text-[12px] font-medium text-foreground hover:bg-muted disabled:opacity-40"
            disabled={disabled}
            aria-pressed={choseMore}
            onClick={onMore}
          >
            <ChoiceMark checked={choseMore} />
            我要其他的
          </button>
        </div>
      ) : null}
    </div>
  );
}
