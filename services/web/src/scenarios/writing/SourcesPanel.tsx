import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Card, CardTitle } from "../../components/ui/card";
import {
  fetchWorkspaceEntries,
  uploadSourceFile,
} from "../../shared/api/client";
import { useAdminAuth } from "../../shared/auth/useAdminAuth";

function fileEntries(entries: string[]): string[] {
  return entries.filter((e) => !e.endsWith("/"));
}

export function SourcesPanel() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const { needsUnlock } = useAdminAuth();
  const queryClient = useQueryClient();

  const sourcesQuery = useQuery({
    queryKey: ["workspace-sources"],
    queryFn: async () => {
      try {
        const data = await fetchWorkspaceEntries("sources");
        return fileEntries(data.entries ?? []);
      } catch {
        return [];
      }
    },
    enabled: !needsUnlock,
  });

  const uploadMutation = useMutation({
    mutationFn: uploadSourceFile,
    onSuccess: async () => {
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["workspace-sources"] });
      if (inputRef.current) inputRef.current.value = "";
    },
    onError: (err: Error) => {
      setError(err.message || "上传失败");
    },
  });

  const files = sourcesQuery.data ?? [];

  return (
    <Card className="border-violet-900/50 bg-violet-950/20">
      <CardTitle className="text-violet-200">写作资料库</CardTitle>
      <p className="mt-1 text-xs text-slate-500">
        上传到 workspace/sources/，供 search_sources 检索引用（.md / .txt，最大
        1MB）
      </p>

      {needsUnlock ? (
        <p className="mt-3 text-xs text-amber-400">
          请先在页面顶部输入 Admin 密码解锁，才能上传资料。
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            ref={inputRef}
            type="file"
            accept=".md,.txt,.markdown,.json,text/plain,text/markdown"
            className="max-w-full text-xs text-slate-400 file:mr-2 file:rounded file:border-0 file:bg-slate-800 file:px-2 file:py-1 file:text-slate-200"
            onChange={(e) => {
              setError(null);
              const file = e.target.files?.[0];
              if (file) uploadMutation.mutate(file);
            }}
          />
          {uploadMutation.isPending ? (
            <span className="text-xs text-slate-500">上传并重建索引…</span>
          ) : null}
        </div>
      )}

      {error ? <p className="mt-2 text-xs text-rose-400">{error}</p> : null}

      {uploadMutation.isSuccess ? (
        <p className="mt-2 text-xs text-emerald-400">
          已保存 {uploadMutation.data.path}
          {uploadMutation.data.index?.chunks != null
            ? ` · 索引 ${uploadMutation.data.index.chunks} 块`
            : ""}
        </p>
      ) : null}

      <ul className="mt-3 space-y-1 text-xs text-slate-400">
        {sourcesQuery.isLoading ? (
          <li>加载中…</li>
        ) : files.length === 0 ? (
          <li className="text-slate-500">暂无资料文件</li>
        ) : (
          files.map((name) => (
            <li key={name} className="rounded bg-slate-950 px-2 py-1">
              sources/{name}
            </li>
          ))
        )}
      </ul>
    </Card>
  );
}
