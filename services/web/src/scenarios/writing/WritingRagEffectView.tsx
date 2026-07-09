import { Badge } from "../../components/ui/badge";
import { Card, CardTitle } from "../../components/ui/card";
import type { WorkbenchState } from "../../shared/workbench/types";
import {
  assessWritingRagEffect,
  type RagEffectStatus,
} from "./writingRagEffect";

type Props = {
  wb: WorkbenchState;
};

const STATUS_VARIANT: Record<
  RagEffectStatus,
  "default" | "success" | "warning"
> = {
  idle: "default",
  running: "default",
  not_needed: "default",
  no_search: "warning",
  no_hits: "warning",
  no_cite: "warning",
  effective: "success",
};

export function WritingRagEffectView({ wb }: Props) {
  const assessment = assessWritingRagEffect({
    view: wb.view,
    streamText: wb.streamText,
    sectionDraft: wb.sectionDraft,
    userMessage: wb.submittedMessage,
    turnBusy: wb.busy,
  });

  if (assessment.status === "idle" && !wb.view && !wb.busy) {
    return (
      <Card className="border-slate-800 bg-slate-900/40">
        <CardTitle className="text-slate-300">资料引用效果</CardTitle>
        <p className="mt-2 text-xs text-slate-500">{assessment.detail}</p>
      </Card>
    );
  }

  return (
    <Card
      className={
        assessment.status === "effective"
          ? "border-emerald-900/50 bg-emerald-950/20"
          : assessment.status === "no_search" ||
              assessment.status === "no_hits" ||
              assessment.status === "no_cite"
            ? "border-amber-900/50 bg-amber-950/20"
            : "border-slate-800 bg-slate-900/40"
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <CardTitle className="text-slate-200">资料引用效果</CardTitle>
        <Badge variant={STATUS_VARIANT[assessment.status]}>
          {assessment.title}
        </Badge>
      </div>
      <p className="mt-2 text-xs text-slate-400">{assessment.detail}</p>
      {assessment.cites.length > 0 ? (
        <p className="mt-2 text-xs text-emerald-300/90">
          引用：{assessment.cites.join(" · ")}
        </p>
      ) : null}
    </Card>
  );
}
