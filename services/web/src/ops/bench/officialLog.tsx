import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { opsRawPath } from "../OpsShell";
import { isOpsErrorLogLine } from "../opsLogStyle";
import { describeMetric } from "./metricGlossary";
import type { OfficialLogItem } from "./types";

const TURN_ID_IN_LOG = /turn_id=([0-9a-fA-F-]{36})/;

export function OfficialLogLine({
  line,
  secret,
}: {
  line: string;
  secret: string;
}) {
  const nodes: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(TURN_ID_IN_LOG.source, "g");
  while ((m = re.exec(line)) !== null) {
    if (m.index > last) nodes.push(line.slice(last, m.index));
    const id = m[1];
    nodes.push(
      <Link
        key={`${id}-${m.index}`}
        to={opsRawPath(secret, id)}
        className="underline decoration-dotted underline-offset-2 text-foreground hover:text-primary"
        title="打开 Raw 快照看逐步 turn_events"
        target="_blank"
        rel="noreferrer"
      >
        turn_id={id}
      </Link>,
    );
    last = m.index + m[0].length;
  }
  if (last < line.length) nodes.push(line.slice(last));
  if (!nodes.length) return <>{line}</>;
  return <>{nodes}</>;
}

/** Detail「日志」Tab: errors + milestones only (full stream stays in the live pane). */
export function isOpsKeyLogItem(item: OfficialLogItem): boolean {
  const kind = String(item.kind || "").toLowerCase();
  if (
    kind === "phase" ||
    kind === "run_started" ||
    kind === "run_finished" ||
    kind === "case_started" ||
    kind === "case_finished"
  ) {
    return true;
  }
  if (String(item.status || "").toLowerCase() === "fail") return true;
  const s = String(item.message || "").trim();
  if (!s) return false;
  if (isOpsErrorLogLine(s)) return true;
  if (/^\[ops\]/i.test(s)) return true;
  if (/^stop requested/i.test(s)) return true;
  if (/^\[L1\]\s+suite start\b/i.test(s)) return true;
  if (/^\[L1\]\s+turn start\b/i.test(s)) return true;
  if (/^\[L1\]\s+turn done\b/i.test(s)) return true;
  if (/^\[L1\]\s+fail\b/i.test(s)) return true;
  if (/^\[L1\]\s+pull\b/i.test(s)) return true;
  if (/^\[L1\]\s+mirror prewarm\b/i.test(s)) return true;
  if (/^\[L1\]\s+checkout\b/i.test(s)) return true;
  if (/\bplan\s+n=/i.test(s)) return true;
  if (/^\[L1\]\s+(retrieval|context|coding)\s+done\b/i.test(s)) return true;
  if (/^\[L1\]\s+coding infer done\b/i.test(s)) return true;
  if (/^\[L1\]\s+context done\b/i.test(s)) return true;
  if (/^\[L1\]\s+retrieval done\b/i.test(s)) return true;
  if (/^\[L1\]\s+workspace_index\s+enqueue\b/i.test(s)) return true;
  if (
    /^\[L1\]\s+workspace_index\s+\S+\s+status=(ready|stale|error|cancelled|watch_timeout|wait_timeout|wait_done)\b/i.test(
      s,
    )
  ) {
    return true;
  }
  // Full harness breadcrumb stream (progress / stage / case / done).
  if (/^\[L1\]\s+coding\s+harness\b/i.test(s)) return true;
  return false;
}

export function liveLogLineClass(line: string): string | undefined {
  if (isOpsErrorLogLine(line)) return "font-semibold text-destructive";
  if (
    line.includes("[phase]") ||
    line.startsWith("[pull]") ||
    line.startsWith("[progress] pull") ||
    line.startsWith("[L1] pull") ||
    line.startsWith("[L1] turn ")
  ) {
    return "font-semibold text-foreground";
  }
  if (line.startsWith("[L1] workspace_index")) {
    if (/\bstatus=ready\b/i.test(line)) return "font-semibold text-foreground";
    if (/\bstatus=(error|poll_error|watch_timeout)\b/i.test(line)) {
      return "font-semibold text-destructive";
    }
    return "text-muted-foreground";
  }
  if (line.startsWith("[L1] ·") || line.startsWith("[L1] …")) {
    return "text-muted-foreground";
  }
  return undefined;
}

export function MetricBars({ metrics }: { metrics: Record<string, number> }) {
  const entries = Object.entries(metrics);
  if (!entries.length) {
    return (
      <p className="text-sm text-muted-foreground">
        本次尚无数值指标（套件未完成、dry /
        skip_api，或旧跑次未按套件回写时常见）。
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => {
        const width = Math.max(0, Math.min(100, v > 1 ? v : v * 100));
        const info = describeMetric(k);
        return (
          <div key={k} title={`${info.en} — ${info.effect}`}>
            <div className="mb-0.5 flex justify-between gap-2 text-xs">
              <span className="min-w-0 truncate">
                <span className="text-foreground">
                  {info.scope ? `${info.scope} · ${info.zh}` : info.zh}
                </span>
                <span className="ml-1.5 font-mono text-[11px] text-muted-foreground">
                  {k}
                </span>
              </span>
              <strong className="shrink-0 tabular-nums">{v.toFixed(4)}</strong>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-foreground/75"
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
