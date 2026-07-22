import { useMemo, useState } from "react";
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
};

function lineClass(kind: DiffLine["kind"]): string {
  if (kind === "add") {
    return "bg-success/15 text-foreground";
  }
  if (kind === "del") {
    return "bg-destructive/15 text-foreground";
  }
  return "bg-transparent text-muted-foreground";
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
}: Props) {
  const [changesOnly, setChangesOnly] = useState(false);
  const allLines = useMemo(
    () => buildUnifiedDiffLines(oldText, newText),
    [oldText, newText],
  );
  const { additions, deletions } = useMemo(
    () => countDiffChanges(allLines),
    [allLines],
  );
  const lines = useMemo(() => {
    if (!changesOnly) return allLines;
    return allLines.filter((l) => l.kind !== "context");
  }, [allLines, changesOnly]);

  const identical = additions === 0 && deletions === 0;

  return (
    <div className={className}>
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
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
        {lines.length === 0 ? (
          <p className="p-2 text-muted-foreground">（空）</p>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {lines.map((line, idx) => (
                <tr key={idx} className={lineClass(line.kind)}>
                  <td className="select-none whitespace-nowrap border-r border-border/60 px-1.5 text-right tabular-nums text-muted-foreground/80">
                    {line.oldLine ?? ""}
                  </td>
                  <td className="select-none whitespace-nowrap border-r border-border/60 px-1.5 text-right tabular-nums text-muted-foreground/80">
                    {line.newLine ?? ""}
                  </td>
                  <td className="select-none w-4 px-1 text-center opacity-70">
                    {gutterPrefix(line.kind)}
                  </td>
                  <td className="whitespace-pre-wrap break-words px-2 py-0">
                    {line.text || " "}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
