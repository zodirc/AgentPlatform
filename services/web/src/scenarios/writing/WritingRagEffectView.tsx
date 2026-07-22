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
      <Card className="border-border bg-card/40">
        <CardTitle className="text-foreground/90">资料引用效果</CardTitle>
        <p className="mt-2 text-xs text-muted-foreground">{assessment.detail}</p>
      </Card>
    );
  }

  return (
    <Card
      className={
        assessment.status === "effective"
          ? "border-success/40 bg-success-muted"
          : assessment.status === "no_search" ||
              assessment.status === "no_hits" ||
              assessment.status === "no_cite"
            ? "border-warning/40 bg-warning-muted"
            : "border-border bg-card/40"
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <CardTitle className="text-foreground">资料引用效果</CardTitle>
        <Badge variant={STATUS_VARIANT[assessment.status]}>
          {assessment.title}
        </Badge>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{assessment.detail}</p>
      {assessment.cites.length > 0 ? (
        <p className="mt-2 text-xs text-success/90">
          引用：{assessment.cites.join(" · ")}
        </p>
      ) : null}
    </Card>
  );
}
