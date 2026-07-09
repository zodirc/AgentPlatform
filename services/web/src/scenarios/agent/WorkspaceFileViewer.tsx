import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect } from "react";
import { fetchWorkspaceFile } from "../../shared/api/client";
import { workspaceEntryIcon } from "./workspaceFileIcon";

type Props = {
  path: string | null;
  onClose: () => void;
};

export function WorkspaceFileViewer({ path, onClose }: Props) {
  const fileName = path?.split("/").pop() ?? "";
  const { Icon, className: iconClass } = workspaceEntryIcon(fileName, false);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["workspace-file-viewer", path],
    queryFn: () => fetchWorkspaceFile(path!),
    enabled: Boolean(path),
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!path) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [path, onClose]);

  if (!path) return null;

  const truncated = Boolean(data?.content?.includes("\n...[truncated]"));

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`查看文件 ${path}`}
      onClick={onClose}
    >
      <div
        className="flex h-[min(90vh,900px)] w-[min(96vw,1100px)] flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-slate-800 px-4 py-3">
          <Icon className={`h-5 w-5 shrink-0 ${iconClass}`} aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-100">
              {fileName}
            </p>
            <p className="truncate text-xs text-slate-500">{path}</p>
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

        <div className="min-h-0 flex-1 overflow-auto bg-slate-900/50 p-4">
          {isLoading ? (
            <p className="text-sm text-slate-500">加载中…</p>
          ) : isError ? (
            <p className="text-sm text-rose-400">
              无法读取文件
              {error instanceof Error ? `：${error.message}` : ""}
              （请确认已 Admin 解锁）
            </p>
          ) : (
            <>
              {truncated ? (
                <p className="mb-2 text-xs text-amber-400/90">
                  内容超过 32KB，仅显示前段（与 runtime read_file 限制一致）
                </p>
              ) : null}
              <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-slate-200">
                {data?.content ?? ""}
              </pre>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
