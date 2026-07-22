import { Button } from "../../components/ui/button";
import { Card, CardTitle } from "../../components/ui/card";

type Props = {
  onOpenSources: () => void;
  onOpenRagDebug: () => void;
};

export function WritingSidebarTools({ onOpenSources, onOpenRagDebug }: Props) {
  return (
    <Card className="border-primary/30 bg-primary/10">
      <CardTitle className="text-primary">写作工具</CardTitle>
      <div className="mt-2 flex flex-wrap gap-2">
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
        书稿默认追加到 manuscript.md。长会话可用 /compact
        压缩对话（不丢书）；写下一章不必整本重读。大纲一轮、分章推进更省用量。
      </p>
    </Card>
  );
}
