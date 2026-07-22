import { CitationView } from "../writing/CitationView";
import { DocumentOutlineView } from "../writing/DocumentOutlineView";
import { Card, CardTitle } from "../../components/ui/card";
import { PlanPanel } from "../../shared/workbench/PlanPanel";
import type { WorkbenchState } from "../../shared/workbench/types";

type Props = {
  wb: WorkbenchState;
};

export function InterviewPanels({ wb }: Props) {
  const view = wb.view;
  return (
    <>
      <CitationView items={view?.tool_timeline ?? []} />
      {view?.artifacts?.some((a) => a.type === "outline") && (
        <Card className="border-primary/30 bg-primary/10">
          <CardTitle className="text-primary">文档大纲</CardTitle>
          <DocumentOutlineView
            artifact={
              view.artifacts.find((a) => a.type === "outline") as {
                content?: string;
              }
            }
          />
        </Card>
      )}
      <PlanPanel
        plan={wb.plan}
        turnStatus={wb.displayStatus}
        planPhase={wb.planPhase}
        showExecute={wb.canExecutePlan}
        executeDisabled={wb.busy || wb.actionBusy}
        onExecute={() => void wb.handleExecutePlan()}
      />
    </>
  );
}
