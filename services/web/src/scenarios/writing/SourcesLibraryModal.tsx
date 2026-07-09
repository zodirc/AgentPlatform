import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, X } from "lucide-react";
import { useEffect, useRef } from "react";
import {
  fetchWorkspaceEntries,
  uploadSourceFile,
} from "../../shared/api/client";
import { useAdminAuth } from "../../shared/auth/useAdminAuth";
import { workspaceEntryIcon } from "../agent/workspaceFileIcon";

function fileEntries(entries: string[]): string[] {
  return entries.filter((e) => !e.endsWith("/"));
}

type Props = {
  open: boolean;
  onClose: () => void;
  onOpenFile: (path: string) => void;
};

export function SourcesLibraryModal({ open, onClose, onOpenFile }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const { needsUnlock } = useAdminAuth();
  const queryClient = useQueryClient();

  const sourcesQuery = useQuery({
    queryKey: ["workspace-sources"],
    queryFn: async () => {
      const data = await fetchWorkspaceEntries("sources");
      return fileEntries(data.entries ?? []);
    },
    enabled: open && !needsUnlock,
  });

  const uploadMutation = useMutation({
    mutationFn: uploadSourceFile,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspace-sources"] });
      await queryClient.invalidateQueries({ queryKey: ["workspace-entries"] });
      if (inputRef.current) inputRef.current.value = "";
    },
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const files = sourcesQuery.data ?? [];

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="写作资料库"
      onClick={onClose}
    >
      <div
        className="flex h-[min(85vh,720px)] w-[min(92vw,640px)] flex-col overflow-hidden rounded-xl border border-violet-900/50 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-slate-800 px-4 py-3">
          <FolderOpen className="h-5 w-5 shrink-0 text-violet-400" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-100">写作资料库</p>
            <p className="text-xs text-slate-500">
              workspace/sources/ · 双击文件查看 · 供 search_sources 检索
            </p>
          </div>
          <button
            type="button"
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-900 hover:text-slate-100"
            onClick={onClose}
            title="关闭 (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {needsUnlock ? (
            <p className="text-sm text-amber-400">
              请先在页面顶部输入 Admin 密码解锁，才能浏览和上传资料。
            </p>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/40 p-3">
                <input
                  ref={inputRef}
                  type="file"
                  accept=".md,.txt,.markdown,.json,text/plain,text/markdown"
                  className="max-w-full text-xs text-slate-400 file:mr-2 file:rounded file:border-0 file:bg-slate-800 file:px-2 file:py-1 file:text-slate-200"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) uploadMutation.mutate(file);
                  }}
                />
                {uploadMutation.isPending ? (
                  <span className="text-xs text-slate-500">上传并重建索引…</span>
                ) : null}
                {uploadMutation.isSuccess ? (
                  <span className="text-xs text-emerald-400">
                    已保存 {uploadMutation.data.path}
                    {uploadMutation.data.index?.chunks != null
                      ? ` · ${uploadMutation.data.index.chunks} 块`
                      : ""}
                  </span>
                ) : null}
                {uploadMutation.isError ? (
                  <span className="text-xs text-rose-400">
                    {uploadMutation.error.message || "上传失败"}
                  </span>
                ) : null}
              </div>

              {sourcesQuery.isLoading ? (
                <p className="text-sm text-slate-500">加载中…</p>
              ) : files.length === 0 ? (
                <p className="text-sm text-slate-500">暂无资料文件</p>
              ) : (
                <ul className="space-y-1">
                  {files.map((name) => {
                    const path = `sources/${name}`;
                    const { Icon, className: iconClass } = workspaceEntryIcon(
                      name,
                      false,
                    );
                    return (
                      <li key={name}>
                        <button
                          type="button"
                          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-900"
                          onDoubleClick={() => onOpenFile(path)}
                          title="双击查看文件"
                        >
                          <Icon
                            className={`h-4 w-4 shrink-0 ${iconClass}`}
                            aria-hidden
                          />
                          <span className="truncate">{name}</span>
                          <span className="ml-auto text-[10px] text-slate-600">
                            双击查看
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
