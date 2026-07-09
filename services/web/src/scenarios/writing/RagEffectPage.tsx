import { Card, CardTitle } from "../../components/ui/card";
import type { WorkbenchState } from "../../shared/workbench/types";
import { RetrievalView } from "../agent/RetrievalView";
import { CitationView } from "./CitationView";
import { WritingRagEffectView } from "./WritingRagEffectView";

type Props = {
  wb: WorkbenchState;
  embedded?: boolean;
};

export function RagEffectPage({ wb, embedded = false }: Props) {
  const view = wb.view;

  return (
    <div
      className={
        embedded
          ? "space-y-4 p-4"
          : "mx-auto max-w-3xl space-y-4 p-6"
      }
    >
      {!embedded ? (
        <header>
          <h1 className="text-xl font-semibold text-slate-100">资料引用诊断</h1>
          <p className="mt-1 text-sm text-slate-400">
            调试 RAG 链路：用户意图 → search_sources → 命中 → 成稿
            [cite:xxx]。与工作台共享同一会话，可在写作时切换查看。
          </p>
        </header>
      ) : null}

      <WritingRagEffectView wb={wb} />

      <RetrievalView artifacts={view?.artifacts ?? []} />
      <CitationView items={view?.tool_timeline ?? []} />

      <Card className="border-slate-800 bg-slate-900/40">
        <CardTitle className="text-slate-300">本轮上下文</CardTitle>
        <dl className="mt-3 space-y-2 text-xs text-slate-400">
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-slate-500">Turn 状态</dt>
            <dd>{wb.displayStatus}</dd>
          </div>
          {wb.turnId ? (
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-slate-500">Turn ID</dt>
              <dd className="font-mono text-slate-300">{wb.turnId}</dd>
            </div>
          ) : null}
          {wb.submittedMessage ? (
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-slate-500">用户消息</dt>
              <dd className="text-slate-300">{wb.submittedMessage}</dd>
            </div>
          ) : null}
        </dl>
        {wb.events.length > 0 ? (
          <pre className="mt-3 max-h-32 overflow-auto rounded-lg bg-slate-950 p-3 text-[10px] text-slate-500">
            {wb.events.map((e) => `${e.sequence}:${e.type}`).join(" → ")}
          </pre>
        ) : (
          <p className="mt-3 text-xs text-slate-600">
            暂无 Turn 事件。请在工作台发送一条需要引用的消息。
          </p>
        )}
      </Card>
    </div>
  );
}
