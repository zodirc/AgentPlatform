import { useState } from "react";
import { Button } from "../../components/ui/button";
import { useAdminAuth } from "../../shared/auth/useAdminAuth";
import { ErrorBanner } from "../../shared/workbench/ErrorBanner";
import { useWorkbench } from "../../shared/workbench/useWorkbench";
import { AgentActivityPanel } from "./AgentActivityPanel";
import { AgentChatPanel } from "./AgentChatPanel";
import { AgentSidebar, type SidebarSelection } from "./AgentSidebar";
import { AgentTimelinePanel } from "./AgentTimelinePanel";

export function AgentWorkbench() {
  const wb = useWorkbench({ scenarioId: "agent", title: "Agent 工作台" });
  const [selection, setSelection] = useState<SidebarSelection | null>(null);
  const { needsUnlock, checking, unlockError, unlock } = useAdminAuth();
  const [adminPasswordInput, setAdminPasswordInput] = useState("");

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

      <div className="grid min-h-0 min-w-[960px] flex-1 grid-cols-[minmax(280px,320px)_minmax(0,1fr)_minmax(300px,380px)] overflow-x-auto">
        <AgentChatPanel wb={wb} />

        <main className="flex min-h-0 min-w-0 flex-col gap-3 overflow-hidden p-4">
          <AgentActivityPanel wb={wb} compact />
          <div className="min-h-0 flex-1 overflow-hidden">
            <AgentTimelinePanel
              items={wb.timelineItems}
              events={wb.events}
              selectedIndex={
                selection?.kind === "timeline" ? selection.index : null
              }
              onSelectItem={(item, index) =>
                setSelection(
                  selection?.kind === "timeline" && selection.index === index
                    ? null
                    : { kind: "timeline", item, index },
                )
              }
            />
          </div>
        </main>

        <AgentSidebar wb={wb} selection={selection} onSelect={setSelection} />
      </div>
    </div>
  );
}
