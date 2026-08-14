import { AstIndexSettingsCard } from "./AstIndexSettingsCard";
import { AstIndexTreeCard } from "./AstIndexTreeCard";
import { CorpusChunksCard } from "./CorpusChunksCard";

export function IndexInspectSection() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">索引查看</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          只读查看当前默认 Work 的 RAG 切块正文，以及 Agent 工作区 AST
          符号树。不进入 Turn 热路径。
        </p>
      </div>
      <CorpusChunksCard />
      <AstIndexSettingsCard />
      <AstIndexTreeCard />
    </div>
  );
}
