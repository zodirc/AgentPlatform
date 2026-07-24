import { useEffect, useState } from "react";

import type { PlanArtifact, PlanItem, PlanPhase } from "./plan";
import {
  isActiveTurnStatus,
  isFormalPlanPhase,
  livePlanStep,
  normalizePlanStatus,
  planHasStaleInProgress,
  planPanelSummaryDisplay,
  planPanelTitle,
  PLAN_PHASE_LABEL,
} from "./plan";

type Props = {
  plan: PlanArtifact | null;
  /** Turn display status — drives whether in_progress is live or stale. */
  turnStatus?: string | null;
  /** Platform Plan phase (docs/25). */
  planPhase?: PlanPhase;
  /** Caller already decided CTA is appropriate (proposed-only + awaiting confirm). */
  showExecute?: boolean;
  executeDisabled?: boolean;
  onExecute?: () => void;
  compact?: boolean;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "待办",
  in_progress: "进行中",
  completed: "完成",
  cancelled: "取消",
};

const STATUS_CLASS: Record<string, string> = {
  pending: "text-muted-foreground",
  in_progress: "text-warning",
  completed: "text-success",
  cancelled: "text-muted-foreground line-through",
};

function StatusMark({ status }: { status: string }) {
  const s = normalizePlanStatus(status);
  if (s === "completed") return <span aria-hidden>✓</span>;
  if (s === "in_progress") return <span aria-hidden>●</span>;
  if (s === "cancelled") return <span aria-hidden>×</span>;
  return <span aria-hidden>○</span>;
}

function PlanItemRow({
  item,
  active,
  staleInProgress,
}: {
  item: PlanItem;
  active: boolean;
  staleInProgress: boolean;
}) {
  const s = normalizePlanStatus(item.status);
  const label =
    s === "in_progress" && staleInProgress
      ? "未勾完（回合已结束）"
      : (STATUS_LABEL[s] ?? s);
  const color =
    s === "in_progress" && staleInProgress
      ? "text-muted-foreground"
      : (STATUS_CLASS[s] ?? "text-muted-foreground");
  return (
    <li
      className={`rounded px-3 py-2 ${
        active ? "bg-warning-muted ring-1 ring-warning/40" : "bg-background"
      }`}
    >
      <div className="flex items-start gap-2 text-xs">
        <span className={`mt-0.5 shrink-0 ${color}`}>
          <StatusMark status={s} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-foreground">{item.title}</p>
          <p className={`mt-0.5 text-[10px] ${color}`}>{label}</p>
        </div>
      </div>
    </li>
  );
}

function progressCounts(items: PlanItem[]): { done: number; total: number } {
  const total = items.length;
  const done = items.filter(
    (item) => normalizePlanStatus(item.status) === "completed",
  ).length;
  return { done, total };
}

export function PlanPanel({
  plan,
  turnStatus = null,
  planPhase = "off",
  showExecute = false,
  executeDisabled = false,
  onExecute,
  compact = false,
}: Props) {
  const items = plan?.items ?? [];
  const live = livePlanStep(plan, turnStatus);
  const stale = planHasStaleInProgress(plan, turnStatus);
  const turnLive = isActiveTurnStatus(turnStatus);
  const canExecute = showExecute && Boolean(onExecute);
  const phaseLabel = PLAN_PHASE_LABEL[planPhase];
  const formal = isFormalPlanPhase(planPhase);
  const title = planPanelTitle(planPhase);
  const summary = planPanelSummaryDisplay(plan?.summary, planPhase);
  const livePrefix = formal ? "当前步" : "进行中";
  const { done, total } = progressCounts(items);

  // Formal Plan awaiting consent / live turn → expand; historical snapshot → collapse.
  const preferOpen = canExecute || turnLive || formal;
  const [open, setOpen] = useState(preferOpen);

  useEffect(() => {
    if (preferOpen) setOpen(true);
  }, [preferOpen, plan?.plan_id, total]);

  if (!items.length) return null;

  return (
    <section
      className={`rounded-lg border border-primary/30 bg-primary/10 ${
        compact ? "px-3 py-2" : "px-4 py-3"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          className="min-w-0 flex-1 rounded text-left hover:opacity-90"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 shrink-0 text-[10px] text-primary"
              aria-hidden
            >
              {open ? "▼" : "▶"}
            </span>
            <p className="text-xs font-medium text-primary">
              {title}
              <span className="ml-1.5 font-normal text-muted-foreground">
                {done}/{total}
              </span>
            </p>
          </div>
          {!open ? (
            <p className="mt-0.5 truncate pl-4 text-[11px] text-warning">
              {live
                ? `${livePrefix} · ${live.title}`
                : summary || phaseLabel || `${total} 项 · 点击展开`}
            </p>
          ) : null}
        </button>
        {canExecute ? (
          <button
            type="button"
            className="shrink-0 rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            disabled={executeDisabled}
            onClick={onExecute}
          >
            按此执行
          </button>
        ) : null}
      </div>

      {open ? (
        <>
          <div className="mt-1 min-w-0 pl-4">
            {!formal ? (
              <p className="text-[11px] text-muted-foreground">
                Agent 进度清单 · 写盘批准一次后，本回合后续编辑免批
              </p>
            ) : null}
            {phaseLabel ? (
              <p className="mt-0.5 text-[11px] text-primary/90">{phaseLabel}</p>
            ) : null}
            {summary ? (
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {summary}
              </p>
            ) : null}
            {live ? (
              <p className="mt-0.5 text-[11px] text-warning">
                {livePrefix} · {live.title}
              </p>
            ) : null}
            {stale ? (
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                回合已结束；清单步骤未全部勾完
              </p>
            ) : null}
            {!turnLive && !stale && !showExecute && planPhase === "off" ? (
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                历史进度快照
              </p>
            ) : null}
          </div>
          <ul
            className={`mt-2 space-y-1 ${compact ? "max-h-40 overflow-y-auto" : ""}`}
          >
            {items.map((item) => (
              <PlanItemRow
                key={item.id}
                item={item}
                active={live?.id === item.id}
                staleInProgress={stale}
              />
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
