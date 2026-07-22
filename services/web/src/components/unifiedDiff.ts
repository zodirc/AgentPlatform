import { diffLines, type Change } from "diff";

export type DiffLineKind = "context" | "add" | "del";

export type DiffLine = {
  kind: DiffLineKind;
  text: string;
  /** 1-based line number in old file; null for pure additions. */
  oldLine: number | null;
  /** 1-based line number in new file; null for pure deletions. */
  newLine: number | null;
};

/**
 * Build Git-style unified diff lines from two text blobs.
 * Pure presentation helper — no agent path.
 */
export function buildUnifiedDiffLines(
  oldText: string,
  newText: string,
): DiffLine[] {
  const changes: Change[] = diffLines(oldText, newText);
  const lines: DiffLine[] = [];
  let oldLine = 1;
  let newLine = 1;

  for (const change of changes) {
    const parts = change.value.split("\n");
    // diffLines keeps a trailing empty segment when the chunk ends with \n
    if (parts.length > 0 && parts[parts.length - 1] === "") {
      parts.pop();
    }
    for (const part of parts) {
      if (change.added) {
        lines.push({
          kind: "add",
          text: part,
          oldLine: null,
          newLine: newLine++,
        });
      } else if (change.removed) {
        lines.push({
          kind: "del",
          text: part,
          oldLine: oldLine++,
          newLine: null,
        });
      } else {
        lines.push({
          kind: "context",
          text: part,
          oldLine: oldLine++,
          newLine: newLine++,
        });
      }
    }
  }
  return lines;
}

export function countDiffChanges(lines: DiffLine[]): {
  additions: number;
  deletions: number;
} {
  let additions = 0;
  let deletions = 0;
  for (const line of lines) {
    if (line.kind === "add") additions += 1;
    else if (line.kind === "del") deletions += 1;
  }
  return { additions, deletions };
}
