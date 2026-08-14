import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { opsRawPath, statusClass } from "../OpsShell";
import { opsDisplayText } from "../opsDisplayText";
import { OpsTextViewerModal } from "../OpsTextViewerModal";
import type { ArtifactCase, RunArtifacts, SuiteArtifact } from "./types";
import {
  downloadAuthorizedFile,
  fetchAuthorizedText,
  openAuthorizedHtml,
} from "./sse";

export const SUITE_ARTIFACT_LABEL: Record<string, string> = {
  retrieval: "检索",
  retrieval_zh: "中文检索",
  context: "上下文",
  coding: "编码",
  coding_infer: "编码",
};

export function isCodingSuite(suite: SuiteArtifact | undefined): boolean {
  const s = String(suite?.suite || "").toLowerCase();
  return (
    s.includes("coding") ||
    s.includes("swebench") ||
    Boolean(suite?.coding_scorecard) ||
    Boolean(suite?.result?.predictions)
  );
}
export function fmtResolveLabel(c: ArtifactCase): string {
  if (typeof c.resolve_label === "string" && c.resolve_label) {
    return c.resolve_label;
  }
  const v = c.resolved ?? c.l2?.resolved;
  if (v === true) return "官方通过";
  if (v === false) return "官方未过";
  return "—";
}

export function metricPreview(m: Record<string, number> | undefined): string {
  if (!m) return "—";
  const preferred = [
    "resolve_rate",
    "patch_rate",
    "n_resolved",
    "n_nonempty_patches",
    "n_instances",
    "ndcg_at_10",
    "agent.ndcg_at_10",
    "fts_okapi_rescore.ndcg_at_10",
    "fts_ts_rank.ndcg_at_10",
    "delta.ndcg_at_10",
    "agent_f1",
    "agent_em",
    "f1",
    "em",
    "n_hits",
  ];
  const parts: string[] = [];
  for (const k of preferred) {
    const v = m[k];
    if (typeof v === "number" && Number.isFinite(v)) {
      parts.push(Number.isInteger(v) ? `${k}=${v}` : `${k}=${v.toFixed(3)}`);
    }
  }
  if (!parts.length) {
    for (const [k, v] of Object.entries(m)) {
      if (typeof v === "number" && Number.isFinite(v) && parts.length < 3) {
        parts.push(Number.isInteger(v) ? `${k}=${v}` : `${k}=${v.toFixed(3)}`);
      }
    }
  }
  return parts.join(" · ") || "—";
}

export function fmtBool(v: unknown): string {
  if (v === true) return "yes";
  if (v === false) return "no";
  return "—";
}

