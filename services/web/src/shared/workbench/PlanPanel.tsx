import type { PlanArtifact, PlanItem } from "../../shared/workbench/plan";
import {
  currentPlanStep,
  normalizePlanStatus,
  planHasOpenItems,
} from "../../shared/workbench/plan";

type Props = {
  plan: PlanArtifact | null;
  /** Show execute CTA when plan has open items and turn is idle. */
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
  pending: "text-slate-400",
  in_progress: "text-amber-300",
  completed: "text-emerald-300",
  cancelled: "text-slate-500 line-through",
};

function StatusMark({ status }: { status: string }) {
  const s = normalizePlanStatus(status);
  if (s === "completed") return <span aria-hidden>✓</span>;
  if (s === "in_progress") return <span aria-hidden>●</span>;
  if (s === "cancelled") return <span aria-hidden>×</span>;
  return <span aria-hidden>○</span>;
}

function PlanItemRow({ item, active }: { item: PlanItem; active: boolean }) {
  const s = normalizePlanStatus(item.status);
  return (
    <li
      className={`rounded px-3 py-2 ${
        active ? "bg-amber-950/40 ring-1 ring-amber-800/50" : "bg-slate-950"
      }`}
    >
      <div className="flex items-start gap-2 text-xs">
        <span className={`mt-0.5 shrink-0 ${STATUS_CLASS[s] ?? "text-slate-400"}`}>
          <StatusMark status={s} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-slate-200">{item.title}</p>
          <p className={`mt-0.5 text-[10px] ${STATUS_CLASS[s] ?? "text-slate-500"}`}>
            {STATUS_LABEL[s] ?? s}
          </p>
        </div>
      </div>
    </li>
  );
}

export function PlanPanel({
  plan,
  showExecute = false,
  executeDisabled = false,
  onExecute,
  compact = false,
}: Props) {
  if (!plan?.items?.length) return null;

  const current = currentPlanStep(plan);
  const canExecute =
    showExecute && Boolean(onExecute) && planHasOpenItems(plan);

  return (
    <section
      className={`rounded-lg border border-violet-900/50 bg-violet-950/20 ${
        compact ? "px-3 py-2" : "px-4 py-3"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium text-violet-200">任务计划</p>
          {plan.summary ? (
            <p className="mt-0.5 truncate text-[11px] text-slate-400">
              {plan.summary}
            </p>
          ) : null}
        </div>
        {canExecute ? (
          <button
            type="button"
            className="shrink-0 rounded-md bg-violet-700 px-2.5 py-1 text-[11px] font-medium text-violet-50 hover:bg-violet-600 disabled:opacity-40"
            disabled={executeDisabled}
            onClick={onExecute}
          >
            按此执行
          </button>
        ) : null}
      </div>
      <ul className={`mt-2 space-y-1 ${compact ? "max-h-40 overflow-y-auto" : ""}`}>
        {plan.items.map((item) => (
          <PlanItemRow
            key={item.id}
            item={item}
            active={current?.id === item.id}
          />
        ))}
      </ul>
    </section>
  );
}
