import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchSourcesIndexStatus,
  syncSourcesIndex,
  uploadSourceFile,
  uploadSourceText,
  type SourcesIndexStatus,
  type SourceUploadResult,
} from "../../shared/api/client";
import { Button } from "../../components/ui/button";
import { isSeedRelUnderSources } from "../../shared/workspace/seedPath";
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
  const { mine, seed } = useMemo(() => {
    const mineList: string[] = [];
    const seedList: string[] = [];
    for (const rel of files) {
      if (isSeedRelUnderSources(rel)) seedList.push(rel);
      else mineList.push(rel);
    }
    return { mine: mineList, seed: seedList };
  }, [files]);
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
      className="fixed inset-0 z-[90] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="写作资料库"
      onClick={onClose}
    >
      <div
        className="flex h-[min(90vh,800px)] w-[min(92vw,640px)] flex-col overflow-hidden rounded-xl border border-primary/30 bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
          <FolderOpen className="h-5 w-5 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">写作资料库</p>
            <p className="text-xs text-muted-foreground">
              我的资料可上传管理；系统资料（seed）只读可见、不可删除 · 同步不挡对话
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shrink-0 border-input text-foreground"
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
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
            title="关闭 (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4">
              <div className="mb-4 space-y-3 rounded-lg border border-border bg-card/40 p-3">
                <div>
                  <p className="mb-2 text-xs font-medium text-foreground/90">
                    在线输入 / 粘贴
                  </p>
                  <input
                    type="text"
                    value={pasteTitle}
                    onChange={(e) => setPasteTitle(e.target.value)}
                    placeholder="标题（可选，默认 paste-note.md）"
                    className="mb-2 w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground/70 focus:border-ring focus:outline-none"
                    disabled={busy}
                  />
                  <textarea
                    value={pasteBody}
                    onChange={(e) => setPasteBody(e.target.value)}
                    placeholder="粘贴或输入资料正文（Markdown / 纯文本）…"
                    rows={6}
                    className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:border-ring focus:outline-none"
                    disabled={busy}
                  />
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="border-primary/40 text-primary"
                      disabled={busy || !pasteBody.trim()}
                      onClick={submitPaste}
                    >
                      {pasteMutation.isPending ? "保存中…" : "保存到资料库"}
                    </Button>
                    <span className="text-[10px] text-muted-foreground/80">
                      保存后后台投影；手改文件由监视自动跟上，也可点「同步资料库」
                    </span>
                  </div>
                </div>

                <div className="border-t border-border pt-3">
                  <p className="mb-2 text-xs font-medium text-foreground/90">
                    上传本地文件
                  </p>
                  <input
                    ref={inputRef}
                    type="file"
                    accept=".md,.txt,.markdown,.json,text/plain,text/markdown"
                    className="max-w-full text-xs text-muted-foreground file:mr-2 file:rounded file:border-0 file:bg-muted file:px-2 file:py-1 file:text-foreground"
                    disabled={busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) uploadMutation.mutate(file);
                    }}
                  />
                </div>

                {busy && !libraryPolling ? (
                  <span className="text-xs text-muted-foreground">正在保存文件…</span>
                ) : null}
                {statusLine && !(busy && !libraryPolling) ? (
                  <span
                    className={
                      statusLine.tone === "err"
                        ? "block text-xs text-destructive"
                        : statusLine.tone === "pending"
                          ? "block text-xs text-warning"
                          : "block text-xs text-success"
                    }
                  >
                    {statusLine.text}
                  </span>
                ) : null}
                {lastErr && !busy ? (
                  <span className="block text-xs text-destructive">{lastErr}</span>
                ) : null}
              </div>

              {sourcesQuery.isLoading ? (
                <p className="text-sm text-muted-foreground">加载中…</p>
              ) : (
                <div className="space-y-5">
                  <section>
                    <div className="mb-2 flex items-baseline justify-between gap-2">
                      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        我的资料
                      </h3>
                      <span className="text-[10px] text-muted-foreground/80">
                        {mine.length} 个文件 · 可上传
                      </span>
                    </div>
                    {mine.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        暂无个人资料。可上方粘贴/上传，文件落在当前作品 sources/。
                      </p>
                    ) : (
                      <ul className="space-y-1">
                        {mine.map((rel) => {
                          const path = `sources/${rel}`;
                          const { Icon, className: iconClass } =
                            workspaceEntryIcon(rel.split("/").pop() ?? rel, false);
                          return (
                            <li key={rel}>
                              <button
                                type="button"
                                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-foreground/90 hover:bg-muted"
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
                                <span className="ml-auto text-[10px] text-muted-foreground/80">
                                  双击查看
                                </span>
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </section>

                  <section>
                    <div className="mb-2 flex items-baseline justify-between gap-2">
                      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        系统资料
                      </h3>
                      <span className="text-[10px] text-muted-foreground/80">
                        {seed.length} 个文件 · 只读
                      </span>
                    </div>
                    <p className="mb-2 text-[11px] text-muted-foreground">
                      部署挂载的常驻语料（sources/seed），可供检索与引用，不可在 Web
                      上删除或覆盖。
                    </p>
                    {seed.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        当前未挂载系统资料。
                      </p>
                    ) : (
                      <ul className="space-y-1">
                        {seed.map((rel) => {
                          const path = `sources/${rel}`;
                          const { Icon, className: iconClass } =
                            workspaceEntryIcon(rel.split("/").pop() ?? rel, false);
                          return (
                            <li key={rel}>
                              <button
                                type="button"
                                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-muted-foreground hover:bg-muted/80"
                                onDoubleClick={() => onOpenFile(path)}
                                title="系统资料 · 只读 · 双击查看"
                              >
                                <Icon
                                  className={`h-4 w-4 shrink-0 ${iconClass}`}
                                  aria-hidden
                                />
                                <span className="truncate font-mono text-[12px]">
                                  {rel}
                                </span>
                                <span className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                  只读
                                </span>
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </section>
                </div>
              )}
        </div>
      </div>
    </div>
  );
}
