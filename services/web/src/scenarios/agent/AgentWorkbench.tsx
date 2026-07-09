import { useState } from "react";
import { Button } from "../../components/ui/button";
import { useAdminAuth } from "../../shared/auth/useAdminAuth";
import { ErrorBanner } from "../../shared/workbench/ErrorBanner";
import { useWorkbench } from "../../shared/workbench/useWorkbench";
import type { TimelineItem } from "../../shared/workbench/types";
import { AgentActivityPanel } from "./AgentActivityPanel";
import { AgentChatPanel } from "./AgentChatPanel";
import { AgentSidebar, type SidebarSelection } from "./AgentSidebar";
import { AgentTimelinePanel } from "./AgentTimelinePanel";

function artifactBadgeCount(
  timelineItems: { tool_name?: string; stream_output?: string }[],
  artifacts: Record<string, unknown>[],
): number {
  const previewableTools = timelineItems.filter(
    (item) =>
      item.tool_name === "read_file" ||
      item.tool_name === "write_file" ||
      item.tool_name === "list_dir" ||
      item.tool_name === "glob" ||
      item.tool_name === "run_command" ||
      Boolean(item.stream_output),
  ).length;
  const fileWrites = artifacts.filter(
    (a) => a.type === "file_write" && typeof a.path === "string",
  ).length;
  const patches = artifacts.filter(
    (a) => typeof a.patch_id === "string",
  ).length;
  return previewableTools + fileWrites + patches;
}

export function AgentWorkbench() {
  const wb = useWorkbench({ scenarioId: "agent", title: "Agent 工作台" });
  const [selection, setSelection] = useState<SidebarSelection | null>(null);
  const [artifactsOpen, setArtifactsOpen] = useState(false);
  const { needsUnlock, checking, unlockError, unlock } = useAdminAuth();
  const [adminPasswordInput, setAdminPasswordInput] = useState("");
  const artifactCount = artifactBadgeCount(
    wb.timelineItems,
    wb.view?.artifacts ?? [],
  );

  const openArtifacts = () => setArtifactsOpen(true);

  const selectTimelineItem = (item: TimelineItem, index: number) => {
    const next =
      selection?.kind === "timeline" && selection.index === index
        ? null
        : ({ kind: "timeline", item, index } as const);
    setSelection(next);
    if (next) setArtifactsOpen(true);
  };

  return (
    <div className="flex h-[calc(100vh-49px)] flex-col">
      <div className="shrink-0 space-y-2 border-b border-slate-800 px-4 py-2">
        <ErrorBanner error={wb.error} onDismiss={wb.clearError} />
        {needsUnlock && !checking ? (
          <form
            className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-900/50 bg-amber-950/20 px-3 py-2"
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
            <span className="text-xs text-amber-200">
              需要 Admin 密码查看工具结果和批准敏感操作
            </span>
            {unlockError ? (
              <span className="text-xs text-rose-300">{unlockError}</span>
            ) : null}
            <input
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
              type="password"
              placeholder="admin 密码"
              value={adminPasswordInput}
              onChange={(e) => setAdminPasswordInput(e.target.value)}
            />
            <Button type="submit" size="sm" className="bg-amber-700">
              解锁
            </Button>
          </form>
        ) : null}
      </div>

      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        {artifactsOpen ? (
          <AgentSidebar
            wb={wb}
            selection={selection}
            onSelect={setSelection}
            onClose={() => setArtifactsOpen(false)}
          />
        ) : (
          <div className="flex w-11 shrink-0 flex-col items-center border-r border-slate-800 bg-slate-950 py-3">
            <button
              type="button"
              className="group flex flex-col items-center gap-2 rounded-md px-1 py-2 text-slate-500 transition-colors hover:bg-slate-900 hover:text-slate-200"
              title="展开产物"
              onClick={openArtifacts}
            >
              <span className="text-[10px] font-medium tracking-wide text-slate-400 group-hover:text-slate-200">
                产物
              </span>
              <span className="text-xs leading-none text-slate-500 group-hover:text-slate-300">
                ›
              </span>
              {artifactCount > 0 ? (
                <span className="min-w-[1.125rem] rounded-full bg-sky-900/60 px-1 text-center text-[10px] font-medium text-sky-200">
                  {artifactCount > 99 ? "99+" : artifactCount}
                </span>
              ) : null}
            </button>
          </div>
        )}

        <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(300px,380px)] overflow-x-auto">
          <main className="flex min-h-0 min-w-0 flex-col gap-3 overflow-hidden border-r border-slate-800 p-4">
            <AgentActivityPanel wb={wb} compact />
            <div className="min-h-0 flex-1 overflow-hidden">
              <AgentTimelinePanel
                items={wb.timelineItems}
                events={wb.events}
                selectedIndex={
                  selection?.kind === "timeline" ? selection.index : null
                }
                onSelectItem={selectTimelineItem}
              />
            </div>
          </main>

          <AgentChatPanel wb={wb} />
        </div>
      </div>
    </div>
  );
}
