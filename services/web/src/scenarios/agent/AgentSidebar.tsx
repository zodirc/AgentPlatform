import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2 } from "lucide-react";
import type { TurnEvent } from "../../shared/api/client";
import { deleteWorkspacePaths } from "../../shared/api/client";
import { isSeedCorpusPath } from "../../shared/workspace/seedPath";
import {
  PatchDiffPanel,
  type PatchArtifact,
} from "../../components/PatchDiffPanel";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import { artifactToWritePreview } from "../../shared/workbench/filePreview";
import type {
  TimelineItem,
  WorkbenchState,
} from "../../shared/workbench/types";
import { ArtifactView } from "./ArtifactView";
import { RetrievalView } from "./RetrievalView";
import { WritingCardsView } from "../writing/WritingCardsView";
import { WorkspaceTree } from "./WorkspaceTree";

export type SidebarSelection =
  | { kind: "timeline"; item: TimelineItem; index: number }
  | { kind: "file_write"; path: string }
  | { kind: "patch"; patchId: string }
  | { kind: "workspace"; path: string };

type Props = {
  wb: WorkbenchState;
  selection: SidebarSelection | null;
  scenarioExtras?: ReactNode;
  onSelect: (sel: SidebarSelection | null) => void;
  onOpenWorkspaceFile: (path: string) => void;
  onOpenSourcesLibrary?: () => void;
  onWorkspaceDeleted?: (deletedPaths: string[]) => void;
  onClose?: () => void;
};

function isPatchArtifact(a: Record<string, unknown>): a is PatchArtifact {
  return typeof a.patch_id === "string" && typeof a.old_text === "string";
}

function toolLabel(item: TimelineItem, events: TurnEvent[]): string {
  const name = String(item.tool_name ?? "tool");
  const path = timelinePath(item, events);
  if (path) return `${name}(${path})`;
  const summary = item.summary ?? "";
  if (summary.startsWith("Wrote ")) return `${name} → ${summary.slice(6)}`;
  return name;
}

function timelinePath(item: TimelineItem, events: TurnEvent[]): string | null {
  const toolCallId = String(item.tool_call_id ?? "");
  if (toolCallId) {
    const started = events.find(
      (e) =>
        e.type === "tool.started" &&
        String(e.payload.tool_call_id ?? "") === toolCallId,
    );
    const args = started?.payload.arguments as
      Record<string, unknown> | undefined;
    if (typeof args?.path === "string") return args.path;
    if (typeof args?.pattern === "string") return args.pattern;
    if (typeof args?.query === "string") return args.query.slice(0, 48);
    if (typeof args?.command === "string") return args.command.slice(0, 40);
  }
  const summary = item.summary ?? "";
  const pathMatch = summary.match(/"path":\s*"([^"]+)"/);
  if (pathMatch) return pathMatch[1];
  if (summary.startsWith("Wrote ")) return summary.slice(6).trim();
  return null;
}

function previewFromTimeline(item: TimelineItem): string {
  if (item.stream_output) return item.stream_output;
  const summary = item.summary ?? "";
  if (summary.startsWith("{")) {
    try {
      return JSON.stringify(JSON.parse(summary), null, 2);
    } catch {
      return summary;
    }
  }
  return summary;
}

