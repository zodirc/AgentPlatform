import type { ReactNode } from "react";
import { Users } from "lucide-react";
import { Card, CardTitle } from "../components/ui/card";
import { PlanPanel } from "../shared/workbench/PlanPanel";
import type { WorkbenchState } from "../shared/workbench/types";
import {
  COLLAB_ROLES,
  collabTeamSummary,
} from "./collab/CollabTeamPanel";
import { CitationView } from "./writing/CitationView";
import { DocumentOutlineView } from "./writing/DocumentOutlineView";
import { WritingSidebarTools } from "./writing/WritingSidebarTools";

type Props = {
  wb: WorkbenchState;
  onOpenSources?: () => void;
  onOpenRagDebug?: () => void;
  onOpenCollabTeam?: () => void;
};

function DocumentOutline({ wb }: Props) {
  const outline = wb.view?.artifacts?.find((a) => a.type === "outline") as
    | { content?: string }
    | undefined;
  if (!outline) return null;
  return (
    <Card className="border-primary/30 bg-primary/10">
      <CardTitle className="text-primary">文档大纲</CardTitle>
      <DocumentOutlineView artifact={outline} />
    </Card>
  );
}

/** Scenario-specific panels injected into the shared sidebar. */
export function ScenarioSidebarExtras({
  wb,
  onOpenSources,
  onOpenRagDebug,
  onOpenCollabTeam,
}: Props): ReactNode {
  const id = wb.scenarioId;
  const planBlock = (
    <PlanPanel
      plan={wb.plan}
      turnStatus={wb.displayStatus}
      planPhase={wb.planPhase}
      showExecute={wb.canExecutePlan}
      executeDisabled={wb.busy || wb.actionBusy}
      onExecute={() => void wb.handleExecutePlan()}
      compact
    />
  );

  if (id === "writing") {
    return (
      <div className="space-y-3">
        {onOpenSources && onOpenRagDebug ? (
          <WritingSidebarTools
            onOpenSources={onOpenSources}
            onOpenRagDebug={onOpenRagDebug}
          />
        ) : null}
        {planBlock}
        <CitationView items={wb.view?.tool_timeline ?? []} />
        <DocumentOutline wb={wb} />
      </div>
    );
  }

  if (id === "intel") {
    return (
      <div className="space-y-3">
        {onOpenSources && onOpenRagDebug ? (
          <WritingSidebarTools
            onOpenSources={onOpenSources}
            onOpenRagDebug={onOpenRagDebug}
          />
        ) : null}
        {planBlock}
        <CitationView items={wb.view?.tool_timeline ?? []} />
        <DocumentOutline wb={wb} />
      </div>
    );
  }

  if (id === "collab") {
    return (
      <div className="space-y-3">
        <button
          type="button"
          onClick={onOpenCollabTeam}
          disabled={!onOpenCollabTeam}
          className="w-full rounded-lg border border-border bg-card/60 p-3 text-left transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:opacity-60"
          title="打开团队子窗口"
        >
          <div className="mb-1 flex items-center gap-2">
            <Users className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
            <span className="text-xs font-medium text-foreground/90">
              团队 / 子任务
            </span>
          </div>
          <p className="text-[11px] text-muted-foreground">
            {collabTeamSummary(wb.subagents)} · 点击打开子窗口
          </p>
          <p className="mt-2 text-[10px] text-muted-foreground/80">
            可用：{COLLAB_ROLES.map((r) => r.label).join(" · ")}
          </p>
        </button>
        {planBlock}
      </div>
    );
  }

  return <div className="space-y-3">{planBlock}</div>;
}