export function ArtifactsPanel({
  data,
  loading,
  error,
  secret,
}: {
  data: RunArtifacts | null;
  loading: boolean;
  error: string | null;
  secret: string;
}) {
  const suites = data?.suites || [];
  const [suiteIdx, setSuiteIdx] = useState(0);
  const [bucketFilter, setBucketFilter] = useState<string>("");
  const [patchViewer, setPatchViewer] = useState<{
    title: string;
    content: string;
  } | null>(null);
  const [artifactActionError, setArtifactActionError] = useState<string | null>(
    null,
  );

  useEffect(() => {
    setSuiteIdx(0);
    setBucketFilter("");
    setPatchViewer(null);
    setArtifactActionError(null);
  }, [data?.run_id, suites.length]);

  if (loading) {
    return <p className="text-sm text-muted-foreground">加载产物…</p>;
  }
  if (error) {
    return <p className="text-sm text-destructive">{opsDisplayText(error)}</p>;
  }
  if (!suites.length) {
    return (
      <p className="text-sm text-muted-foreground">
        尚无子套件产物（跑次未完成，或未写入 child manifest）。
      </p>
    );
  }

  const suite = suites[Math.min(suiteIdx, suites.length - 1)] || suites[0];
  const coding = isCodingSuite(suite);
  const counts = suite.bucket_counts || {};
  const totalBuckets = Object.values(counts).reduce((a, b) => a + b, 0);
  const bucketKeys = Object.keys(counts).sort(
    (a, b) => (counts[b] || 0) - (counts[a] || 0),
  );
  const cases = (suite.cases || []).filter((c) =>
    bucketFilter ? c.bucket === bucketFilter : true,
  );
  const score = suite.coding_scorecard || {};
  const resolveRate =
    typeof score.resolve_rate === "number"
      ? score.resolve_rate
      : typeof suite.metrics?.resolve_rate === "number"
        ? suite.metrics.resolve_rate
        : null;
  const patchRate =
    typeof score.patch_rate === "number"
      ? score.patch_rate
      : typeof suite.metrics?.patch_rate === "number"
        ? suite.metrics.patch_rate
        : null;

  return (
    <div className="space-y-4">
      {suites.length > 1 ? (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {suites.map((s, i) => {
            const key = s.suite || String(i);
            const label = SUITE_ARTIFACT_LABEL[key] || key;
            return (
              <button
                key={`${key}-${s.bench_run_id || i}`}
                type="button"
                onClick={() => {
                  setSuiteIdx(i);
                  setBucketFilter("");
                }}
                className={`rounded-md border px-2.5 py-1 ${
                  i === suiteIdx
                    ? "border-foreground/40 bg-muted"
                    : "border-border"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="font-mono">{suite.bench_run_id || "—"}</span>
        {suite.arm ? <span>arm={suite.arm}</span> : null}
        {suite.sample_tier ? <span>{suite.sample_tier}</span> : null}
        {suite.context_limit != null && Number(suite.context_limit) > 0 ? (
          <span>limit={suite.context_limit}/task</span>
        ) : null}
        {suite.suite_ndcg_median != null ? (
          <span>median nDCG={Number(suite.suite_ndcg_median).toFixed(3)}</span>
        ) : null}
        {suite.report_href ? (
          <button
            type="button"
            className="underline decoration-dotted underline-offset-2"
            onClick={() => {
              setArtifactActionError(null);
              void openAuthorizedHtml(suite.report_href!, secret).catch((e) =>
                setArtifactActionError(
                  e instanceof Error ? e.message : String(e),
                ),
              );
            }}
          >
            HTML 报告
          </button>
        ) : suite.report_html_available ? (
          <span>报告已生成</span>
        ) : null}
        {suite.predictions_href ? (
          <button
            type="button"
            className="underline decoration-dotted underline-offset-2"
            onClick={() => {
              setArtifactActionError(null);
              const name = `predictions-${(suite.bench_run_id || data?.run_id || "run").slice(0, 8)}.jsonl`;
              void downloadAuthorizedFile(
                suite.predictions_href!,
                secret,
                name,
              ).catch((e) =>
                setArtifactActionError(
                  e instanceof Error ? e.message : String(e),
                ),
              );
            }}
          >
            下载 predictions.jsonl
          </button>
        ) : suite.predictions_available ? (
          <span>predictions 就绪</span>
        ) : null}
        {suite.csi_probes_href ? (
          <button
            type="button"
            className="underline decoration-dotted underline-offset-2"
            onClick={() => {
              setArtifactActionError(null);
              const name = `csi_probes-${(suite.bench_run_id || data?.run_id || "run").slice(0, 8)}.json`;
              void downloadAuthorizedFile(
                suite.csi_probes_href!,
                secret,
                name,
              ).catch((e) =>
                setArtifactActionError(
                  e instanceof Error ? e.message : String(e),
                ),
              );
            }}
          >
            下载 csi_probes.json
          </button>
        ) : suite.csi_probes_available ? (
          <span>csi_probes 就绪</span>
        ) : null}
      </div>
      {artifactActionError ? (
        <p className="text-[11px] text-destructive">
          {opsDisplayText(artifactActionError)}
        </p>
      ) : null}

      {coding ? (
        <div className="rounded-md border border-border/80 bg-muted/30 px-3 py-2 text-xs">
          <div className="mb-1 text-[11px] text-muted-foreground">
            编码效果（L1 pass=有 patch；官方 resolve 看下表「官方」列，需
            harness）
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono tabular-nums">
            <span>
              resolve_rate=
              {resolveRate == null ? "—" : Number(resolveRate).toFixed(3)}
            </span>
            <span>
              patch_rate=
              {patchRate == null ? "—" : Number(patchRate).toFixed(3)}
            </span>
            {score.n_resolved != null || score.n_resolved_cases != null ? (
              <span>
                resolved=
                {String(score.n_resolved ?? score.n_resolved_cases)}
                {score.n_instances != null
                  ? `/${String(score.n_instances)}`
                  : ""}
              </span>
            ) : null}
            {score.n_apply_ok != null ? (
              <span>
                apply_ok={String(score.n_apply_ok)}
                {score.n_with_patch != null
                  ? `/${String(score.n_with_patch)}`
                  : ""}
              </span>
            ) : null}
            {typeof score.locate_fuse_ok_rate === "number" ? (
              <span>
                locate_fuse=
                {Number(score.locate_fuse_ok_rate).toFixed(3)}
                {score.locate_fuse_n != null
                  ? ` (n=${String(score.locate_fuse_n)})`
                  : ""}
              </span>
            ) : null}
            {typeof score.edit_impact_coverage === "number" ? (
              <span>
                impact_cov={Number(score.edit_impact_coverage).toFixed(3)}
              </span>
            ) : null}
            {typeof score.edit_checks_coverage === "number" ? (
              <span>
                checks_cov={Number(score.edit_checks_coverage).toFixed(3)}
              </span>
            ) : null}
            {typeof score.file_hit_rate === "number" ? (
              <span>
                file_hit={Number(score.file_hit_rate).toFixed(3)}
                {score.file_hit_n != null
                  ? ` (n=${String(score.file_hit_n)})`
                  : ""}
              </span>
            ) : null}
            {typeof score.repro_rerun_rate === "number" ? (
              <span>
                repro_rerun={Number(score.repro_rerun_rate).toFixed(3)}
              </span>
            ) : null}
            {typeof score.tests_before_submit_rate === "number" ? (
              <span>
                tests_submit={Number(score.tests_before_submit_rate).toFixed(3)}
              </span>
            ) : null}
            {typeof score.read_outline_coverage === "number" ? (
              <span>
                outline_cov={Number(score.read_outline_coverage).toFixed(3)}
              </span>
            ) : null}
            {typeof score.edit_related_tests_coverage === "number" ? (
              <span>
                related_tests=
                {Number(score.edit_related_tests_coverage).toFixed(3)}
              </span>
            ) : null}
            {score.syntax_reject_count != null ? (
              <span>syntax_rej={String(score.syntax_reject_count)}</span>
            ) : null}
            {score.span_fail_n != null ? (
              <span>
                span_fail={String(score.span_fail_n)}
                {typeof score.span_fail_with_candidates_rate === "number"
                  ? ` (cand=${Number(score.span_fail_with_candidates_rate).toFixed(2)})`
                  : ""}
              </span>
            ) : null}
            {score.coding_tier != null ? (
              <span>tier={String(score.coding_tier)}</span>
            ) : null}
            {score.harness != null ? (
              <span>harness={fmtBool(score.harness)}</span>
            ) : null}
          </div>
          {typeof score.resolve_note === "string" && score.resolve_note ? (
            <div className="mt-1 text-[11px] text-muted-foreground">
              {opsDisplayText(score.resolve_note)}
            </div>
          ) : null}
          {Array.isArray(score.resolved_ids) && score.resolved_ids.length ? (
            <div className="mt-1 text-[10px] font-mono text-muted-foreground">
              通过: {(score.resolved_ids as unknown[]).map(String).join(", ")}
            </div>
          ) : null}
          {Array.isArray(score.unresolved_ids) &&
          score.unresolved_ids.length ? (
            <div className="mt-0.5 text-[10px] font-mono text-muted-foreground">
              未过: {(score.unresolved_ids as unknown[]).map(String).join(", ")}
            </div>
          ) : null}
          {typeof score.note === "string" && score.note ? (
            <div className="mt-1 text-[11px] text-muted-foreground">
              {opsDisplayText(score.note)}
            </div>
          ) : null}
          {typeof score.harness_error === "string" && score.harness_error ? (
            <div className="mt-1 text-[11px] text-destructive">
              {opsDisplayText(score.harness_error)}
            </div>
          ) : null}
        </div>
      ) : Object.keys(suite.metrics || {}).length ? (
        <div className="text-xs font-mono text-muted-foreground">
          {metricPreview(suite.metrics)}
        </div>
      ) : null}

      <div>
        <div className="mb-2 text-[11px] text-muted-foreground">
          分桶{totalBuckets ? ` · n=${totalBuckets}` : ""}
        </div>
        {bucketKeys.length ? (
          <div className="space-y-1.5">
            {bucketKeys.map((b) => {
              const n = counts[b] || 0;
              const pct =
                totalBuckets > 0 ? Math.round((n / totalBuckets) * 100) : 0;
              const active = bucketFilter === b;
              return (
                <button
                  key={b}
                  type="button"
                  onClick={() => setBucketFilter(active ? "" : b)}
                  className={`flex w-full items-center gap-2 rounded-md border px-2 py-1 text-left text-xs ${
                    active
                      ? "border-foreground/40 bg-muted"
                      : "border-border/70 hover:bg-muted/40"
                  }`}
                >
                  <span className="w-36 shrink-0 truncate font-mono">{b}</span>
                  <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-foreground/70"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right tabular-nums text-muted-foreground">
                    {n} · {pct}%
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            无分桶（旧跑或未打桶）。
          </p>
        )}
        {bucketFilter ? (
          <button
            type="button"
            className="mt-2 text-[11px] text-muted-foreground underline"
            onClick={() => setBucketFilter("")}
          >
            清除筛选 · {bucketFilter}
          </button>
        ) : null}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-border text-muted-foreground">
            <tr>
              <th className="py-2 pr-2">case</th>
              <th className="py-2 pr-2">bucket</th>
              {coding ? (
                <>
                  <th className="py-2 pr-2">source</th>
                  <th className="py-2 pr-2">apply</th>
                  <th className="py-2 pr-2">官方</th>
                  <th className="py-2 pr-2">patch</th>
                </>
              ) : (
                <th className="py-2 pr-2">状态</th>
              )}
              <th className="py-2">指标 / L2</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => {
              const l2bits: string[] = [];
              const l2 = c.l2 || {};
              const l2Keys = coding
                ? [
                    "patch_source",
                    "patch_applies",
                    "resolved",
                    "ran_tests",
                    "has_repo",
                    "n_reads",
                    "steps",
                    "terminal_state",
                    "n_grep_locate_ok",
                    "n_edit_with_impact",
                    "n_edit_with_checks",
                    "n_syntax_rejected",
                    "n_span_fail",
                  ]
                : [
                    "n_search",
                    "query_drift",
                    "n_reads",
                    "read_coverage",
                    "answer_len",
                    "steps",
                    "terminal_state",
                  ];
              for (const k of l2Keys) {
                const v = l2[k] ?? (c as Record<string, unknown>)[k];
                if (v != null && v !== "") {
                  l2bits.push(
                    typeof v === "number"
                      ? `${k}=${Number(v).toFixed(3)}`
                      : `${k}=${String(v)}`,
                  );
                }
              }
              const preview = c.patch_preview || "";
              return (
                <tr
                  key={c.case_id}
                  className="border-b border-border/60 align-top"
                >
                  <td className="py-1.5 pr-2 font-mono text-[10px]">
                    {c.turn_id ? (
                      <Link
                        to={opsRawPath(secret, String(c.turn_id))}
                        className="underline decoration-dotted underline-offset-2"
                        title="Raw turn_events"
                      >
                        {c.case_id}
                      </Link>
                    ) : (
                      c.case_id
                    )}
                  </td>
                  <td className="py-1.5 pr-2 font-mono text-[10px]">
                    {c.bucket || "—"}
                  </td>
                  {coding ? (
                    <>
                      <td className="py-1.5 pr-2 font-mono text-[10px]">
                        {c.patch_source ||
                          (typeof l2.patch_source === "string"
                            ? l2.patch_source
                            : "—")}
                      </td>
                      <td className="py-1.5 pr-2 font-mono text-[10px]">
                        {fmtBool(c.patch_applies ?? l2.patch_applies ?? null)}
                      </td>
                      <td
                        className="py-1.5 pr-2 font-mono text-[10px]"
                        title={
                          c.resolve_verdict
                            ? `verdict=${c.resolve_verdict}`
                            : undefined
                        }
                      >
                        {fmtResolveLabel(c)}
                      </td>
                      <td className="py-1.5 pr-2 text-[10px]">
                        {preview || c.patch_href ? (
                          <span className="inline-flex flex-wrap gap-x-2 gap-y-0.5">
                            <button
                              type="button"
                              className="underline decoration-dotted underline-offset-2"
                              onClick={() => {
                                setArtifactActionError(null);
                                const titleBase = c.case_id || "patch";
                                if (c.patch_href) {
                                  void fetchAuthorizedText(c.patch_href, secret)
                                    .then((full) => {
                                      setPatchViewer({
                                        title: `${titleBase} (${full.length} chars · full)`,
                                        content: full,
                                      });
                                    })
                                    .catch((e) => {
                                      if (preview) {
                                        setPatchViewer({
                                          title: `${titleBase} (${c.patch_chars ?? preview.length} chars · preview)`,
                                          content: preview,
                                        });
                                      }
                                      setArtifactActionError(
                                        e instanceof Error
                                          ? e.message
                                          : String(e),
                                      );
                                    });
                                  return;
                                }
                                setPatchViewer({
                                  title: `${titleBase} (${c.patch_chars ?? preview.length} chars · preview)`,
                                  content: preview,
                                });
                              }}
                            >
                              {c.patch_href ? "全文" : "预览"}
                              {c.patch_chars != null
                                ? ` (${c.patch_chars})`
                                : ""}
                            </button>
                            {c.patch_href ? (
                              <button
                                type="button"
                                className="underline decoration-dotted underline-offset-2 text-muted-foreground"
                                onClick={() => {
                                  setArtifactActionError(null);
                                  const name = `${(c.case_id || "patch").replace(/[^\w.-]+/g, "_")}.diff`;
                                  void downloadAuthorizedFile(
                                    c.patch_href!,
                                    secret,
                                    name,
                                  ).catch((e) =>
                                    setArtifactActionError(
                                      e instanceof Error
                                        ? e.message
                                        : String(e),
                                    ),
                                  );
                                }}
                              >
                                下载
                              </button>
                            ) : null}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </>
                  ) : (
                    <td
                      className={`py-1.5 pr-2 ${statusClass(c.status || "")}`}
                    >
                      {c.status}
                    </td>
                  )}
                  <td className="py-1.5 font-mono text-[10px] text-muted-foreground">
                    <div>{metricPreview(c.metrics)}</div>
                    {l2bits.length ? (
                      <div className="mt-0.5 opacity-80">
                        {l2bits.join(" · ")}
                      </div>
                    ) : null}
                    {c.error ? (
                      <div className="mt-0.5 text-destructive">
                        {opsDisplayText(c.error)}
                      </div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!cases.length ? (
          <p className="mt-2 text-sm text-muted-foreground">
            该筛选下无 case。
          </p>
        ) : null}
      </div>

      <details className="rounded-md border border-border/80 text-xs">
        <summary className="cursor-pointer px-2 py-1.5 text-muted-foreground">
          原始 result JSON
        </summary>
        <pre className="max-h-64 overflow-auto border-t border-border/60 p-2 font-mono text-[10px]">
          {JSON.stringify(suite.result || {}, null, 2)}
        </pre>
      </details>

      {patchViewer ? (
        <OpsTextViewerModal
          open
          title={patchViewer.title}
          downloadName={`${(patchViewer.title.split(" ")[0] || "patch").replace(/[^\w.-]+/g, "_")}.diff`}
          content={patchViewer.content}
          onClose={() => setPatchViewer(null)}
        />
      ) : null}
    </div>
  );
}
