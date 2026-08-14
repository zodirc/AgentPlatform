import { Link } from "react-router-dom";
import { targetsFromRun } from "./progressParse";
import type { OfficialLogItem, OfficialRun } from "./types";

type OfficialCase = NonNullable<OfficialRun["cases"]>[number];

// The parent owns this deliberately broad cross-pane state bag; callbacks are
// typed at their use sites so strict TypeScript still checks rendered behavior.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type HistoryPaneModel = Record<string, any>;

export function HistoryPane({ model }: { model: HistoryPaneModel }) {
  const { filteredRuns, runs, historySelectMode, setHistorySelectMode, setCheckedRunIds, checkedRunIds, clearingHistory, deleteSelectedHistory, clearHistory, clearHistoryBefore, loadList, selectedId, loadDetail, shortId, toggleCheckedRun, runMetrics, historyHeadlineMetric, elapsedSeconds, isActiveStatus, nowMs, setPagePane, historyDeepLinkDoneRef, navigate, opsOfficialPath, secret, runSuitesLabel, statusClass, formatTime, formatDuration, detail, elapsedSec, busy, remainLabel, targetEnabled, rerunFrom, openAuthorizedHtml, setError, opsDisplayText, downloadAuthorizedFile, opsRunPath, tab, setTab, MetricBars, detailMetrics, ArtifactsPanel, artifacts, artifactsLoading, artifactsError, logTabItems, isOpsErrorLogLine } = model;
  return (
        <>
          <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
            {/* History table */}
            <aside className="rounded-xl border border-border">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
                <h2 className="text-sm font-semibold">
                  历史 ({filteredRuns.length})
                </h2>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="text-[11px] text-muted-foreground underline disabled:opacity-40"
                    disabled={runs.length === 0}
                    onClick={() => {
                      setHistorySelectMode((v: boolean) => {
                        if (v) setCheckedRunIds(new Set());
                        return !v;
                      });
                    }}
                  >
                    {historySelectMode ? "取消多选" : "多选"}
                  </button>
                  {historySelectMode ? (
                    <>
                      <button
                        type="button"
                        className="text-[11px] text-muted-foreground underline disabled:opacity-40"
                        disabled={filteredRuns.length === 0}
                        onClick={() => {
                          const allVisible = filteredRuns.every((r: OfficialRun) =>
                            checkedRunIds.has(r.id),
                          );
                          if (allVisible) {
                            setCheckedRunIds(new Set());
                          } else {
                            setCheckedRunIds(
                              new Set(filteredRuns.map((r: OfficialRun) => r.id)),
                            );
                          }
                        }}
                      >
                        {filteredRuns.every((r: OfficialRun) => checkedRunIds.has(r.id)) &&
                        filteredRuns.length > 0
                          ? "取消全选"
                          : "全选"}
                      </button>
                      <button
                        type="button"
                        className="text-[11px] text-destructive underline disabled:opacity-40"
                        disabled={clearingHistory || checkedRunIds.size === 0}
                        onClick={() => void deleteSelectedHistory()}
                      >
                        {clearingHistory
                          ? "删除中…"
                          : `删除选中(${checkedRunIds.size})`}
                      </button>
                    </>
                  ) : (
                    <>
                      <label className="text-[11px] text-muted-foreground">
                        按时间
                        <select
                          className="ml-1 rounded border border-border bg-background px-1 py-0.5 text-[11px]"
                          defaultValue=""
                          disabled={clearingHistory || runs.length === 0}
                          onChange={(e) => {
                            const v = e.target.value;
                            e.target.value = "";
                            if (v === "all") void clearHistory();
                            else if (v === "1h")
                              void clearHistoryBefore(1, "1 小时前");
                            else if (v === "24h")
                              void clearHistoryBefore(24, "1 天前");
                            else if (v === "7d")
                              void clearHistoryBefore(24 * 7, "7 天前");
                            else if (v === "30d")
                              void clearHistoryBefore(24 * 30, "30 天前");
                          }}
                        >
                          <option value="" disabled>
                            清除…
                          </option>
                          <option value="1h">早于 1 小时</option>
                          <option value="24h">早于 1 天</option>
                          <option value="7d">早于 7 天</option>
                          <option value="30d">早于 30 天</option>
                          <option value="all">全部清空</option>
                        </select>
                      </label>
                    </>
                  )}
                  <button
                    type="button"
                    className="text-[11px] text-muted-foreground underline"
                    onClick={() => {
                      void loadList();
                      if (selectedId) void loadDetail();
                    }}
                  >
                    刷新
                  </button>
                </div>
              </div>
              <div className="max-h-[32rem] overflow-y-auto">
                {filteredRuns.length === 0 ? (
                  <p className="p-3 text-xs text-muted-foreground">
                    暂无记录。
                  </p>
                ) : (
                  <ul>
                    {filteredRuns.map((r: OfficialRun) => {
                      const active = selectedId === r.id;
                      const checked = checkedRunIds.has(r.id);
                      const m = runMetrics(r);
                      const head = historyHeadlineMetric(m);
                      const durSec = elapsedSeconds(
                        r.created_at,
                        isActiveStatus(r.status) ? null : r.finished_at,
                        nowMs,
                      );
                      return (
                        <li
                          key={r.id}
                          className="border-b border-border/70 last:border-0"
                        >
                          <div
                            className={`flex items-start gap-2 px-3 py-2.5 text-xs ${
                              active ? "bg-muted" : "hover:bg-muted/60"
                            }`}
                          >
                            {historySelectMode ? (
                              <input
                                type="checkbox"
                                className="mt-1"
                                checked={checked}
                                aria-label={`选择 ${shortId(r.id)}`}
                                onChange={() => toggleCheckedRun(r.id)}
                              />
                            ) : null}
                            <button
                              type="button"
                              className="min-w-0 flex-1 text-left"
                              onClick={() => {
                                if (historySelectMode) {
                                  toggleCheckedRun(r.id);
                                  return;
                                }
                                historyDeepLinkDoneRef.current = true;
                                setPagePane("history");
                                navigate(opsOfficialPath(secret, r.id));
                              }}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-medium">
                                  {runSuitesLabel(r)}
                                </span>
                                <span className={statusClass(r.status)}>
                                  {r.status}
                                </span>
                              </div>
                              <div className="mt-0.5 flex justify-between gap-2 text-[11px] text-muted-foreground">
                                <span>{formatTime(r.created_at)}</span>
                                {durSec != null ? (
                                  <span className="tabular-nums shrink-0">
                                    {isActiveStatus(r.status) ? "已用 " : ""}
                                    {formatDuration(durSec)}
                                  </span>
                                ) : null}
                              </div>
                              <div className="mt-1 flex justify-between font-mono text-[10px] text-muted-foreground">
                                <span>{shortId(r.id)}</span>
                                <span>
                                  {head
                                    ? `${head.label}=${
                                        Number.isInteger(head.value)
                                          ? head.value
                                          : head.value.toFixed(3)
                                      }`
                                    : `${r.summary?.pass ?? 0}/${r.summary?.total ?? 0}`}
                                </span>
                              </div>
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </aside>

            {/* Detail */}
            <div className="rounded-xl border border-border p-4">
              {!selectedId ? (
                <p className="text-sm text-muted-foreground">
                  从左侧选一次 run
                  查看详情。顶栏「本轮」只负责发起与直播，不会自动摊开历史结果。
                </p>
              ) : !detail ? (
                <p className="text-sm text-muted-foreground">加载中…</p>
              ) : (
                <div className="space-y-4">
                  <header>
                    <h2 className="text-lg font-semibold tracking-tight">
                      {detail.title || detail.model_meta?.title || detail.id}
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      <span className={statusClass(detail.status)}>
                        {detail.status}
                      </span>
                      {" · "}
                      {formatTime(detail.created_at)} →{" "}
                      {formatTime(detail.finished_at)}
                      {elapsedSec != null ? (
                        <>
                          {" · "}
                          <span className="tabular-nums">
                            {busy ? "已用" : "用时"}{" "}
                            {formatDuration(elapsedSec)}
                            {busy && remainLabel ? ` · ${remainLabel}` : ""}
                          </span>
                        </>
                      ) : null}
                      {" · "}
                      pass {detail.summary?.pass ?? 0}/
                      {detail.summary?.total ?? 0}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      <button
                        type="button"
                        className="rounded-md border border-border px-2 py-1 hover:bg-muted"
                        disabled={!targetsFromRun(detail).some(targetEnabled)}
                        title="按相同目标强制重跑（会停掉当前活动轮）"
                        onClick={() => void rerunFrom(detail)}
                      >
                        重跑
                      </button>
                      <button
                        type="button"
                        className="rounded-md border border-border px-2 py-1 hover:bg-muted"
                        onClick={() => {
                          void openAuthorizedHtml(
                            `/api/v1/ops/official/runs/${encodeURIComponent(detail.id)}/report`,
                            secret,
                          ).catch((e: unknown) =>
                            setError(
                              e instanceof Error ? e.message : String(e),
                            ),
                          );
                        }}
                      >
                        HTML 报告
                      </button>
                      <button
                        type="button"
                        className="rounded-md border border-border px-2 py-1 hover:bg-muted"
                        onClick={() => {
                          void downloadAuthorizedFile(
                            `/api/v1/ops/official/runs/${encodeURIComponent(detail.id)}/predictions`,
                            secret,
                            `predictions-${detail.id.slice(0, 8)}.jsonl`,
                          ).catch((e: unknown) =>
                            setError(
                              e instanceof Error ? e.message : String(e),
                            ),
                          );
                        }}
                      >
                        predictions
                      </button>
                      <Link
                        className="rounded-md border border-border px-2 py-1 hover:bg-muted"
                        to={opsRunPath(secret, detail.id)}
                      >
                        通用 Run 页
                      </Link>
                    </div>
                    {detail.error ? (
                      <p className="mt-2 text-sm text-destructive">
                        {opsDisplayText(detail.error)}
                      </p>
                    ) : null}
                  </header>

                  <div className="flex flex-wrap gap-1.5 text-xs">
                    {(
                      [
                        "overview",
                        "metrics",
                        "cases",
                        "artifacts",
                        "log",
                      ] as const
                    ).map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setTab(t)}
                        className={`rounded-md border px-2.5 py-1 ${
                          tab === t
                            ? "border-foreground/40 bg-muted"
                            : "border-border"
                        }`}
                      >
                        {t === "overview"
                          ? "总览"
                          : t === "metrics"
                            ? "指标"
                            : t === "cases"
                              ? "步骤"
                              : t === "artifacts"
                                ? "产物"
                                : "日志"}
                      </button>
                    ))}
                  </div>

                  {tab === "overview" ? (
                    <div className="grid gap-3 sm:grid-cols-4">
                      {(
                        [
                          ["total", detail.summary?.total],
                          ["pass", detail.summary?.pass],
                          ["fail", detail.summary?.fail],
                          ["skipped", detail.summary?.skipped],
                        ] as const
                      ).map(([label, val]) => (
                        <div
                          key={label}
                          className="rounded-lg bg-muted/40 px-3 py-2 text-center"
                        >
                          <div className="text-[11px] text-muted-foreground">
                            {label}
                          </div>
                          <div className="text-xl font-semibold tabular-nums">
                            {val ?? 0}
                          </div>
                        </div>
                      ))}
                      <p className="sm:col-span-4 text-xs text-muted-foreground">
                        单次指标见「指标」页签；完整分桶与逐题产物见「产物」；跨跑次汇总见顶栏「指标汇总」（仅
                        completed）。
                      </p>
                    </div>
                  ) : null}

                  {tab === "metrics" ? (
                    <MetricBars metrics={detailMetrics} />
                  ) : null}

                  {tab === "cases" ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="border-b border-border text-muted-foreground">
                          <tr>
                            <th className="py-2 pr-2">步骤</th>
                            <th className="py-2 pr-2">状态</th>
                            <th className="py-2">指标</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(detail.cases || []).map((c: OfficialCase) => (
                            <tr
                              key={c.case_id}
                              className="border-b border-border/60"
                            >
                              <td className="py-1.5 pr-2 font-mono">
                                {c.case_id}
                              </td>
                              <td
                                className={`py-1.5 pr-2 ${statusClass(c.status)}`}
                              >
                                {c.status}
                              </td>
                              <td className="py-1.5 font-mono text-[10px]">
                                {JSON.stringify(c.metrics || {})}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {tab === "artifacts" ? (
                    <ArtifactsPanel
                      data={artifacts}
                      loading={artifactsLoading}
                      error={artifactsError}
                      secret={secret}
                    />
                  ) : null}

                  {tab === "log" ? (
                    <ol className="max-h-[28rem] space-y-2 overflow-y-auto text-xs">
                      <li className="pb-1 text-[11px] text-muted-foreground">
                        仅 error 与关键步骤（suite / turn / phase /
                        case）；完整过程在本页签与产物中查看
                      </li>
                      {logTabItems.length === 0 ? (
                        <li className="text-muted-foreground">暂无关键日志</li>
                      ) : null}
                      {logTabItems.map((item: OfficialLogItem, i: number) => {
                        const text = String(item.message || "");
                        const err =
                          isOpsErrorLogLine(text) ||
                          String(item.status || "").toLowerCase() === "fail";
                        return (
                          <li
                            key={`${item.at}-${item.kind}-${i}`}
                            className={`border-b border-border/50 pb-2 ${
                              err ? "border-destructive/30" : ""
                            }`}
                          >
                            <span className="text-muted-foreground">
                              {formatTime(item.at)}
                            </span>{" "}
                            <span
                              className={`rounded-full border px-1.5 text-[10px] uppercase ${
                                err
                                  ? "border-destructive/50 text-destructive"
                                  : "border-border text-muted-foreground"
                              }`}
                            >
                              {err
                                ? "error"
                                : item.kind === "log"
                                  ? "step"
                                  : item.kind || "step"}
                            </span>
                            <div
                              className={`mt-0.5 whitespace-pre-wrap font-mono text-[11px] ${
                                err ? "font-medium text-destructive" : ""
                              }`}
                            >
                              {text || (item.kind ? `(${item.kind})` : "")}
                            </div>
                          </li>
                        );
                      })}
                    </ol>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        </>
  );
}
