import { RetrievalView } from "./RetrievalView";
import { ArtifactView } from "./ArtifactView";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import { artifactToWritePreview } from "../../shared/workbench/filePreview";
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
      <RetrievalView artifacts={view?.artifacts ?? []} />
      <ArtifactView artifacts={view?.artifacts ?? []} />
      {view?.artifacts?.some((a) => a.type === "plan") && (
        <section className="rounded-xl border border-violet-900/50 bg-violet-950/20 p-4">
          <h2 className="mb-2 text-sm font-medium text-violet-200">任务计划</h2>
          <ul className="space-y-1 text-xs">
            {(
              (
                view.artifacts.find((a) => a.type === "plan") as {
                  items?: Array<{
                    id: string;
                    title: string;
                    status: string;
                  }>;
                }
              )?.items ?? []
            ).map((item) => (
              <li key={item.id} className="rounded bg-slate-950 px-3 py-2">
                <span className="text-slate-400">{item.status}</span> —{" "}
                {item.title}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