export function AgentSidebar({
  wb,
  selection,
  scenarioExtras,
  onSelect,
  onOpenWorkspaceFile,
  onOpenSourcesLibrary,
  onWorkspaceDeleted,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  const [workspaceRefreshing, setWorkspaceRefreshing] = useState(false);
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [checkedPaths, setCheckedPaths] = useState<Set<string>>(() => new Set());
  const view = wb.view;
  const artifacts = view?.artifacts ?? [];

  const refreshWorkspace = async () => {
    setWorkspaceRefreshing(true);
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workspace-entries"] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-file-viewer"] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-sources"] }),
      ]);
    } finally {
      setWorkspaceRefreshing(false);
    }
  };

  const deleteSelected = useMutation({
    mutationFn: (paths: string[]) => deleteWorkspacePaths(paths),
    onSuccess: (result) => {
      void refreshWorkspace();
      setCheckedPaths(new Set());
      setMultiSelectMode(false);
      if (result.deleted.length > 0) {
        onWorkspaceDeleted?.(result.deleted);
      }
      if (result.failed.length > 0) {
        const detail = result.failed
          .map((row) => `${row.path}: ${row.error}`)
          .join("\n");
        window.alert(`部分删除失败：\n${detail}`);
      }
    },
    onError: (error: Error) => {
      window.alert(`删除失败：${error.message}`);
    },
  });

  const toggleCheckedPath = (path: string) => {
    setCheckedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const confirmDeleteSelected = () => {
    const paths = [...checkedPaths].filter((p) => !isSeedCorpusPath(p));
    if (paths.length === 0) {
      window.alert("系统资料（seed）不可删除。请只选择个人文件。");
      return;
    }
    const preview =
      paths.length <= 5
        ? paths.join("\n")
        : `${paths.slice(0, 5).join("\n")}\n…等 ${paths.length} 项`;
    const ok = window.confirm(
      `确定删除以下 ${paths.length} 项？\n\n${preview}\n\n此操作不可恢复。`,
    );
    if (!ok) return;
    deleteSelected.mutate(paths);
  };

  const patches = artifacts.filter(
    isPatchArtifact,
  ) as unknown as PatchArtifact[];
  const fileWrites = artifacts
    .filter((a) => a.type === "file_write" && typeof a.path === "string")
    .filter((a) => String(a.status ?? "") === "applied");

  const previewableTimeline = useMemo(
    () =>
      wb.timelineItems.filter(
        (item) =>
          item.tool_name === "read_file" ||
          item.tool_name === "write_file" ||
          item.tool_name === "list_dir" ||
          item.tool_name === "glob" ||
          item.tool_name === "run_command" ||
          item.tool_name === "search_sources" ||
          item.tool_name === "search_codebase" ||
          Boolean(item.stream_output),
      ),
    [wb.timelineItems],
  );

  const workspacePath = selection?.kind === "workspace" ? selection.path : null;
  const [workspaceSelectPath, setWorkspaceSelectPath] = useState<string | null>(
    null,
  );
  const treeSelectedPath = workspacePath ?? workspaceSelectPath;

  const selectedPreview = useMemo(() => {
    if (!selection) return null;
    if (selection.kind === "workspace") {
      return null;
    }
    if (selection.kind === "timeline") {
      const item = selection.item;
      return {
        title: toolLabel(item, wb.events),
        subtitle: String(item.tool_name ?? "tool"),
        body: previewFromTimeline(item),
      };
    }
    if (selection.kind === "file_write") {
      const item = fileWrites.find((f) => String(f.path) === selection.path);
      if (!item) return null;
      const preview = artifactToWritePreview(item);
      return {
        title: preview.path,
        subtitle: "文件变更",
        body: preview.new_text || preview.old_text,
        writePreview: preview,
      };
    }
    if (selection.kind === "patch") {
      const patch = patches.find((p) => p.patch_id === selection.patchId);
      if (!patch) return null;
      return {
        title: patch.patch_id,
        subtitle: "Patch",
        body: patch.new_text,
        patch,
      };
    }
    return null;
  }, [selection, fileWrites, patches, wb.events]);

  return (
    <aside className="flex h-full w-[min(360px,40vw)] min-w-0 shrink-0 flex-col overflow-hidden border-r border-border bg-background">
      <header className="flex shrink-0 items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">产物</h2>
          <p className="text-xs text-muted-foreground">工作区文件 · 工具输出</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded border border-input px-2 py-1 text-[11px] text-foreground/90 hover:bg-muted hover:text-foreground disabled:opacity-50"
            title="刷新工作区文件树"
            disabled={workspaceRefreshing}
            onClick={() => void refreshWorkspace()}
          >
            <RefreshCw
              className={`size-3.5 ${workspaceRefreshing ? "animate-spin" : ""}`}
              aria-hidden
            />
            刷新
          </button>
          {onClose ? (
            <button
              type="button"
              className="rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              title="收起产物栏"
              onClick={onClose}
            >
              ‹
            </button>
          ) : null}
        </div>
      </header>

      <div className="scrollbar-thin min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
        <section className="border-b border-border p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              工作区
            </h3>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                className={`rounded border px-2 py-0.5 text-[10px] ${
                  multiSelectMode
                    ? "border-primary/50 bg-primary/15 text-primary"
                    : "border-input text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
                onClick={() => {
                  setMultiSelectMode((value) => {
                    if (value) setCheckedPaths(new Set());
                    return !value;
                  });
                }}
              >
                {multiSelectMode ? "取消多选" : "多选"}
              </button>
              {multiSelectMode && checkedPaths.size > 0 ? (
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded border border-destructive/40 px-2 py-0.5 text-[10px] text-destructive hover:bg-destructive/10 disabled:opacity-50"
                  disabled={deleteSelected.isPending}
                  onClick={confirmDeleteSelected}
                >
                  <Trash2 className="size-3" aria-hidden />
                  删除 ({checkedPaths.size})
                </button>
              ) : null}
            </div>
          </div>
          <WorkspaceTree
            selectedPath={treeSelectedPath}
            multiSelectMode={multiSelectMode}
            checkedPaths={checkedPaths}
            onTogglePath={toggleCheckedPath}
            onSelectFile={(path) => {
              setWorkspaceSelectPath(path);
              onSelect({ kind: "workspace", path });
            }}
            onOpenFile={onOpenWorkspaceFile}
            onOpenSourcesLibrary={onOpenSourcesLibrary}
          />
          <p className="mt-2 text-[10px] text-muted-foreground/80">
            {multiSelectMode
              ? "多选模式下点击条目勾选，可删除文件或目录"
              : "单击选中 · 双击在新窗口查看完整内容"}
          </p>
        </section>

        <section className="border-b border-border p-3">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            工具产物
          </h3>
          {previewableTimeline.length === 0 ? (
            <p className="text-xs text-muted-foreground/80">暂无</p>
          ) : (
            <ul className="space-y-1">
              {previewableTimeline.map((item, idx) => {
                const path = timelinePath(item, wb.events);
                const label = path ?? toolLabel(item, wb.events);
                const active =
                  selection?.kind === "timeline" && selection.index === idx;
                return (
                  <li key={String(item.tool_call_id ?? idx)}>
                    <button
                      type="button"
                      className={`w-full rounded px-2 py-1.5 text-left text-xs ${
                        active
                          ? "bg-primary/15 text-primary"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      }`}
                      onClick={() =>
                        onSelect(
                          active
                            ? null
                            : { kind: "timeline", item, index: idx },
                        )
                      }
                    >
                      <span className="text-muted-foreground">{item.tool_name}</span>
                      <span className="ml-1 truncate">{label}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {fileWrites.length > 0 ? (
          <section className="border-b border-border p-3">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              文件变更
            </h3>
            <ul className="space-y-1">
              {fileWrites.map((item, idx) => {
                const path = String(item.path ?? "");
                const active =
                  selection?.kind === "file_write" && selection.path === path;
                return (
                  <li key={String(item.tool_call_id ?? path ?? idx)}>
                    <button
                      type="button"
                      className={`w-full truncate rounded px-2 py-1.5 text-left text-xs ${
                        active
                          ? "bg-primary/20 text-primary"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      }`}
                      onClick={() =>
                        onSelect(active ? null : { kind: "file_write", path })
                      }
                    >
                      {path}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        {patches.length > 0 ? (
          <section className="border-b border-border p-3">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Patch
            </h3>
            <ul className="space-y-1">
              {patches.map((patch) => {
                const active =
                  selection?.kind === "patch" &&
                  selection.patchId === patch.patch_id;
                return (
                  <li key={patch.patch_id}>
                    <button
                      type="button"
                      className={`w-full truncate rounded px-2 py-1.5 text-left text-xs ${
                        active
                          ? "bg-warning-muted text-warning"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      }`}
                      onClick={() =>
                        onSelect(
                          active
                            ? null
                            : { kind: "patch", patchId: patch.patch_id },
                        )
                      }
                    >
                      {patch.patch_id}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        <div className="min-w-0 space-y-3 overflow-hidden p-3">
          {scenarioExtras}
          <WritingCardsView artifacts={artifacts} />
          <RetrievalView artifacts={artifacts} />
          <ArtifactView artifacts={artifacts} />
        </div>
      </div>

      <div className="shrink-0 border-t border-border">
        {selectedPreview ? (
          <div className="scrollbar-thin max-h-[45vh] overflow-y-auto p-4">
            <p className="truncate text-sm font-medium text-foreground">
              {selectedPreview.title}
            </p>
            <p className="mb-2 text-xs text-muted-foreground">
              {selectedPreview.subtitle}
            </p>
            {"loading" in selectedPreview && selectedPreview.loading ? (
              <p className="text-xs text-muted-foreground">加载文件…</p>
            ) : "error" in selectedPreview && selectedPreview.error ? (
              <p className="text-xs text-destructive">
                无法读取文件
              </p>
            ) : "writePreview" in selectedPreview &&
              selectedPreview.writePreview ? (
              <WriteFileDiffPanel preview={selectedPreview.writePreview} />
            ) : "patch" in selectedPreview && selectedPreview.patch ? (
              <PatchDiffPanel
                patch={selectedPreview.patch}
                busy={wb.actionBusy}
                onAccept={(id) => void wb.handleAcceptPatch(id)}
                onReject={(id) => void wb.handleRejectPatch(id)}
              />
            ) : (
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-card p-3 text-xs text-foreground/90">
                {selectedPreview.body || "（无内容）"}
              </pre>
            )}
          </div>
        ) : (
          <p className="p-4 text-xs text-muted-foreground/80">
            双击工作区文件在新窗口查看，或点击工具产物预览
          </p>
        )}
      </div>
    </aside>
  );
}
