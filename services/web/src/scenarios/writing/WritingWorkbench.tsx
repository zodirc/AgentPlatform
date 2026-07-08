import { useWorkbench } from "../../shared/workbench/useWorkbench";
import { WorkbenchShell } from "../../shared/workbench/WorkbenchShell";
import { WritingPanels } from "./WritingPanels";

export function WritingWorkbench() {
  const wb = useWorkbench({ scenarioId: "writing", title: "写作工作台" });
  return (
    <WorkbenchShell wb={wb}>
      <WritingPanels wb={wb} />
    </WorkbenchShell>
  );
}
