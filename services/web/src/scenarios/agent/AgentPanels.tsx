import { RetrievalView } from "./RetrievalView";
import { ArtifactView } from "./ArtifactView";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import { artifactToWritePreview } from "../../shared/workbench/filePreview";
import { PlanPanel } from "../../shared/workbench/PlanPanel";
import type { WorkbenchState } from "../../shared/workbench/types";

type Props = {
  wb: WorkbenchState;
};

export function AgentPanels({ wb }: Props) {
  const view = wb.view;
  const errorArtifact = (view?.artifacts ?? []).find(
    (a) => a.type === "error",
  ) as { message?: string; termination_reason?: string } | undefined;
  const fileWrites = (view?.artifacts ?? [])
    .filter((a) => a.type === "file_write" && typeof a.path === "string")
    .filter((a) => String(a.status ?? "") === "applied");

  return (
    <>
      {errorArtifact?.message ? (
        <section className="rounded-xl border border-rose-800/60 bg-rose-950/30 p-4">
          <h2 className="mb-1 text-sm font-medium text-rose-200">失败原因</h2>
          <p className="text-sm text-rose-100">
            {String(errorArtifact.message)}
          </p>
          {errorArtifact.termination_reason ? (
            <p className="mt-1 text-xs text-rose-300/80">
              reason={String(errorArtifact.termination_reason)}
            </p>
          ) : null}
        </section>
      ) : null}
      {fileWrites.length > 0 ? (
        <section className="space-y-3 rounded-xl border border-violet-900/50 bg-violet-950/20 p-4">
          <h2 className="text-sm font-medium text-violet-200">文件变更</h2>
          {fileWrites.map((item, idx) => (
            <WriteFileDiffPanel
              key={String(item.tool_call_id ?? item.path ?? idx)}
              preview={artifactToWritePreview(item)}
            />
          ))}
        </section>
      ) : null}
      <PlanPanel
        plan={wb.plan}
        turnStatus={wb.displayStatus}
        planPhase={wb.planPhase}
        showExecute={wb.canExecutePlan}
        executeDisabled={wb.busy || wb.actionBusy}
        onExecute={() => void wb.handleExecutePlan()}
      />
      <RetrievalView artifacts={view?.artifacts ?? []} />
      <ArtifactView artifacts={view?.artifacts ?? []} />
    </>
  );
}
