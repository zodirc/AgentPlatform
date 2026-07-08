import type { ContextUsage, TokenUsage } from "../../shared/workbench/types";

function formatTokens(n: number | undefined): string {
  const value = Number(n ?? 0);
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

type Props = {
  contextUsage: ContextUsage | null;
  tokenUsage: TokenUsage | null;
};

export function UsageMeter({ contextUsage, tokenUsage }: Props) {
  const ctxAfter = contextUsage?.tokens_after;
  const ctxBudget = contextUsage?.token_budget;
  const hasContext =
    contextUsage != null && typeof ctxAfter === "number" && typeof ctxBudget === "number";
  const hasToken =
    tokenUsage != null &&
    (Number(tokenUsage.input_tokens ?? 0) > 0 || Number(tokenUsage.output_tokens ?? 0) > 0);

  if (!hasContext && !hasToken) return null;

  const pct =
    hasContext && ctxBudget && ctxBudget > 0
      ? Math.min(100, Math.round((Number(ctxAfter) / ctxBudget) * 100))
      : 0;

  const sourceLabel =
    contextUsage?.source === "provider"
      ? "provider"
      : tokenUsage?.source === "provider"
        ? "provider"
        : tokenUsage?.source === "mixed"
          ? "mixed"
          : "est.";

  return (
    <div className="mt-2 space-y-1 border-t border-white/10 pt-2 text-[11px] opacity-80">
      {hasContext ? (
        <div>
          <div className="mb-1 flex items-center justify-between gap-2">
            <span>上下文窗口</span>
            <span>
              {formatTokens(ctxAfter)} / {formatTokens(ctxBudget)} ({pct}%) · {sourceLabel}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded bg-black/30">
            <div
              className={`h-full rounded ${
                pct >= 90 ? "bg-rose-400" : pct >= 70 ? "bg-amber-400" : "bg-sky-400"
              }`}
              style={{ width: `${Math.max(pct, 1)}%` }}
            />
          </div>
          <p className="mt-1 truncate opacity-70">
            sys={formatTokens(contextUsage?.system_tokens)} · tools=
            {formatTokens(contextUsage?.tools_tokens)} · msgs=
            {formatTokens(contextUsage?.messages_tokens)}
          </p>
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
