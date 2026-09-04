import { Button } from "../../components/ui/button";
import { Card, CardTitle } from "../../components/ui/card";

type Props = {
  onOpenSources: () => void;
  onOpenRagDebug: () => void;
  onOpenSignals: () => void;
};

export function WritingSidebarTools({
  onOpenSources,
  onOpenRagDebug,
  onOpenSignals,
}: Props) {
  return (
    <Card className="border-primary/30 bg-primary/10">
      <CardTitle className="text-primary">写作工具</CardTitle>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-primary/40 text-primary"
          onClick={onOpenSignals}
        >
          写作信号
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-primary/40 text-primary"
          onClick={onOpenSources}
        >
          资料库
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-input text-foreground/90"
          onClick={onOpenRagDebug}
        >
          引用诊断
        </Button>
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/80">
        「写作信号」管经典/网文贴近强度。资料库只管引用材料。长会话可用 /compact。
      </p>
    </Card>
  );
}
