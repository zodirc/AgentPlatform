import { CitationView } from "./CitationView";
import { DocumentOutlineView } from "./DocumentOutlineView";
import { Card, CardTitle } from "../../components/ui/card";
import type { WorkbenchState } from "../../shared/workbench/types";

type Props = {
  wb: WorkbenchState;
};

export function WritingPanels({ wb }: Props) {
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
    </>
  );
}
