import { useState } from "react";
import { Button } from "../../components/ui/button";
import { ErrorBanner } from "./ErrorBanner";
import type { ScenarioId, TimelineItem, WorkbenchState } from "./types";
import { AgentActivityPanel } from "../../scenarios/agent/AgentActivityPanel";
import { AgentChatPanel } from "../../scenarios/agent/AgentChatPanel";
import {
  AgentSidebar,
  type SidebarSelection,
} from "../../scenarios/agent/AgentSidebar";
import { AgentTimelinePanel } from "../../scenarios/agent/AgentTimelinePanel";
import { WorkspaceFileViewer } from "../../scenarios/agent/WorkspaceFileViewer";
import { ScenarioSidebarExtras } from "../../scenarios/ScenarioSidebarExtras";
import { RagDebugModal } from "../../scenarios/writing/RagDebugModal";
import { SourcesLibraryModal } from "../../scenarios/writing/SourcesLibraryModal";

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
  const [selection, setSelection] = useState<SidebarSelection | null>(null);
  const [artifactsOpen, setArtifactsOpen] = useState(scenarioId !== "agent");
  const [workspaceViewerPath, setWorkspaceViewerPath] = useState<string | null>(
    null,
  );
  const [sourcesLibraryOpen, setSourcesLibraryOpen] = useState(false);
  const [ragDebugOpen, setRagDebugOpen] = useState(false);
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

  const rootClass = fillParent
    ? "flex h-full min-h-0 flex-col"
    : "flex h-[calc(100vh-49px)] flex-col";

  return (
    <div className={rootClass}>
      <div className="shrink-0 space-y-2 border-b border-border px-4 py-2">
        <ErrorBanner error={wb.error} onDismiss={wb.clearError} />
      </div>

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

        <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(300px,380px)] overflow-x-auto">
          <main className="flex min-h-0 min-w-0 flex-col gap-3 overflow-hidden border-r border-border p-4">
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

      <WorkspaceFileViewer
        path={workspaceViewerPath}
        onClose={() => setWorkspaceViewerPath(null)}
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
