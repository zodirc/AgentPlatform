import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  fetchSourcesIndexStatus,
  syncSourcesIndex,
  uploadSourceFile,
  uploadSourceText,
  type SourcesIndexStatus,
  type SourceUploadResult,
} from "../../shared/api/client";
import { Button } from "../../components/ui/button";
import { workspaceEntryIcon } from "../agent/workspaceFileIcon";
import { listSourcesLibraryFiles } from "./listSourcesLibraryFiles";
import {
  libraryIndexStatusLabel,
  sourcesIndexStatusLabel,
} from "./sourcesIndexStatus";

type Props = {
  open: boolean;
  onClose: () => void;
  onOpenFile: (path: string) => void;
};

export function SourcesLibraryModal({ open, onClose, onOpenFile }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteBody, setPasteBody] = useState("");
  const [watchPath, setWatchPath] = useState<string | null>(null);
  /** When true, poll library-wide index status (IX1 sync button). */
  const [watchLibrary, setWatchLibrary] = useState(false);

  const sourcesQuery = useQuery({
    queryKey: ["workspace-sources"],
    queryFn: () => listSourcesLibraryFiles(),
    enabled: open,
  });

  const indexQuery = useQuery({
    queryKey: ["sources-index-status", watchPath ?? (watchLibrary ? "__library__" : null)],
    queryFn: () =>
      fetchSourcesIndexStatus(watchPath ?? undefined),
    enabled: open && (Boolean(watchPath) || watchLibrary),
    refetchInterval: (query) => {
      const data = query.state.data as SourcesIndexStatus | undefined;
      if (!data) return 1000;
      if (data.status === "building" || data.status === "pending") return 1000;
      if (watchPath && !data.path_current && data.status !== "error")
        return 1000;
      return false;
    },
  });

  useEffect(() => {
    if (!watchPath && !watchLibrary) return;
    const data = indexQuery.data;
    if (!data) return;
    if (data.status === "error") return;
    if (data.status === "ready" || data.status === "idle") {
      setWatchLibrary(false);
      void queryClient.invalidateQueries({ queryKey: ["workspace-sources"] });
    }
    if (
      watchPath &&
      (data.path_current || (data.status === "ready" && data.path_indexed))
    ) {
      void queryClient.invalidateQueries({ queryKey: ["workspace-sources"] });
    }
  }, [watchPath, watchLibrary, indexQuery.data, queryClient]);

  const invalidateSources = async () => {
    await queryClient.invalidateQueries({ queryKey: ["workspace-sources"] });
    await queryClient.invalidateQueries({ queryKey: ["workspace-entries"] });
  };

  const onUploadSuccess = async (result: SourceUploadResult) => {
    await invalidateSources();
    setWatchLibrary(false);
    setWatchPath(result.path);
    await queryClient.invalidateQueries({
      queryKey: ["sources-index-status", result.path],
    });
  };

  const uploadMutation = useMutation({
    mutationFn: uploadSourceFile,
    onSuccess: async (result) => {
      await onUploadSuccess(result);
      if (inputRef.current) inputRef.current.value = "";
    },
  });

  const pasteMutation = useMutation({
    mutationFn: ({ title, content }: { title: string; content: string }) =>
      uploadSourceText(title, content),
    onSuccess: async (result) => {
      await onUploadSuccess(result);
      setPasteTitle("");
      setPasteBody("");
    },
  });

  const syncMutation = useMutation({
    mutationFn: syncSourcesIndex,
    onSuccess: async () => {
      setWatchPath(null);
      setWatchLibrary(true);
      await queryClient.invalidateQueries({
        queryKey: ["sources-index-status", "__library__"],
      });
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
  const busy =
    uploadMutation.isPending ||
    pasteMutation.isPending ||
    syncMutation.isPending;
  const lastErr =
    pasteMutation.error?.message ||
    uploadMutation.error?.message ||
    syncMutation.error?.message ||
    null;
  const pathPolling =
    Boolean(watchPath) &&
    (indexQuery.isFetching ||
      indexQuery.data?.status === "building" ||
      indexQuery.data?.status === "pending" ||
      (indexQuery.data != null &&
        !indexQuery.data.path_current &&
        indexQuery.data.status !== "error" &&
        indexQuery.data.status !== "ready"));
  const libraryPolling =
    watchLibrary &&
    (syncMutation.isPending ||
      indexQuery.isFetching ||
      indexQuery.data?.status === "building" ||
      indexQuery.data?.status === "pending");
  const pathStatusLine = sourcesIndexStatusLabel(
    watchPath,
    indexQuery.data,
    pathPolling,
  );
  const libraryStatusLine =
    watchLibrary || libraryPolling
      ? libraryIndexStatusLabel(indexQuery.data, libraryPolling)
      : null;
  const statusLine = pathStatusLine ?? libraryStatusLine;

  const submitPaste = () => {
    const content = pasteBody.trim();
    if (!content || busy) return;
    pasteMutation.mutate({ title: pasteTitle, content });
  };

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="写作资料库"
      onClick={onClose}
    >
      <div
        className="flex h-[min(90vh,800px)] w-[min(92vw,640px)] flex-col overflow-hidden rounded-xl border border-violet-900/50 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-slate-800 px-4 py-3">
          <FolderOpen className="h-5 w-5 shrink-0 text-violet-400" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-100">写作资料库</p>
            <p className="text-xs text-slate-500">
              当前作品 sources/ · 含子目录与 seed 挂载 · 粘贴或上传 · 同步不挡对话 ·
              投影就绪≠效果过关
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shrink-0 border-slate-700 text-slate-200"
            disabled={busy || libraryPolling}
            onClick={() => syncMutation.mutate()}
            title="增量投影到索引（后台，不挡发送）"
          >
            <RefreshCw
              className={`mr-1.5 h-3.5 w-3.5 ${libraryPolling ? "animate-spin" : ""}`}
            />
            {libraryPolling || syncMutation.isPending
              ? "同步中…"
              : "同步资料库"}
          </Button>
          <button
            type="button"
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-900 hover:text-slate-100"
            onClick={onClose}
            title="关闭 (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4">
              <div className="mb-4 space-y-3 rounded-lg border border-slate-800 bg-slate-900/40 p-3">
                <div>
                  <p className="mb-2 text-xs font-medium text-slate-300">
                    在线输入 / 粘贴
                  </p>
                  <input
                    type="text"
                    value={pasteTitle}
                    onChange={(e) => setPasteTitle(e.target.value)}
                    placeholder="标题（可选，默认 paste-note.md）"
                    className="mb-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-violet-700 focus:outline-none"
                    disabled={busy}
                  />
                  <textarea
                    value={pasteBody}
                    onChange={(e) => setPasteBody(e.target.value)}
                    placeholder="粘贴或输入资料正文（Markdown / 纯文本）…"
                    rows={6}
                    className="w-full resize-y rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-violet-700 focus:outline-none"
                    disabled={busy}
                  />
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="border-violet-800 text-violet-200"
                      disabled={busy || !pasteBody.trim()}
                      onClick={submitPaste}
                    >
                      {pasteMutation.isPending ? "保存中…" : "保存到资料库"}
                    </Button>
                    <span className="text-[10px] text-slate-600">
                      保存后后台投影；手改文件由监视自动跟上，也可点「同步资料库」
                    </span>
                  </div>
                </div>

                <div className="border-t border-slate-800 pt-3">
                  <p className="mb-2 text-xs font-medium text-slate-300">
                    上传本地文件
                  </p>
                  <input
                    ref={inputRef}
                    type="file"
                    accept=".md,.txt,.markdown,.json,text/plain,text/markdown"
                    className="max-w-full text-xs text-slate-400 file:mr-2 file:rounded file:border-0 file:bg-slate-800 file:px-2 file:py-1 file:text-slate-200"
                    disabled={busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) uploadMutation.mutate(file);
                    }}
                  />
                </div>

                {busy && !libraryPolling ? (
                  <span className="text-xs text-slate-500">正在保存文件…</span>
                ) : null}
                {statusLine && !(busy && !libraryPolling) ? (
                  <span
                    className={
                      statusLine.tone === "err"
                        ? "block text-xs text-rose-400"
                        : statusLine.tone === "pending"
                          ? "block text-xs text-amber-300"
                          : "block text-xs text-emerald-400"
                    }
                  >
                    {statusLine.text}
                  </span>
                ) : null}
                {lastErr && !busy ? (
                  <span className="block text-xs text-rose-400">{lastErr}</span>
                ) : null}
              </div>

              {sourcesQuery.isLoading ? (
                <p className="text-sm text-slate-500">加载中…</p>
              ) : files.length === 0 ? (
                <p className="text-sm text-slate-500">
                  暂无资料文件（含子目录）。可粘贴上传，或把 .md 放到当前作品
                  sources/。
                </p>
              ) : (
                <ul className="space-y-1">
                  {files.map((rel) => {
                    const path = `sources/${rel}`;
                    const { Icon, className: iconClass } = workspaceEntryIcon(
                      rel.split("/").pop() ?? rel,
                      false,
                    );
                    return (
                      <li key={rel}>
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
                          <span className="truncate font-mono text-[12px]">
                            {rel}
                          </span>
                          <span className="ml-auto text-[10px] text-slate-600">
                            双击查看
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
        </div>
      </div>
    </div>
  );
}
