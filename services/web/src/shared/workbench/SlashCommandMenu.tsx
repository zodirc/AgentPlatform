import { useEffect, useRef } from "react";
import type { SlashCommand } from "../../shared/workbench/slashCommands";

type Props = {
  items: SlashCommand[];
  activeIndex: number;
  onActiveIndexChange: (index: number) => void;
  onSelect: (cmd: SlashCommand) => void;
  onDismiss: () => void;
};

export function SlashCommandMenu({
  items,
  activeIndex,
  onActiveIndexChange,
  onSelect,
  onDismiss,
}: Props) {
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-slash-index="${activeIndex}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  if (items.length === 0) {
    return (
      <div
        className="absolute bottom-full left-0 right-0 z-30 mb-2 overflow-hidden rounded-xl border border-border bg-popover shadow-xl"
        role="listbox"
        aria-label="斜杠命令"
      >
        <p className="px-3 py-2.5 text-xs text-muted-foreground">
          无匹配命令 · Esc 关闭
        </p>
      </div>
    );
  }

  return (
    <div
      className="absolute bottom-full left-0 right-0 z-30 mb-2 overflow-hidden rounded-xl border border-border bg-popover shadow-xl"
      role="listbox"
      aria-label="斜杠命令"
    >
      <div className="flex items-center justify-between border-b border-border/70 px-3 py-1.5">
        <p className="text-[11px] font-medium text-muted-foreground">命令</p>
        <button
          type="button"
          className="text-[11px] text-muted-foreground hover:text-foreground"
          onClick={onDismiss}
        >
          Esc
        </button>
      </div>
      <ul ref={listRef} className="max-h-56 overflow-y-auto py-1">
        {items.map((cmd, index) => {
          const active = index === activeIndex;
          return (
            <li key={cmd.id} role="option" aria-selected={active}>
              <button
                type="button"
                data-slash-index={index}
                className={`flex w-full items-start gap-3 px-3 py-2 text-left transition-colors ${
                  active
                    ? "bg-primary/15 text-foreground"
                    : "text-foreground/90 hover:bg-muted/60"
                }`}
                onMouseEnter={() => onActiveIndexChange(index)}
                onClick={() => onSelect(cmd)}
              >
                <span className="shrink-0 font-mono text-xs font-semibold text-primary">
                  {cmd.label}
                </span>
                <span className="min-w-0 flex-1 text-xs text-muted-foreground">
                  {cmd.description}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
