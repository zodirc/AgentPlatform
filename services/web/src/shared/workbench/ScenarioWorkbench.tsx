import { useEffect, useState } from "react";
import { ErrorBanner } from "./ErrorBanner";
import type { ScenarioId, TimelineItem, WorkbenchState } from "./types";
import { AgentActivityPanel } from "../../scenarios/agent/AgentActivityPanel";
import { AgentChatPanel } from "../../scenarios/agent/AgentChatPanel";
import { AstIndexStatusBar } from "../../scenarios/agent/AstIndexStatusBar";
import {
  AgentSidebar,
  type SidebarSelection,
} from "../../scenarios/agent/AgentSidebar";
import { AgentTimelinePanel } from "../../scenarios/agent/AgentTimelinePanel";
import {
  CollabTeamViewer,
} from "../../scenarios/collab/CollabTeamPanel";
import { WorkspaceFileViewer } from "../../scenarios/agent/WorkspaceFileViewer";
import { ScenarioSidebarExtras } from "../../scenarios/ScenarioSidebarExtras";
import { RagDebugModal } from "../../scenarios/writing/RagDebugModal";
import { SourcesLibraryModal } from "../../scenarios/writing/SourcesLibraryModal";
import { useAgentPanel } from "./agentPanel";

function artifactBadgeCount(
  timelineItems: { tool_name?: string; stream_output?: string }[],
  artifacts: Record<string, unknown>[],
): number {
  const previewableTools = timelineItems.filter(
    (item) =>
      item.tool_name === "read_file" ||
      item.tool_name === "write_file" ||
      item.tool_name === "edit_file" ||
      item.tool_name === "list_dir" ||
      item.tool_name === "glob" ||
      item.tool_name === "run_command" ||
      item.tool_name === "search_sources" ||
      item.tool_name === "search_codebase" ||
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

function toolStepCount(
  timelineItems: TimelineItem[],
  subagents: { tools: unknown[] }[],
): number {
  return (
    timelineItems.length +
    subagents.reduce((n, s) => n + s.tools.length, 0)
  );
}

type ViewProps = {
  scenarioId: ScenarioId;
  wb: WorkbenchState;
  fillParent?: boolean;
};

export function ScenarioWorkbenchView({
  scenarioId,
  wb,
  fillParent = false,
}: ViewProps) {
  const {
    open: toolsOpen,
    closePanel: closeTools,
    togglePanel: toggleTools,
  } = useAgentPanel();
  const [selection, setSelection] = useState<SidebarSelection | null>(null);
  const [artifactsOpen, setArtifactsOpen] = useState(scenarioId !== "agent");
  const [workspaceViewerPath, setWorkspaceViewerPath] = useState<string | null>(
    null,
  );
  const [sourcesLibraryOpen, setSourcesLibraryOpen] = useState(false);
  const [ragDebugOpen, setRagDebugOpen] = useState(false);
  const [openSubagentRequest, setOpenSubagentRequest] = useState<string | null>(
    null,
  );
  const [teamViewerOpen, setTeamViewerOpen] = useState(false);
  const isCollab = scenarioId === "collab";
  const artifactCount = artifactBadgeCount(
    wb.timelineItems,
    wb.view?.artifacts ?? [],
  );
  const toolsCount = toolStepCount(
    wb.timelineItems,
    isCollab ? [] : wb.subagents,
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

  const openSubagent = (id: string) => {
    setOpenSubagentRequest(id);
  };

  useEffect(() => {
    if (!toolsOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeTools();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toolsOpen, closeTools]);

  const rootClass = fillParent
    ? "relative flex h-full min-h-0 flex-col"
    : "relative flex h-[calc(100vh-49px)] flex-col";

  return (
    <div className={rootClass}>
      {wb.error ? (
        <div className="shrink-0 border-b border-border px-4 py-2">
          <ErrorBanner error={wb.error} onDismiss={wb.clearError} />
        </div>
      ) : null}
      {scenarioId === "agent" ? <AstIndexStatusBar /> : null}

      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        {artifactsOpen ? (
          <AgentSidebar
            wb={wb}
            selection={selection}
            scenarioExtras={
              <ScenarioSidebarExtras
                wb={wb}
                onOpenSources={
                  scenarioId === "writing"
                    ? () => setSourcesLibraryOpen(true)
                    : undefined
                }
                onOpenRagDebug={
                  scenarioId === "writing"
                    ? () => setRagDebugOpen(true)
                    : undefined
                }
                onOpenCollabTeam={
                  isCollab ? () => setTeamViewerOpen(true) : undefined
                }
              />
            }
            onOpenSourcesLibrary={
              scenarioId === "writing"
                ? () => setSourcesLibraryOpen(true)
                : undefined
            }
            onSelect={(sel) => {
              setSelection(sel);
              if (sel?.kind === "workspace") setArtifactsOpen(true);
            }}
            onOpenWorkspaceFile={(path) => {
              setWorkspaceViewerPath(path);
              setArtifactsOpen(true);
              setSelection({ kind: "workspace", path });
            }}
            onWorkspaceDeleted={(deletedPaths) => {
              if (
                workspaceViewerPath &&
                deletedPaths.some(
                  (deleted) =>
                    workspaceViewerPath === deleted ||
                    workspaceViewerPath.startsWith(`${deleted}/`),
                )
              ) {
                setWorkspaceViewerPath(null);
              }
              if (
                selection?.kind === "workspace" &&
                deletedPaths.some(
                  (deleted) =>
                    selection.path === deleted ||
                    selection.path.startsWith(`${deleted}/`),
                )
              ) {
                setSelection(null);
              }
            }}
            onClose={() => setArtifactsOpen(false)}
          />
        ) : (
          <div className="flex w-11 shrink-0 flex-col items-center border-r border-border bg-background py-3">
            <button
              type="button"
              className="group flex flex-col items-center gap-2 rounded-md px-1 py-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title="展开产物"
              onClick={openArtifacts}
            >
              <span className="text-[10px] font-medium tracking-wide text-muted-foreground group-hover:text-foreground">
                产物
              </span>
              <span className="text-xs leading-none text-muted-foreground group-hover:text-foreground/90">
                ›
              </span>
              {artifactCount > 0 ? (
                <span className="min-w-[1.125rem] rounded-full bg-primary/25 px-1 text-center text-[10px] font-medium text-primary">
                  {artifactCount > 99 ? "99+" : artifactCount}
                </span>
              ) : null}
            </button>
          </div>
        )}

        {/* Main stays full width; tools open as an overlay drawer. */}
        <main className="flex min-h-0 min-w-0 flex-1 flex-col gap-2.5 overflow-hidden p-3 sm:p-4">
          <AgentActivityPanel
            wb={wb}
            compact
            onOpenTools={toggleTools}
            toolsOpen={toolsOpen}
            toolsCount={toolsCount}
          />
          <div className="min-h-0 flex-1 overflow-hidden">
            <AgentChatPanel
              wb={wb}
              openSubagentRequest={openSubagentRequest}
              onOpenSubagentHandled={() => setOpenSubagentRequest(null)}
            />
          </div>
        </main>
      </div>

      {/* Bookmark-style tools drawer: overlays content, does not reflow layout. */}
      {toolsOpen ? (
        <div
          className="absolute inset-0 z-40 flex justify-end bg-overlay"
          onClick={closeTools}
          role="presentation"
        >
          <aside
            className="flex h-full w-[min(380px,92vw)] flex-col overflow-hidden border-l border-border bg-card shadow-2xl animate-in slide-in-from-right-4 fade-in duration-200"
            aria-label="工具时间线"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <AgentTimelinePanel
              title={isCollab ? "主编工具" : undefined}
              emptyHint={
                isCollab
                  ? "主编下场的工具会出现在这里；工人详情在左侧「团队 / 子任务」"
                  : undefined
              }
              items={wb.timelineItems}
              events={wb.events}
              subagents={isCollab ? [] : wb.subagents}
              selectedIndex={
                selection?.kind === "timeline" ? selection.index : null
              }
              onSelectItem={selectTimelineItem}
              onOpenSubagent={isCollab ? undefined : openSubagent}
              onClose={closeTools}
            />
          </aside>
        </div>
      ) : null}

      <WorkspaceFileViewer
        path={workspaceViewerPath}
        onClose={() => setWorkspaceViewerPath(null)}
      />
      <CollabTeamViewer
        open={teamViewerOpen}
        subagents={wb.subagents}
        onClose={() => setTeamViewerOpen(false)}
        onOpenSubagent={openSubagent}
      />
      {scenarioId === "writing" ? (
        <>
          <SourcesLibraryModal
            open={sourcesLibraryOpen}
            onClose={() => setSourcesLibraryOpen(false)}
            onOpenFile={(path) => {
              setWorkspaceViewerPath(path);
              setSourcesLibraryOpen(false);
            }}
          />
          <RagDebugModal
            open={ragDebugOpen}
            wb={wb}
            onClose={() => setRagDebugOpen(false)}
          />
        </>
      ) : null}
    </div>
  );
}
