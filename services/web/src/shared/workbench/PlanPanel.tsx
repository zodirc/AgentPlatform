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
  /**
   * panel — sidebar / standalone chrome (primary card).
   * chat — Cursor-like checklist inside the assistant message stream.
   */
  variant?: "panel" | "chat";
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
  chat,
}: {
  item: PlanItem;
  active: boolean;
  staleInProgress: boolean;
  chat?: boolean;
}) {
  const s = normalizePlanStatus(item.status);
  if (chat) {
    const markClass =
      s === "completed"
        ? "text-emerald-600 dark:text-emerald-400"
        : s === "in_progress" && !staleInProgress
          ? "text-amber-600 dark:text-amber-400"
          : "text-muted-foreground";
    return (
      <li className="flex items-start gap-2 py-0.5 text-[13px] leading-snug">
        <span className={`mt-0.5 shrink-0 font-medium ${markClass}`} aria-hidden>
          <StatusMark status={s} />
        </span>
        <span
          className={
            s === "completed" || s === "cancelled"
              ? "text-muted-foreground line-through decoration-muted-foreground/50"
              : active
                ? "font-medium text-foreground"
                : "text-foreground/90"
          }
        >
          {item.title}
          {s === "in_progress" && !staleInProgress ? (
            <span className="ml-1.5 text-[10px] font-medium text-amber-700 dark:text-amber-300">
              进行中
            </span>
          ) : null}
        </span>
      </li>
    );
  }
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
  variant = "panel",
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
  const chat = variant === "chat";

  // Formal Plan awaiting consent / live turn → expand; historical snapshot → collapse.
  const preferOpen = canExecute || turnLive || formal;
  const [open, setOpen] = useState(preferOpen);

  useEffect(() => {
    if (preferOpen) setOpen(true);
  }, [preferOpen, plan?.plan_id, total]);

  if (!items.length) return null;

  if (chat) {
    const badge = formal ? "计划" : "进度";
    const awaiting = canExecute || planPhase === "ready";
    return (
      <div
        className={`rounded-lg border-l-[3px] px-3 py-2.5 ${
          awaiting
            ? "border-l-amber-500 bg-amber-500/10"
            : formal
              ? "border-l-sky-500 bg-sky-500/10"
              : "border-l-muted-foreground/40 bg-muted/40"
        }`}
      >
        <div className="flex items-start justify-between gap-2">
          <button
            type="button"
            className="min-w-0 flex-1 rounded text-left hover:opacity-90"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide ${
                  awaiting
                    ? "bg-amber-500/20 text-amber-800 dark:text-amber-200"
                    : formal
                      ? "bg-sky-500/20 text-sky-800 dark:text-sky-200"
                      : "bg-muted text-muted-foreground"
                }`}
              >
                {badge}
              </span>
              <span className="text-[12px] font-medium text-foreground">
                {title}
              </span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {done}/{total}
              </span>
            </div>
            {awaiting ? (
              <p className="mt-1 text-[11px] font-medium text-amber-800/90 dark:text-amber-200/90">
                待你确认后才会改文件 / 执行清单
              </p>
            ) : phaseLabel ? (
              <p className="mt-1 text-[11px] text-muted-foreground">{phaseLabel}</p>
            ) : null}
            {!open ? (
              <p className="mt-0.5 truncate text-[13px] text-foreground/90">
                {live
                  ? `${livePrefix} · ${live.title}`
                  : summary || `${total} 项`}
              </p>
            ) : null}
          </button>
        </div>
        {open ? (
          <>
            {summary ? (
              <p className="mt-2 text-[12px] leading-relaxed text-foreground/80">
                {summary}
              </p>
            ) : null}
            {stale ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                回合已结束；清单步骤未全部勾完
              </p>
            ) : null}
            <ul className="mt-2 space-y-1 border-t border-border/50 pt-2">
              {items.map((item) => (
                <PlanItemRow
                  key={item.id}
                  item={item}
                  active={live?.id === item.id}
                  staleInProgress={stale}
                  chat
                />
              ))}
            </ul>
            {canExecute ? (
              <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-amber-500/25 pt-2.5">
                <p className="text-[11px] text-amber-900/80 dark:text-amber-100/80">
                  确认这份计划后开始执行
                </p>
                <button
                  type="button"
                  className="shrink-0 rounded-md bg-amber-600 px-3 py-1.5 text-[12px] font-semibold text-white shadow-sm hover:bg-amber-500 disabled:opacity-40"
                  disabled={executeDisabled}
                  onClick={onExecute}
                >
                  按此执行
                </button>
              </div>
            ) : null}
          </>
        ) : (
          canExecute ? (
            <div className="mt-2 flex justify-end">
              <button
                type="button"
                className="shrink-0 rounded-md bg-amber-600 px-3 py-1.5 text-[12px] font-semibold text-white shadow-sm hover:bg-amber-500 disabled:opacity-40"
                disabled={executeDisabled}
                onClick={onExecute}
              >
                按此执行
              </button>
            </div>
          ) : null
        )}
      </div>
    );
  }

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
