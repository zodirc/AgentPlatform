import type { ReactNode } from "react";
import { useState } from "react";
import {
  PatchDiffPanel,
  type PatchArtifact,
} from "../../components/PatchDiffPanel";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import { Button } from "../../components/ui/button";
import { Card, CardTitle } from "../../components/ui/card";
import { Textarea } from "../../components/ui/textarea";
import { useAdminAuth } from "../auth/useAdminAuth";
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
  const { needsUnlock, checking, unlockError, unlock } = useAdminAuth();
  const [adminPasswordInput, setAdminPasswordInput] = useState("");
  const pendingApprovalEvent = lastApprovalEvent(wb.events);
  const pendingArgs = pendingApprovalEvent?.payload.arguments as
    Record<string, unknown> | undefined;
  const approval = approvalCopy(wb.pendingToolName);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <header>
        <p className="text-xs uppercase tracking-wide text-sky-400">Phase 1</p>
        <h1 className="text-2xl font-semibold">{wb.title}</h1>
        <p className="text-sm text-slate-400">
          scenario_id={wb.scenarioId}
          {wb.useWebSocket ? " · transport=ws" : ""}
        </p>
      </header>

      <ErrorBanner error={wb.error} onDismiss={wb.clearError} />

      {needsUnlock && !checking && (
        <form
          className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-900/50 bg-amber-950/20 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!adminPasswordInput.trim()) return;
            void (async () => {
              const ok = await unlock(adminPasswordInput.trim());
              if (!ok) return;
              setAdminPasswordInput("");
              await wb.refreshView();
            })();
          }}
        >
          <span className="text-sm text-amber-200">
            需要 Admin 密码才能查看工具结果和批准敏感操作
          </span>
          {unlockError ? (
            <span className="text-sm text-rose-300">{unlockError}</span>
          ) : null}
          <input
            className="rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm"
            type="password"
            placeholder="admin 密码（默认 admin）"
            value={adminPasswordInput}
            onChange={(e) => setAdminPasswordInput(e.target.value)}
          />
          <Button type="submit" className="bg-amber-700">
            解锁
          </Button>
        </form>
      )}

      <div
        className={
          layout === "agent" ? "max-w-3xl" : "grid gap-4 lg:grid-cols-2"
        }
      >
        <Card className={layout === "agent" ? "" : undefined}>
          <label className="mb-2 block text-sm text-slate-300">消息</label>
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
              className="border-rose-700 text-rose-300"
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
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs">
              {wb.streamText ||
                wb.sectionDraft ||
                wb.view?.latest_output ||
                "（等待 Turn）"}
            </pre>
            {(wb.view || wb.busy || wb.awaitingApproval) && (
              <p className="mt-2 text-xs text-slate-500">
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
        <Card className="border-violet-800/60 bg-violet-950/30">
          <CardTitle className="text-violet-200">{approval.title}</CardTitle>
          <p className="mb-1 text-sm text-slate-300">{approval.description}</p>
          {wb.pendingWriteFile ? (
            <div className="mb-3">
              <WriteFileDiffPanel
                preview={wb.pendingWriteFile}
                mode="approval"
              />
            </div>
          ) : null}
          {wb.pendingToolName === "run_command" && pendingArgs?.command ? (
            <pre className="mb-3 max-h-40 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-amber-100">
              $ {String(pendingArgs.command)}
            </pre>
          ) : null}
          {wb.pendingToolCallId ? (
            <p className="mb-3 text-xs text-slate-400">
              工具：{wb.pendingToolName ?? "unknown"} · id=
              {wb.pendingToolCallId}
            </p>
          ) : (
            <p className="mb-3 text-xs text-amber-400">
              若未显示按钮，请先到顶部输入 Admin 密码解锁，然后刷新页面。
            </p>
          )}
          <div className="flex gap-2">
            <Button
              className="bg-emerald-700"
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
        <section className="space-y-3 rounded-xl border border-violet-900/50 bg-violet-950/20 p-4">
          <h2 className="text-sm font-medium text-violet-200">文件变更</h2>
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
          className="space-y-3 rounded-xl border border-amber-900/50 bg-amber-950/20 p-4"
          data-testid="patch-review"
        >
          <h2 className="text-sm font-medium text-amber-200">Patch 审阅</h2>
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

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="mb-2 text-sm font-medium text-slate-400">
          {layout === "agent" ? "调试事件流" : "事件流"}
        </h2>
        <pre
          className={`overflow-auto text-xs text-slate-500 ${layout === "agent" ? "max-h-24" : "max-h-40"}`}
        >
          {wb.events.map((e) => `${e.sequence}:${e.type}`).join(" → ") || "—"}
        </pre>
      </section>
    </div>
  );
}
