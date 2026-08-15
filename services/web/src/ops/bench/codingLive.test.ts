import { describe, expect, it } from "vitest";

import {
  EMPTY_CODING_HARNESS,
  formatAstIndexRows,
  formatCodingCaseStats,
  mergeAstIndexEntry,
  mergeCodingLiveState,
  parseAstIndexLine,
  parseCodingLiveLine,
  sumCodingCaseStats,
} from "./codingLive";
import type { CodingCaseLive } from "./types";

describe("parseCodingLiveLine", () => {
  it("parses per-case steps and elapsed_s on done lines", () => {
    expect(
      parseCodingLiveLine(
        "[L1] coding 2/5 astropy__astropy-14182 status=pass bucket=ok patch_source=git_diff steps=14 elapsed_s=182.5",
      ),
    ).toMatchObject({
      kind: "case",
      case: {
        iid: "astropy__astropy-14182",
        status: "pass",
        steps: 14,
        elapsedSec: 182.5,
        patchSource: "git_diff",
      },
    });
  });

  it("marks case start for live elapsed ticks", () => {
    const ev = parseCodingLiveLine("[L1] coding case start foo__bar-1");
    expect(ev?.kind).toBe("case");
    if (ev?.kind === "case") {
      expect(ev.case.status).toBe("running");
      expect(typeof ev.case.startedAtMs).toBe("number");
    }
  });
});

describe("sumCodingCaseStats", () => {
  it("sums finished steps/elapsed and live running elapsed", () => {
    const rows: CodingCaseLive[] = [
      {
        iid: "a",
        status: "pass",
        steps: 10,
        elapsedSec: 100,
      },
      {
        iid: "b",
        status: "running",
        startedAtMs: 1_000,
      },
    ];
    const sum = sumCodingCaseStats(rows, 6_000);
    expect(sum.stepsTotal).toBe(10);
    expect(sum.elapsedTotalSec).toBe(105);
    expect(formatCodingCaseStats(rows[0]!, 6_000, (s) => `${s}s`)).toBe(
      "10步 · 100s",
    );
  });
});

describe("mergeCodingLiveState", () => {
  it("does not drop a finished case when snapshot logs only have later cases", () => {
    const prev = {
      byIid: {
        "astropy__astropy-12907": {
          iid: "astropy__astropy-12907",
          status: "pass" as const,
          patchSource: "git_diff",
        },
      },
      harness: { ...EMPTY_CODING_HARNESS, n: 5, total: 5 },
    };
    const next = {
      "astropy__astropy-14182": {
        iid: "astropy__astropy-14182",
        status: "pass" as const,
        patchSource: "git_diff",
      },
    };
    const merged = mergeCodingLiveState(prev, next, EMPTY_CODING_HARNESS);
    expect(merged.byIid["astropy__astropy-12907"]?.status).toBe("pass");
    expect(merged.byIid["astropy__astropy-14182"]?.status).toBe("pass");
    expect(merged.harness.n).toBe(5);
  });
});

describe("parseAstIndexLine", () => {
  it("parses enqueue and status lines", () => {
    expect(
      parseAstIndexLine(
        "[L1] workspace_index enqueue (ephemeral) astropy__astropy-14182 work=abcd accepted=1",
      ),
    ).toMatchObject({ iid: "astropy__astropy-14182", status: "queued" });
    expect(
      parseAstIndexLine(
        "[L1] workspace_index astropy__astropy-14182 status=ready files=935/935 gen=1 ephemeral=1",
      ),
    ).toMatchObject({
      iid: "astropy__astropy-14182",
      status: "ready",
      filesDone: 935,
      filesTotal: 935,
      ephemeral: true,
    });
  });
});

describe("mergeAstIndexEntry", () => {
  it("does not let poll_error clobber a ready snapshot", () => {
    const ready = {
      iid: "a",
      status: "ready",
      filesDone: 900,
      filesTotal: 900,
      ephemeral: true,
    };
    const weak = {
      iid: "a",
      status: "poll_error",
      filesDone: null,
      filesTotal: null,
      ephemeral: false,
    };
    expect(mergeAstIndexEntry(ready, weak)).toMatchObject({
      status: "ready",
      filesDone: 900,
      filesTotal: 900,
    });
  });
});

describe("formatAstIndexRows", () => {
  it("keeps finished coding cases when AST logs were truncated", () => {
    const coding: Record<string, CodingCaseLive> = {
      "astropy__astropy-14182": { iid: "astropy__astropy-14182", status: "pass" },
      "astropy__astropy-14365": { iid: "astropy__astropy-14365", status: "pass" },
      "astropy__astropy-14995": { iid: "astropy__astropy-14995", status: "running" },
      "astropy__astropy-6938": { iid: "astropy__astropy-6938", status: "pass" },
    };
    const ast = {
      "astropy__astropy-14995": {
        iid: "astropy__astropy-14995",
        status: "ready",
        filesDone: 903,
        filesTotal: 903,
        ephemeral: true,
      },
      "astropy__astropy-6938": {
        iid: "astropy__astropy-6938",
        status: "ready",
        filesDone: 704,
        filesTotal: 704,
        ephemeral: true,
      },
    };
    const rows = formatAstIndexRows(ast, coding);
    expect(rows.map((r) => r.iid).sort()).toEqual([
      "astropy__astropy-14182",
      "astropy__astropy-14365",
      "astropy__astropy-14995",
      "astropy__astropy-6938",
    ]);
    expect(rows.find((r) => r.iid.endsWith("14182"))?.status).toBe("purged");
    expect(rows.find((r) => r.iid.endsWith("14995"))?.status).toBe("ready");
  });
});
