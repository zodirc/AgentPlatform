import type { AstIndexLive, CodingCaseLive } from "./types";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type LiveProgressModel = Record<string, any>;

export function LiveProgress({ model }: { model: LiveProgressModel }) {
  const { busy, displayPhaseHint, timingLabel, detailProgress, detailPct, suiteProgressLabel, progress, itemsRemainLabel, suitePct, barPct, codingRows, codingSummary, HARNESS_STAGE_LABEL, shortCaseToken, astIndexRows, astIndexSummary, astIndexExpanded, setAstIndexExpanded, ChevronUp, ChevronDown, logBoxRef, liveLogs, liveLogLineClass, OfficialLogLine, secret } = model;
  return (
    <>
            {busy ? (
              <div className="mt-4 space-y-2">
                <div className="rounded-md border border-border/80 bg-background/80 px-3 py-2 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <span className="text-muted-foreground">当前阶段 · </span>
                      <span className="font-medium whitespace-pre-wrap">
                        {displayPhaseHint}
                      </span>
                    </span>
                    <div className="flex flex-wrap items-center gap-2">
                      {timingLabel ? (
                        <span className="tabular-nums text-muted-foreground">
                          {timingLabel}
                        </span>
                      ) : null}
                      <span className="rounded bg-foreground/10 px-1.5 py-0.5 text-[10px] tabular-nums">
                        直播中
                      </span>
                    </div>
                  </div>
                </div>
                <div className="rounded-md border border-border/80 bg-background/60 px-3 py-2 text-xs">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span>
                      <span className="text-muted-foreground">明细 · </span>
                      <span className="font-medium">
                        {detailProgress.kind === "idle"
                          ? "拉取中 / 等待进度…"
                          : detailProgress.label}
                      </span>
                    </span>
                    <span className="tabular-nums text-muted-foreground">
                      {detailProgress.done != null &&
                      detailProgress.total != null
                        ? detailProgress.done < (detailProgress.total ?? 0)
                          ? `已完成 ${detailProgress.done}/${detailProgress.total}`
                          : `${detailProgress.done}/${detailProgress.total}` +
                            (detailProgress.remain != null &&
                            detailProgress.unit
                              ? ` · 剩 ${detailProgress.remain} ${detailProgress.unit}`
                              : "")
                        : detailPct != null
                          ? `${detailPct}%`
                          : "—"}
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-foreground/70 transition-[width] duration-200"
                      style={{ width: `${detailPct != null ? detailPct : 8}%` }}
                    />
                  </div>
                </div>
                <div className="flex justify-between text-[11px] text-muted-foreground">
                  <span>
                    {suiteProgressLabel ||
                      `L1套件 ${progress.done}/${progress.total || "—"}`}
                    <span className="text-muted-foreground/80">
                      {" "}
                      （检索 / 中文检索 / 上下文 / 编码；与 BEIR
                      三数据集不是同一层）
                    </span>
                  </span>
                  <span className="tabular-nums">
                    {itemsRemainLabel
                      ? itemsRemainLabel
                      : suiteProgressLabel
                        ? suiteProgressLabel
                        : progress.total
                          ? `${suitePct}%`
                          : "—"}
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-foreground/80 transition-[width] duration-300"
                    style={{ width: `${barPct}%` }}
                  />
                </div>
                {codingRows.length > 0 ||
                codingSummary.harness.phase !== "idle" ? (
                  <div
                    className="mt-2 rounded-md border border-border/80 bg-muted/20 px-2.5 py-2"
                    aria-label="编码题进度"
                  >
                    {/* Harness mid-run is the primary signal; infer is a compact footer. */}
                    {codingSummary.harness.phase !== "idle" ? (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                              官方 harness（中间过程）
                            </div>
                            <div className="mt-0.5 truncate text-[11px] tabular-nums text-muted-foreground">
                              {codingSummary.harness.phase === "running"
                                ? (() => {
                                    const stageKey =
                                      codingSummary.harness.stage || "";
                                    const stageLabel =
                                      HARNESS_STAGE_LABEL[stageKey] ||
                                      (stageKey === "start" ||
                                      stageKey === "resolve"
                                        ? "启动中"
                                        : stageKey || "评测中");
                                    const view = codingSummary.harnessView;
                                    const done =
                                      view.done != null && view.total != null
                                        ? `${view.done}/${view.total}`
                                        : codingSummary.harness.n != null
                                          ? `n=${codingSummary.harness.n}`
                                          : null;
                                    const counts =
                                      view.resolved != null
                                        ? `✓${view.resolved} · ✖${view.unresolved ?? 0} · err ${view.error ?? 0}`
                                        : null;
                                    return [stageLabel, done, counts]
                                      .filter(Boolean)
                                      .join(" · ");
                                  })()
                                : codingSummary.harness.phase === "done"
                                  ? `完成 · resolve ${codingSummary.harness.resolved ?? "?"}/${codingSummary.harness.total ?? "?"}${
                                      codingSummary.harness.rate
                                        ? ` · rate=${codingSummary.harness.rate}`
                                        : ""
                                    }`
                                  : codingSummary.harness.detail
                                    ? `失败 · ${codingSummary.harness.detail}`
                                    : "失败"}
                            </div>
                          </div>
                          <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
                            {codingSummary.harness.phase === "running"
                              ? codingSummary.harnessView.pct != null
                                ? `${codingSummary.harnessView.pct}%`
                                : "…"
                              : codingSummary.harness.phase === "done"
                                ? "100%"
                                : codingSummary.harness.phase === "failed"
                                  ? "—"
                                  : "…"}
                          </span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                          <div
                            className={`h-full rounded-full transition-[width] duration-500 ${
                              codingSummary.harness.phase === "failed"
                                ? "bg-destructive/70"
                                : "bg-foreground/70"
                            }`}
                            style={{
                              width: `${
                                codingSummary.harness.phase === "done"
                                  ? 100
                                  : codingSummary.harness.phase === "failed"
                                    ? Math.max(
                                        codingSummary.harness.pct ?? 8,
                                        8,
                                      )
                                    : Math.max(
                                        codingSummary.harnessView.pct ??
                                          (codingSummary.harnessView.done !=
                                            null &&
                                          codingSummary.harnessView.total
                                            ? Math.round(
                                                (codingSummary.harnessView
                                                  .done /
                                                  codingSummary.harnessView
                                                    .total) *
                                                  100,
                                              )
                                            : 8),
                                        8,
                                      )
                              }%`,
                            }}
                          />
                        </div>
                        {codingSummary.harness.detail &&
                        codingSummary.harness.phase === "running" ? (
                          <div className="truncate font-mono text-[10px] text-muted-foreground/90">
                            {codingSummary.harness.detail}
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    {codingRows.length > 0 ? (
                      <div
                        className={
                          codingSummary.harness.phase !== "idle"
                            ? "mt-2 border-t border-border/60 pt-2"
                            : undefined
                        }
                      >
                        <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                          infer 出 patch
                        </div>
                        <div className="mt-0.5 text-[11px] tabular-nums text-muted-foreground">
                          {codingSummary.total > 0
                            ? `${codingSummary.pass + codingSummary.fail}/${codingSummary.total} 完成`
                            : "—"}
                          {codingSummary.running > 0
                            ? ` · 进行中 ${codingSummary.running}`
                            : ""}
                          {codingSummary.pass > 0
                            ? ` · patch ${codingSummary.pass}`
                            : ""}
                          {codingSummary.fail > 0
                            ? ` · 失败 ${codingSummary.fail}`
                            : ""}
                          {codingSummary.harness.phase === "idle"
                            ? " · 完成后进入 harness"
                            : ""}
                        </div>
                        <ul className="mt-1.5 space-y-1">
                          {codingRows.map((row: CodingCaseLive) => {
                            const label =
                              row.harness != null
                                ? `${row.status} · harness=${row.harness}`
                                : row.bucket
                                  ? `${row.status} · ${row.bucket}`
                                  : row.patchSource &&
                                      row.patchSource !== "none"
                                    ? `${row.status} · ${row.patchSource}`
                                    : row.status;
                            return (
                              <li
                                key={row.iid}
                                className="flex items-center justify-between gap-2 text-[11px]"
                              >
                                <span className="truncate font-mono text-foreground/90">
                                  {shortCaseToken(row.iid)}
                                </span>
                                <span className="shrink-0 tabular-nums text-muted-foreground">
                                  {label}
                                </span>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {astIndexRows.length > 0 ? (
                  <div
                    className="mt-2 rounded-md border border-border/80 bg-muted/20 px-2.5 py-2"
                    aria-label="编码题 AST 索引"
                  >
                    <button
                      type="button"
                      className="flex w-full items-center justify-between gap-2 text-left transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      onClick={() => setAstIndexExpanded((v: boolean) => !v)}
                      aria-expanded={astIndexExpanded}
                      title={
                        astIndexExpanded
                          ? "收起按题 AST 索引"
                          : "展开按题 AST 索引"
                      }
                    >
                      <div className="min-w-0">
                        <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                          AST 索引（按题 · ephemeral）
                        </div>
                        <div className="mt-0.5 truncate text-[11px] tabular-nums text-muted-foreground">
                          {astIndexSummary.total} 题
                          {astIndexSummary.building > 0
                            ? ` · 进行中 ${astIndexSummary.building}`
                            : ""}
                          {astIndexSummary.ready > 0
                            ? ` · ready ${astIndexSummary.ready}`
                            : ""}
                          {astIndexSummary.error > 0
                            ? ` · 失败 ${astIndexSummary.error}`
                            : ""}
                          {astIndexSummary.disabled > 0
                            ? ` · disabled ${astIndexSummary.disabled}`
                            : ""}
                        </div>
                      </div>
                      {astIndexExpanded ? (
                        <ChevronUp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      )}
                    </button>
                    {astIndexExpanded ? (
                      <ul className="mt-2 space-y-1.5 border-t border-border/60 pt-2">
                        {astIndexRows.map((row: AstIndexLive) => {
                          const pct =
                            row.filesTotal != null &&
                            row.filesTotal > 0 &&
                            row.filesDone != null
                              ? Math.max(
                                  0,
                                  Math.min(
                                    100,
                                    Math.round(
                                      (row.filesDone / row.filesTotal) * 100,
                                    ),
                                  ),
                                )
                              : null;
                          const building =
                            row.status === "building" ||
                            row.status === "cold" ||
                            row.status === "queued" ||
                            row.status === "stale";
                          return (
                            <li key={row.iid} className="text-[11px]">
                              <div className="flex items-center justify-between gap-2">
                                <span className="truncate font-mono text-foreground/90">
                                  {shortCaseToken(row.iid)}
                                </span>
                                <span className="shrink-0 tabular-nums text-muted-foreground">
                                  {row.status}
                                  {row.filesDone != null &&
                                  row.filesTotal != null
                                    ? ` · ${row.filesDone}/${row.filesTotal}`
                                    : ""}
                                </span>
                              </div>
                              {building ? (
                                <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                                  <div
                                    className="h-full rounded-full bg-foreground/40 transition-[width] duration-500"
                                    style={{
                                      width: pct != null ? `${pct}%` : "28%",
                                      ...(pct == null
                                        ? {
                                            animation:
                                              "pulse 1.4s ease-in-out infinite",
                                          }
                                        : null),
                                    }}
                                  />
                                </div>
                              ) : null}
                            </li>
                          );
                        })}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
                <div
                  ref={logBoxRef}
                  className="max-h-72 overflow-y-auto overscroll-contain rounded-md border border-border/80 bg-muted/40 p-2 font-mono text-[11px] leading-relaxed"
                >
                  {liveLogs.length === 0 ? (
                    <p className="text-muted-foreground">
                      等待拉取日志…（L1 会先打 [L1] pull … starting，随后 [pull]
                      / [progress] pull）
                    </p>
                  ) : (
                    liveLogs.map((line: string, i: number) => (
                      <div
                        key={`${i}-${line.slice(0, 24)}`}
                        className={liveLogLineClass(line)}
                      >
                        <OfficialLogLine line={line} secret={secret} />
                      </div>
                    ))
                  )}
                </div>
              </div>
            ) : null}
    </>
  );
}
