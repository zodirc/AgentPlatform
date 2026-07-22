import type { ReactNode } from "react";
import { Card, CardTitle } from "../components/ui/card";
import { PlanPanel } from "../shared/workbench/PlanPanel";
import type { WorkbenchState } from "../shared/workbench/types";
import { CitationView } from "./writing/CitationView";
import { DocumentOutlineView } from "./writing/DocumentOutlineView";
import { WritingSidebarTools } from "./writing/WritingSidebarTools";

type Props = {
  wb: WorkbenchState;
  onOpenSources?: () => void;
  onOpenRagDebug?: () => void;
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

  if (id === "interview") {
    return (
      <div className="space-y-3">
        {planBlock}
        <CitationView items={wb.view?.tool_timeline ?? []} />
        <DocumentOutline wb={wb} />
      </div>
    );
  }

  return <div className="space-y-3">{planBlock}</div>;
}
