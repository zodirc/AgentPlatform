import type { ReactNode } from "react";
import {
  PatchDiffPanel,
  type PatchArtifact,
} from "../../components/PatchDiffPanel";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import { Button } from "../../components/ui/button";
import { Card, CardTitle } from "../../components/ui/card";
import { Textarea } from "../../components/ui/textarea";
import { artifactToWritePreview } from "./filePreview";
import { approvalCopy, lastApprovalEvent } from "./toolApproval";
import { ErrorBanner } from "./ErrorBanner";
import { onChatEnterSend } from "./chatKeyboard";
import { placeholderForScenario } from "./useWorkbench";
import type { WorkbenchState } from "./types";

type Props = {
  wb: WorkbenchState;
  children?: ReactNode;
  layout?: "default" | "agent";
};

function isPatchArtifact(a: Record<string, unknown>): a is PatchArtifact {
  return typeof a.patch_id === "string" && typeof a.old_text === "string";
}

function isFileWriteArtifact(a: Record<string, unknown>): boolean {
  return a.type === "file_write" && typeof a.path === "string";
}

export function WorkbenchShell({ wb, children, layout = "default" }: Props) {
  const patches = (wb.view?.artifacts ?? []).filter(
    isPatchArtifact,
  ) as unknown as PatchArtifact[];
  const fileWrites = (wb.view?.artifacts ?? [])
    .filter(isFileWriteArtifact)
    .filter((a) => String(a.status ?? "") === "applied");
  const pendingApprovalEvent = lastApprovalEvent(wb.events);
  const pendingArgs = pendingApprovalEvent?.payload.arguments as
    Record<string, unknown> | undefined;
  const approval = approvalCopy(wb.pendingToolName);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <header>
        <p className="text-xs uppercase tracking-wide text-primary">Phase 1</p>
        <h1 className="text-2xl font-semibold">{wb.title}</h1>
        <p className="text-sm text-muted-foreground">
          scenario_id={wb.scenarioId}
          {wb.useWebSocket ? " · transport=ws" : ""}
        </p>
      </header>

      <ErrorBanner error={wb.error} onDismiss={wb.clearError} />

      <div
        className={
          layout === "agent" ? "max-w-3xl" : "grid gap-4 lg:grid-cols-2"
        }
      >
        <Card className={layout === "agent" ? "" : undefined}>
          <label className="mb-2 block text-sm text-foreground/90">消息</label>
          <Textarea
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
          <div className="mt-3 flex gap-2">
            <Button
              disabled={wb.busy || !wb.message.trim()}
              onClick={() => void wb.handleSend()}
            >
              发送
            </Button>
            <Button
              variant="outline"
              disabled={wb.busy}
              onClick={() => void wb.handleVerify()}
              title="事实核查（不修改草稿）"
            >
              事实核查
            </Button>
            <Button
              variant="outline"
              className="border-destructive/50 text-destructive"
              disabled={!wb.busy || wb.stopping}
              onClick={() => void wb.handleStop()}
            >
              {wb.stopping ? "正在停止…" : "Stop"}
            </Button>
          </div>
        </Card>

        {layout === "default" ? (
          <Card>
            <CardTitle>输出</CardTitle>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-background p-3 text-xs">
              {wb.streamText ||
                wb.sectionDraft ||
                wb.view?.latest_output ||
                "（等待 Turn）"}
            </pre>
            {(wb.view || wb.busy || wb.awaitingApproval) && (
              <p className="mt-2 text-xs text-muted-foreground">
                status={wb.displayStatus}
                {wb.view ? ` · seq=${wb.view.last_event_sequence}` : ""}
                {wb.view?.runner_id ? ` · runner=${wb.view.runner_id}` : ""}
                {wb.turnId ? ` · turn=${wb.turnId.slice(0, 8)}` : ""}
              </p>
            )}
          </Card>
        ) : null}
      </div>

      {wb.awaitingApproval && (
        <Card className="border-primary/40 bg-primary/10">
          <CardTitle className="text-primary">{approval.title}</CardTitle>
          <p className="mb-1 text-sm text-foreground/90">{approval.description}</p>
          {wb.pendingWriteFile ? (
            <div className="mb-3">
              <WriteFileDiffPanel
                preview={wb.pendingWriteFile}
                mode="approval"
              />
            </div>
          ) : null}
          {wb.pendingToolName === "run_command" && pendingArgs?.command ? (
            <pre className="mb-3 max-h-40 overflow-auto rounded-lg bg-background p-3 text-xs text-warning">
              $ {String(pendingArgs.command)}
            </pre>
          ) : null}
          {wb.pendingToolCallId ? (
            <p className="mb-3 text-xs text-muted-foreground">
              工具：{wb.pendingToolName ?? "unknown"} · id=
              {wb.pendingToolCallId}
            </p>
          ) : (
            <p className="mb-3 text-xs text-warning">
              等待审批控件就绪，可稍后刷新当前轮次。
            </p>
          )}
          <div className="flex gap-2">
            <Button
              className="bg-success text-success-foreground hover:bg-success/90"
              disabled={wb.actionBusy || !wb.pendingToolCallId}
              onClick={() => void wb.handleApprove()}
            >
              {approval.approveLabel}
            </Button>
            <Button
              variant="outline"
              disabled={wb.actionBusy || !wb.pendingToolCallId}
              onClick={() => void wb.handleDeny()}
            >
              拒绝
            </Button>
          </div>
        </Card>
      )}

      {children}

      {layout !== "agent" && fileWrites.length > 0 && (
        <section className="space-y-3 rounded-xl border border-primary/30 bg-primary/10 p-4">
          <h2 className="text-sm font-medium text-primary">文件变更</h2>
          {fileWrites.map((item, idx) => (
            <WriteFileDiffPanel
              key={String(item.tool_call_id ?? item.path ?? idx)}
              preview={artifactToWritePreview(item)}
            />
          ))}
        </section>
      )}

      {patches.length > 0 && (
        <section
          className="space-y-3 rounded-xl border border-warning/40 bg-warning-muted p-4"
          data-testid="patch-review"
        >
          <h2 className="text-sm font-medium text-warning">Patch 审阅</h2>
          {patches.map((patch) => (
            <PatchDiffPanel
              key={patch.patch_id}
              patch={patch}
              busy={wb.actionBusy}
              onAccept={(id) => void wb.handleAcceptPatch(id)}
              onReject={(id) => void wb.handleRejectPatch(id)}
            />
          ))}
        </section>
      )}

      <section className="rounded-xl border border-border bg-card/40 p-4">
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">
          {layout === "agent" ? "调试事件流" : "事件流"}
        </h2>
        <pre
          className={`overflow-auto text-xs text-muted-foreground ${layout === "agent" ? "max-h-24" : "max-h-40"}`}
        >
          {wb.events.map((e) => `${e.sequence}:${e.type}`).join(" → ") || "—"}
        </pre>
      </section>
    </div>
  );
}
