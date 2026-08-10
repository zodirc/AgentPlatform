import { useEffect, useRef, useState } from "react";
import { useTheme } from "./ThemeProvider";
import type { ThemeId } from "./theme";

type Props = {
  className?: string;
  /** Full chip row (settings / wide headers). Default: compact dropdown for nav. */
  variant?: "dropdown" | "grid";
};

/** Appearance switcher — local preference only, no agent-path impact. */
export function ThemeSwitcher({
  className = "",
  variant = "dropdown",
}: Props) {
  const { theme, setTheme, themes, meta } = useTheme();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (variant === "grid") {
    return (
      <div
        className={`grid gap-2 sm:grid-cols-2 lg:grid-cols-3 ${className}`}
        role="group"
        aria-label="外观主题"
      >
        {themes.map((id: ThemeId) => {
          const selected = theme === id;
          const m = meta[id];
          return (
            <button
              key={id}
              type="button"
              onClick={() => setTheme(id)}
              aria-pressed={selected}
              className={`rounded-lg border px-3 py-2.5 text-left transition-colors ${
                selected
                  ? "border-primary/50 bg-primary/10 ring-1 ring-primary/40"
                  : "border-border bg-background hover:bg-muted"
              }`}
            >
              <span className="flex items-center gap-2">
                <span
                  className="inline-flex h-4 w-4 overflow-hidden rounded-full border border-border/80"
                  aria-hidden
                >
                  <span
                    className="h-full w-1/2"
                    style={{ background: m.swatch.bg }}
                  />
                  <span
                    className="h-full w-1/2"
                    style={{ background: m.swatch.accent }}
                  />
                </span>
                <span className="text-sm font-medium text-foreground">
                  {m.label}
                </span>
              </span>
              <span className="mt-1 block text-[11px] text-muted-foreground">
                {m.description}
              </span>
            </button>
          );
        })}
      </div>
    );
  }

  const current = meta[theme];

  return (
    <div className={`relative ${className}`} ref={rootRef}>
      <button
        type="button"
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-2 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`外观：${current.label}`}
        title={current.description}
        onClick={() => setOpen((v) => !v)}
      >
        <span
          className="inline-flex h-3.5 w-3.5 overflow-hidden rounded-full border border-border/70"
          aria-hidden
        >
          <span
            className="h-full w-1/2"
            style={{ background: current.swatch.bg }}
          />
          <span
            className="h-full w-1/2"
            style={{ background: current.swatch.accent }}
          />
        </span>
        <span className="font-medium text-foreground/90">{current.label}</span>
        <span className="text-muted-foreground">▾</span>
      </button>
      {open ? (
        <div
          role="listbox"
          aria-label="选择外观主题"
          className="absolute right-0 top-full z-50 mt-1 w-[min(18rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border bg-popover py-1 shadow-xl"
        >
          <p className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            外观 · 仅本机显示
          </p>
          {themes.map((id: ThemeId) => {
            const selected = theme === id;
            const m = meta[id];
            return (
              <button
                key={id}
                type="button"
                role="option"
                aria-selected={selected}
                className={`flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors ${
                  selected
                    ? "bg-primary/12 text-foreground"
                    : "text-foreground/90 hover:bg-muted/70"
                }`}
                onClick={() => {
                  setTheme(id);
                  setOpen(false);
                }}
              >
                <span
                  className="mt-0.5 inline-flex h-4 w-4 shrink-0 overflow-hidden rounded-full border border-border/70"
                  aria-hidden
                >
                  <span
                    className="h-full w-1/2"
                    style={{ background: m.swatch.bg }}
                  />
                  <span
                    className="h-full w-1/2"
                    style={{ background: m.swatch.accent }}
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-xs font-medium">
                    {m.label}
                    <span className="text-[10px] font-normal text-muted-foreground">
                      {m.scheme === "dark" ? "深色" : "浅色"}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                    {m.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
