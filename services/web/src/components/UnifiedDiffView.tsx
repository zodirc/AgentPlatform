import { useEffect, useMemo, useRef, useState } from "react";
import {
  buildUnifiedDiffLines,
  countDiffChanges,
  type DiffLine,
} from "./unifiedDiff";

type Props = {
  oldText: string;
  newText: string;
  /** Max height CSS class for the scroll area. */
  maxHeightClass?: string;
  className?: string;
  /** Stretch scroll area to fill a flex parent (modal). */
  fillHeight?: boolean;
  /** Case-insensitive substring highlight on matching lines. */
  highlightQuery?: string;
  /** Absolute index into the full unified line list to scroll into view. */
  activeLineIndex?: number | null;
};

function lineClass(
  kind: DiffLine["kind"],
  highlighted: boolean,
  active: boolean,
): string {
  const base =
    kind === "add"
      ? "bg-success/15 text-foreground"
      : kind === "del"
        ? "bg-destructive/15 text-foreground"
        : "bg-transparent text-muted-foreground";
  if (active) return `${base} ring-1 ring-inset ring-warning`;
  if (highlighted) return `${base} bg-warning/10`;
  return base;
}

function gutterPrefix(kind: DiffLine["kind"]): string {
  if (kind === "add") return "+";
  if (kind === "del") return "-";
  return " ";
}

export function UnifiedDiffView({
  oldText,
  newText,
  maxHeightClass = "max-h-72",
  className = "",
  fillHeight = false,
  highlightQuery,
  activeLineIndex = null,
}: Props) {
  const [changesOnly, setChangesOnly] = useState(false);
  const activeRef = useRef<HTMLTableRowElement | null>(null);
  const allLines = useMemo(
    () => buildUnifiedDiffLines(oldText, newText),
    [oldText, newText],
  );
  const { additions, deletions } = useMemo(
    () => countDiffChanges(allLines),
    [allLines],
  );
  const needle = highlightQuery?.trim().toLowerCase() ?? "";

  const visible = useMemo(() => {
    return allLines
      .map((line, index) => ({ line, index }))
      .filter(({ line }) => (changesOnly ? line.kind !== "context" : true));
  }, [allLines, changesOnly]);

  useEffect(() => {
    if (activeLineIndex == null) return;
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeLineIndex, changesOnly, needle]);

  const identical = additions === 0 && deletions === 0;

  return (
    <div
      className={`${fillHeight ? "flex min-h-0 flex-1 flex-col" : ""} ${className}`}
    >
      <div className="mb-1.5 flex shrink-0 flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          {identical ? (
            "无行级变更"
          ) : (
            <>
              <span className="text-success">+{additions}</span>
              {" · "}
              <span className="text-destructive">−{deletions}</span>
              {" · "}
              {allLines.length} 行
            </>
          )}
        </p>
        {!identical ? (
          <button
            type="button"
            className="text-[11px] text-primary hover:underline"
            onClick={() => setChangesOnly((v) => !v)}
          >
            {changesOnly ? "显示上下文" : "仅改动行"}
          </button>
        ) : null}
      </div>
      <div
        className={`scrollbar-panel overflow-auto rounded border border-border bg-card font-mono text-[11px] leading-5 ${maxHeightClass}`}
      >
        {visible.length === 0 ? (
          <p className="p-2 text-muted-foreground">（空）</p>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {visible.map(({ line, index }) => {
                const hit =
                  Boolean(needle) && line.text.toLowerCase().includes(needle);
                const active = activeLineIndex === index;
                return (
                  <tr
                    key={index}
                    ref={active ? activeRef : undefined}
                    className={lineClass(line.kind, hit, active)}
                  >
                    <td className="select-none whitespace-nowrap border-r border-border/60 px-1.5 text-right tabular-nums text-muted-foreground/80">
                      {line.oldLine ?? ""}
                    </td>
                    <td className="select-none whitespace-nowrap border-r border-border/60 px-1.5 text-right tabular-nums text-muted-foreground/80">
                      {line.newLine ?? ""}
                    </td>
                    <td className="w-4 select-none px-1 text-center opacity-70">
                      {gutterPrefix(line.kind)}
                    </td>
                    <td className="whitespace-pre-wrap break-words px-2 py-0">
                      {line.text || " "}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
