import { useWorkbench } from "../../shared/workbench/useWorkbench";
import { WorkbenchShell } from "../../shared/workbench/WorkbenchShell";
import { InterviewPanels } from "./InterviewPanels";

export function InterviewWorkbench() {
  const wb = useWorkbench({ scenarioId: "interview", title: "访谈纪要工作台" });
  return (
    <WorkbenchShell wb={wb}>
      <InterviewPanels wb={wb} />
    </WorkbenchShell>
  );
}
