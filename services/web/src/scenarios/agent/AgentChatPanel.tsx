import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import {
  approvalCopy,
  lastApprovalEvent,
} from "../../shared/workbench/toolApproval";
import { onChatEnterSend } from "../../shared/workbench/chatKeyboard";
import { placeholderForScenario } from "../../shared/workbench/useWorkbench";
import type { WorkbenchState } from "../../shared/workbench/types";

type Props = {
  wb: WorkbenchState;
};

export function AgentChatPanel({ wb }: Props) {
  const pendingApprovalEvent = lastApprovalEvent(wb.events);
  const pendingArgs = pendingApprovalEvent?.payload.arguments as
    Record<string, unknown> | undefined;
  const approval = approvalCopy(wb.pendingToolName);
  const output = wb.streamText || wb.view?.latest_output || "";

  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-slate-800 bg-slate-950">
      <header className="shrink-0 border-b border-slate-800 px-4 py-3">
        <p className="text-xs uppercase tracking-wide text-sky-400">Agent</p>
        <h1 className="text-sm font-semibold text-slate-100">{wb.title}</h1>
        <p className="text-xs text-slate-500">
          scenario_id={wb.scenarioId}
          {wb.useWebSocket ? " · ws" : ""}
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {wb.submittedMessage && (wb.busy || wb.view) ? (
          <div className="mb-4">
            <p className="mb-1 text-xs font-medium text-slate-500">你</p>
            <p className="rounded-lg bg-slate-900 px-3 py-2 text-sm text-slate-200">
              {wb.submittedMessage}
            </p>
          </div>
        ) : null}
        {output ? (
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">助手</p>
            <pre className="whitespace-pre-wrap rounded-lg bg-slate-900/60 px-3 py-2 text-xs text-slate-300">
              {output}
            </pre>
          </div>
        ) : (
          <p className="text-xs text-slate-600">发送消息开始任务…</p>
        )}
        {(wb.view || wb.busy) && (
          <p className="mt-3 text-xs text-slate-600">
            status={wb.displayStatus}
            {wb.view ? ` · seq=${wb.view.last_event_sequence}` : ""}
            {wb.turnId ? ` · turn=${wb.turnId.slice(0, 8)}` : ""}
          </p>
        )}
      </div>

      {wb.awaitingApproval ? (
        <div className="shrink-0 border-t border-violet-900/50 bg-violet-950/30 p-4">
          <p className="text-sm font-medium text-violet-200">
            {approval.title}
          </p>
          <p className="mb-2 text-xs text-slate-400">{approval.description}</p>
          {wb.pendingWriteFile ? (
            <div className="mb-2">
              <WriteFileDiffPanel
                preview={wb.pendingWriteFile}
                mode="approval"
              />
            </div>
          ) : null}
          {wb.pendingToolName === "run_command" && pendingArgs?.command ? (
            <pre className="mb-2 max-h-32 overflow-auto rounded bg-slate-950 p-2 text-xs text-amber-100">
              $ {String(pendingArgs.command)}
            </pre>
          ) : null}
          <div className="flex gap-2">
            <Button
              size="sm"
              className="bg-emerald-700"
              disabled={wb.actionBusy || !wb.pendingToolCallId}
              onClick={() => void wb.handleApprove()}
            >
              {approval.approveLabel}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={wb.actionBusy || !wb.pendingToolCallId}
              onClick={() => void wb.handleDeny()}
            >
              拒绝
            </Button>
          </div>
        </div>
      ) : null}

      <div className="shrink-0 border-t border-slate-800 p-4">
        <Textarea
          className="min-h-[80px] resize-none text-sm"
          value={wb.message}
          onChange={(e) => wb.setMessage(e.target.value)}
          placeholder={placeholderForScenario(wb.scenarioId)}
          onKeyDown={(e) =>
            onChatEnterSend(
              e,
              () => void wb.handleSend(),
              !wb.busy && Boolean(wb.message.trim()),
            )
          }
        />
        <div className="mt-2 flex gap-2">
          <Button
            size="sm"
            disabled={wb.busy || !wb.message.trim()}
            onClick={() => void wb.handleSend()}
          >
            发送
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-rose-700 text-rose-300"
            disabled={!wb.busy || wb.stopping}
            onClick={() => void wb.handleStop()}
          >
            {wb.stopping ? "停止中…" : "Stop"}
          </Button>
        </div>
      </div>
    </aside>
  );
}
