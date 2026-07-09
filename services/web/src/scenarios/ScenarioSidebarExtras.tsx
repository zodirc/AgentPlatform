import type { ReactNode } from "react";
import { Card, CardTitle } from "../components/ui/card";
import type { WorkbenchState } from "../shared/workbench/types";
import { CitationView } from "./writing/CitationView";
import { DocumentOutlineView } from "./writing/DocumentOutlineView";
import { WritingSidebarTools } from "./writing/WritingSidebarTools";

type Props = {
  wb: WorkbenchState;
  onOpenSources?: () => void;
  onOpenRagDebug?: () => void;
};

function InterviewPlan({ wb }: Props) {
  const view = wb.view;
  const plan = view?.artifacts?.find((a) => a.type === "plan") as
    | { items?: Array<{ id: string; title: string; status: string }> }
    | undefined;
  if (!plan?.items?.length) return null;
  return (
    <Card className="border-emerald-900/50 bg-emerald-950/20">
      <CardTitle className="text-emerald-200">访谈待办</CardTitle>
      <ul className="mt-2 space-y-1 text-xs">
        {plan.items.map((item) => (
          <li key={item.id} className="rounded bg-slate-950 px-3 py-2">
            <span className="text-slate-400">{item.status}</span> — {item.title}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function DocumentOutline({ wb }: Props) {
  const outline = wb.view?.artifacts?.find((a) => a.type === "outline") as
    { content?: string } | undefined;
  if (!outline) return null;
  return (
    <Card className="border-sky-900/50 bg-sky-950/20">
      <CardTitle className="text-sky-200">文档大纲</CardTitle>
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

  if (id === "writing") {
    return (
      <div className="space-y-3">
        {onOpenSources && onOpenRagDebug ? (
          <WritingSidebarTools
            onOpenSources={onOpenSources}
            onOpenRagDebug={onOpenRagDebug}
          />
        ) : null}
        <CitationView items={wb.view?.tool_timeline ?? []} />
        <DocumentOutline wb={wb} />
      </div>
    );
  }

  if (id === "interview") {
    return (
      <div className="space-y-3">
        <CitationView items={wb.view?.tool_timeline ?? []} />
        <DocumentOutline wb={wb} />
        <InterviewPlan wb={wb} />
      </div>
    );
  }

  return null;
}
