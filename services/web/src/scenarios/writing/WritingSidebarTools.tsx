import { Button } from "../../components/ui/button";
import { Card, CardTitle } from "../../components/ui/card";

type Props = {
  onOpenSources: () => void;
  onOpenRagDebug: () => void;
};

export function WritingSidebarTools({ onOpenSources, onOpenRagDebug }: Props) {
  return (
    <Card className="border-violet-900/50 bg-violet-950/20">
      <CardTitle className="text-violet-200">写作工具</CardTitle>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-violet-800 text-violet-200"
          onClick={onOpenSources}
        >
          资料库
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-slate-700 text-slate-300"
          onClick={onOpenRagDebug}
        >
          引用诊断
        </Button>
      </div>
      <p className="mt-2 text-[10px] text-slate-600">
        资料库支持粘贴输入或上传文件；双击可查看。工作区 sources/ 同理。
      </p>
    </Card>
  );
}
