import { useMemo, useState, type ReactNode } from "react";
import type { TurnEvent } from "../../shared/api/client";
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
  onClose,
}: Props) {
  const view = wb.view;
  const artifacts = view?.artifacts ?? [];

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
    <aside className="flex h-full w-[min(360px,40vw)] shrink-0 flex-col border-r border-slate-800 bg-slate-950">
      <header className="flex shrink-0 items-start justify-between gap-2 border-b border-slate-800 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-slate-200">产物</h2>
          <p className="text-xs text-slate-500">工作区文件 · 工具输出</p>
        </div>
        {onClose ? (
          <button
            type="button"
            className="shrink-0 rounded px-1.5 py-0.5 text-xs text-slate-500 hover:bg-slate-900 hover:text-slate-200"
            title="收起产物栏"
            onClick={onClose}
          >
            ‹
          </button>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className="border-b border-slate-800 p-3">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
            工作区
          </h3>
          <WorkspaceTree
            selectedPath={treeSelectedPath}
            onSelectFile={(path) => {
              setWorkspaceSelectPath(path);
              onSelect({ kind: "workspace", path });
            }}
            onOpenFile={onOpenWorkspaceFile}
          />
          <p className="mt-2 text-[10px] text-slate-600">
            单击选中 · 双击在新窗口查看完整内容
          </p>
        </section>

        <section className="border-b border-slate-800 p-3">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
            工具产物
          </h3>
          {previewableTimeline.length === 0 ? (
            <p className="text-xs text-slate-600">暂无</p>
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
                          ? "bg-sky-900/40 text-sky-200"
                          : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
                      }`}
                      onClick={() =>
                        onSelect(
                          active
                            ? null
                            : { kind: "timeline", item, index: idx },
                        )
                      }
                    >
                      <span className="text-slate-500">{item.tool_name}</span>
                      <span className="ml-1 truncate">{label}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {fileWrites.length > 0 ? (
          <section className="border-b border-slate-800 p-3">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
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
                          ? "bg-violet-900/40 text-violet-200"
                          : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
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
          <section className="border-b border-slate-800 p-3">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
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
                          ? "bg-amber-900/40 text-amber-200"
                          : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
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

        <div className="space-y-3 p-3">
          {scenarioExtras}
          <RetrievalView artifacts={artifacts} />
          <ArtifactView artifacts={artifacts} />
        </div>
      </div>

      <div className="shrink-0 border-t border-slate-800">
        {selectedPreview ? (
          <div className="max-h-[45vh] overflow-y-auto p-4">
            <p className="truncate text-sm font-medium text-slate-200">
              {selectedPreview.title}
            </p>
            <p className="mb-2 text-xs text-slate-500">
              {selectedPreview.subtitle}
            </p>
            {"loading" in selectedPreview && selectedPreview.loading ? (
              <p className="text-xs text-slate-500">加载文件…</p>
            ) : "error" in selectedPreview && selectedPreview.error ? (
              <p className="text-xs text-rose-400">
                无法读取文件（请确认已 Admin 解锁）
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
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-xs text-slate-300">
                {selectedPreview.body || "（无内容）"}
              </pre>
            )}
          </div>
        ) : (
          <p className="p-4 text-xs text-slate-600">
            双击工作区文件在新窗口查看，或点击工具产物预览
          </p>
        )}
      </div>
    </aside>
  );
}
