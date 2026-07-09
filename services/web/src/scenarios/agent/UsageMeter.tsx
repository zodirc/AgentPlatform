import type {
  ContextUsage,
  ContextWindowBreakdown,
  TokenUsage,
} from "../../shared/workbench/types";

function formatTokens(n: number | undefined): string {
  const value = Number(n ?? 0);
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

const BREAKDOWN_SEGMENTS: Array<{
  key: keyof ContextWindowBreakdown;
  label: string;
  color: string;
}> = [
  { key: "system", label: "System", color: "bg-violet-400" },
  { key: "tools", label: "Tools", color: "bg-indigo-400" },
  { key: "session", label: "Session", color: "bg-emerald-400" },
  { key: "user", label: "User", color: "bg-sky-400" },
  { key: "assistant", label: "Assistant", color: "bg-cyan-400" },
  { key: "tool_results", label: "Tool results", color: "bg-amber-400" },
  { key: "compaction", label: "Compact", color: "bg-slate-400" },
];

type Props = {
  contextUsage: ContextUsage | null;
  tokenUsage: TokenUsage | null;
};

export function UsageMeter({ contextUsage, tokenUsage }: Props) {
  const ctxAfter = contextUsage?.tokens_after;
  const ctxBudget = contextUsage?.token_budget;
  const hasContext =
    contextUsage != null &&
    typeof ctxAfter === "number" &&
    typeof ctxBudget === "number";
  const hasToken =
    tokenUsage != null &&
    (Number(tokenUsage.input_tokens ?? 0) > 0 ||
      Number(tokenUsage.output_tokens ?? 0) > 0);

  if (!hasContext && !hasToken) return null;

  const pct =
    hasContext && ctxBudget && ctxBudget > 0
      ? Math.min(100, Math.round((Number(ctxAfter) / ctxBudget) * 100))
      : 0;

  const fillPct =
    contextUsage?.fill_ratio != null && contextUsage.fill_ratio > 0
      ? Math.min(100, Math.round(contextUsage.fill_ratio * 100))
      : pct;

  const sourceLabel =
    contextUsage?.source === "provider"
      ? "provider"
      : tokenUsage?.source === "provider"
        ? "provider"
        : tokenUsage?.source === "mixed"
          ? "mixed"
          : "est.";

  const breakdown = contextUsage?.breakdown;
  const breakdownTotal = breakdown
    ? BREAKDOWN_SEGMENTS.reduce(
        (sum, seg) => sum + Number(breakdown[seg.key] ?? 0),
        0,
      )
    : 0;
  const barDenominator =
    ctxBudget && ctxBudget > 0 ? ctxBudget : breakdownTotal || ctxAfter || 1;

  return (
    <div className="mt-2 space-y-1 border-t border-white/10 pt-2 text-[11px] opacity-80">
      {hasContext ? (
        <div>
          <div className="mb-1 flex items-center justify-between gap-2">
            <span>上下文窗口</span>
            <span>
              {formatTokens(ctxAfter)} / {formatTokens(ctxBudget)} ({fillPct}%)
              · {sourceLabel}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded bg-black/30">
            <div
              className={`h-full rounded ${
                fillPct >= 90
                  ? "bg-rose-400"
                  : fillPct >= 70
                    ? "bg-amber-400"
                    : "bg-sky-400"
              }`}
              style={{ width: `${Math.max(fillPct, 1)}%` }}
            />
          </div>

          {breakdown && breakdownTotal > 0 ? (
            <div className="mt-2 space-y-1">
              <div className="flex h-2 overflow-hidden rounded bg-black/30">
                {BREAKDOWN_SEGMENTS.map((seg) => {
                  const value = Number(breakdown[seg.key] ?? 0);
                  if (value <= 0) return null;
                  const width = Math.max(0.5, (value / barDenominator) * 100);
                  return (
                    <div
                      key={seg.key}
                      className={`${seg.color} h-full`}
                      style={{ width: `${width}%` }}
                      title={`${seg.label}: ${formatTokens(value)}`}
                    />
                  );
                })}
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] opacity-70">
                {BREAKDOWN_SEGMENTS.map((seg) => {
                  const value = Number(breakdown[seg.key] ?? 0);
                  if (value <= 0) return null;
                  const segPct = Math.round((value / barDenominator) * 100);
                  return (
                    <div key={seg.key} className="flex items-center gap-1">
                      <span
                        className={`inline-block h-2 w-2 rounded-sm ${seg.color}`}
                      />
                      <span className="truncate">
                        {seg.label} {formatTokens(value)} ({segPct}%)
                      </span>
                    </div>
                  );
                })}
              </div>
              <p className="text-[10px] opacity-50">
                Rules 合并在 System；平台暂无独立 Skills 层
              </p>
            </div>
          ) : (
            <p className="mt-1 truncate opacity-70">
              sys={formatTokens(contextUsage?.system_tokens)} · tools=
              {formatTokens(contextUsage?.tools_tokens)} · msgs=
              {formatTokens(contextUsage?.messages_tokens)}
            </p>
          )}

          {contextUsage?.strategies && contextUsage.strategies.length > 0 ? (
            <p className="truncate opacity-70">
              压缩: {contextUsage.strategies.join(" → ")}
            </p>
          ) : null}
        </div>
      ) : null}
      {hasToken ? (
        <p>
          模型用量 in={formatTokens(tokenUsage?.input_tokens)} · out=
          {formatTokens(tokenUsage?.output_tokens)}
          {tokenUsage?.source ? ` · ${tokenUsage.source}` : ""}
        </p>
      ) : (
        <p className="opacity-60">模型用量：本步结束后更新</p>
      )}
    </div>
  );
}
