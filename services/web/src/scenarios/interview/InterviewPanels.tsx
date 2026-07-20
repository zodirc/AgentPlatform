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
        <Card className="border-sky-900/50 bg-sky-950/20">
          <CardTitle className="text-sky-200">文档大纲</CardTitle>
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
        showExecute={!wb.busy && !wb.awaitingApproval}
        executeDisabled={wb.busy || wb.actionBusy}
        onExecute={() => void wb.handleExecutePlan()}
      />
    </>
  );
}
