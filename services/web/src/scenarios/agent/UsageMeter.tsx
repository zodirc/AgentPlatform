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

/**
 * Display layers aligned with Cursor Context Usage naming, mapped to our
 * wire channels (system / tools[] / project user / messages history).
 * Skills / Subagent are not independent metered layers on this platform.
 */
const DISPLAY_SEGMENTS: Array<{
  id: string;
  label: string;
  color: string;
  keys: Array<keyof ContextWindowBreakdown>;
}> = [
  {
    id: "system_prompt",
    label: "System prompt",
    color: "bg-muted-foreground",
    keys: ["system"],
  },
  {
    id: "tool_definitions",
    label: "Tool definitions",
    color: "bg-primary/70",
    keys: ["tools"],
  },
  {
    id: "rules",
    label: "Rules",
    color: "bg-success/70",
    keys: ["project"],
  },
  {
    id: "writing_ctx",
    label: "Writing ctx",
    color: "bg-primary/55",
    keys: ["volatile"],
  },
  {
    id: "runtime",
    label: "Runtime",
    color: "bg-warning/70",
    keys: ["runtime"],
  },
  {
    id: "session",
    label: "Session",
    color: "bg-success",
    keys: ["session"],
  },
  {
    id: "conversation",
    label: "Conversation",
    color: "bg-primary",
    keys: ["user", "assistant", "tool_results", "compaction"],
  },
];

function segmentValue(
  breakdown: ContextWindowBreakdown,
  keys: Array<keyof ContextWindowBreakdown>,
): number {
  return keys.reduce((sum, key) => sum + Number(breakdown[key] ?? 0), 0);
}

type Props = {
  contextUsage: ContextUsage | null;
  tokenUsage: TokenUsage | null;
  /** Thin one-line meter for the status strip (hides breakdown grid). */
  compact?: boolean;
};

export function UsageMeter({
  contextUsage,
  tokenUsage,
  compact = false,
}: Props) {
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
    ? DISPLAY_SEGMENTS.reduce(
        (sum, seg) => sum + segmentValue(breakdown, seg.keys),
        0,
      )
    : 0;
  const barDenominator =
    ctxBudget && ctxBudget > 0 ? ctxBudget : breakdownTotal || ctxAfter || 1;

  if (compact) {
    return (
      <div className="mt-2 flex min-w-0 items-center gap-3 border-t border-border/60 pt-2 text-[11px] text-muted-foreground">
        {hasContext ? (
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <div className="h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full transition-[width] ${
                  fillPct >= 90
                    ? "bg-destructive"
                    : fillPct >= 70
                      ? "bg-warning"
                      : "bg-primary"
                }`}
                style={{ width: `${Math.max(fillPct, 1)}%` }}
              />
            </div>
            <span className="shrink-0 tabular-nums">
              {formatTokens(ctxAfter)}/{formatTokens(ctxBudget)} · {fillPct}%
            </span>
          </div>
        ) : null}
        {hasToken ? (
          <span className="shrink-0 tabular-nums">
            in {formatTokens(tokenUsage?.input_tokens)} · out{" "}
            {formatTokens(tokenUsage?.output_tokens)}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-1 border-t border-border pt-2 text-[11px] opacity-80">
      {hasContext ? (
        <div>
          <div className="mb-1 flex items-center justify-between gap-2">
            <span>Context Usage</span>
            <span>
              {formatTokens(ctxAfter)} / {formatTokens(ctxBudget)} ·{" "}
              {fillPct}% full · {sourceLabel}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded bg-muted">
            <div
              className={`h-full rounded ${
                fillPct >= 90
                  ? "bg-destructive"
                  : fillPct >= 70
                    ? "bg-warning"
                    : "bg-primary"
              }`}
              style={{ width: `${Math.max(fillPct, 1)}%` }}
            />
          </div>

          {breakdown && breakdownTotal > 0 ? (
            <div className="mt-2 space-y-1">
              <div className="flex h-2 overflow-hidden rounded bg-muted">
                {DISPLAY_SEGMENTS.map((seg) => {
                  const value = segmentValue(breakdown, seg.keys);
                  if (value <= 0) return null;
                  const width = Math.max(0.5, (value / barDenominator) * 100);
                  return (
                    <div
                      key={seg.id}
                      className={`${seg.color} h-full`}
                      style={{ width: `${width}%` }}
                      title={`${seg.label}: ${formatTokens(value)}`}
                    />
                  );
                })}
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] opacity-70">
                {DISPLAY_SEGMENTS.map((seg) => {
                  const value = segmentValue(breakdown, seg.keys);
                  if (value <= 0) return null;
                  const segPct = Math.round((value / barDenominator) * 100);
                  return (
                    <div key={seg.id} className="flex items-center gap-1">
                      <span
                        className={`inline-block h-2 w-2 rounded-sm ${seg.color}`}
                      />
                      <span className="truncate">
                        {seg.label}{" "}
                        <span className="opacity-80">
                          {formatTokens(value)} · {segPct}%
                        </span>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <p className="mt-1 truncate opacity-70">
              system prompt={formatTokens(contextUsage?.system_tokens)} · tool
              definitions={formatTokens(contextUsage?.tools_tokens)} · msgs=
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
          本回合累计 in={formatTokens(tokenUsage?.input_tokens)} · out=
          {formatTokens(tokenUsage?.output_tokens)}
          {tokenUsage?.source ? ` · ${tokenUsage.source}` : ""}
        </p>
      ) : (
        <p className="opacity-60">本回合累计：首轮模型返回后更新</p>
      )}
    </div>
  );
}
