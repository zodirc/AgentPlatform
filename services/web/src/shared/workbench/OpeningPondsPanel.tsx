import type { OpeningPondItem, OpeningPondsArtifact } from "./openingPonds";
import { pondContrastLine } from "./openingPonds";

type Props = {
  ponds: OpeningPondsArtifact | null;
  interactive?: boolean;
  disabled?: boolean;
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

function PondCard({
  item,
  interactive,
  disabled,
  onSelect,
}: {
  item: OpeningPondItem;
  interactive?: boolean;
  disabled?: boolean;
  onSelect?: (item: OpeningPondItem) => void;
}) {
  return (
    <li className="rounded-md border border-border/70 bg-background/80 px-2.5 py-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-[13px] font-medium text-foreground">{item.title}</p>
          {item.flavor ? (
            <p className="text-[12px] text-foreground/90">{item.flavor}</p>
          ) : null}
          <Field label="开篇" value={item.opening} />
          <Field label="走向" value={item.arc} />
          <Field label="跟着谁" value={item.who} />
          <Field label="站在哪" value={item.where} />
          <Field label="眼下要什么" value={item.want} />
        </div>
        {interactive && onSelect ? (
          <button
            type="button"
            className="shrink-0 self-start rounded-md bg-amber-600 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm hover:bg-amber-500 disabled:opacity-40"
            disabled={disabled}
            onClick={() => onSelect(item)}
          >
            采用
          </button>
        ) : null}
      </div>
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
            点选一份：开篇、走向和全篇气味；或要其他的
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
      <ul className="mt-2 space-y-1.5 border-t border-amber-500/20 pt-2">
        {items.map((item) => (
          <PondCard
            key={item.id}
            item={item}
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
    </div>
  );
}
