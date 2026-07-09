import { CitationView } from "../writing/CitationView";
import { DocumentOutlineView } from "../writing/DocumentOutlineView";
import { Card, CardTitle } from "../../components/ui/card";
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
      {view?.artifacts?.some((a) => a.type === "plan") && (
        <section className="rounded-xl border border-emerald-900/50 bg-emerald-950/20 p-4">
          <h2 className="mb-2 text-sm font-medium text-emerald-200">
            访谈待办
          </h2>
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
