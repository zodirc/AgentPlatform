import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchAstIndexStatus, fetchDefaultWork } from "../shared/api/client";
import {
  fetchAstIndexInspect,
  type AstInspectFileRow,
  type AstSymbolNode,
} from "./inspectApi";

function KindBadge({ kind }: { kind: string }) {
  return (
    <span className="rounded bg-muted px-1 py-px font-mono text-[10px] text-muted-foreground">
      {kind}
    </span>
  );
}

function SymbolTree({ nodes, depth = 0 }: { nodes: AstSymbolNode[]; depth?: number }) {
  return (
    <ul className={depth === 0 ? "space-y-0.5" : "ml-3 space-y-0.5 border-l border-border pl-2"}>
      {nodes.map((n) => (
        <li key={`${n.kind}:${n.name}:${n.line}`}>
          <div className="flex flex-wrap items-baseline gap-1.5 text-[12px]">
            <KindBadge kind={n.kind} />
            <span className="font-mono text-foreground">{n.name}</span>
            <span className="font-mono text-[10px] text-muted-foreground">
              L{n.line}
              {n.end_line ? `–${n.end_line}` : ""}
            </span>
          </div>
          {n.children && n.children.length > 0 ? (
            <SymbolTree nodes={n.children} depth={depth + 1} />
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function AstIndexTreeCard() {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<AstInspectFileRow | null>(null);
  const [view, setView] = useState<"tree" | "text">("tree");

  const work = useQuery({
    queryKey: ["works", "default"],
    queryFn: fetchDefaultWork,
    staleTime: 60_000,
  });
  const workId = work.data?.id;

  const indexStatus = useQuery({
    queryKey: ["ast-index-status", workId ?? "default"],
    queryFn: () => fetchAstIndexStatus({ enqueue: false, workId }),
    enabled: Boolean(workId),
    staleTime: 5_000,
  });

  const listQuery = useQuery({
    queryKey: [
      "ast-index-inspect",
      workId,
      q,
      indexStatus.data?.files_indexed,
      indexStatus.data?.generation,
      indexStatus.data?.catchup_remaining,
    ],
    queryFn: () =>
      fetchAstIndexInspect({ workId, q: q.trim() || undefined }),
    enabled: Boolean(workId),
    staleTime: 10_000,
  });

  const fileQuery = useQuery({
    queryKey: ["ast-index-file", workId, selected?.path],
    queryFn: () => fetchAstIndexInspect({ workId, path: selected!.path }),
    enabled: Boolean(workId && selected?.path),
  });

  const files = listQuery.data?.files ?? [];
  const detail = fileQuery.data?.file;
  const disabled = listQuery.data?.enabled === false;

  return (
    <section className="rounded-xl border border-border bg-card/60 p-4">
      <h2 className="text-sm font-medium text-foreground">AST 索引外形</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        工作区代码索引存的是定义级符号树（class / function / method +
        容器链），不是完整 CST。与上方进度条同一套索引。
      </p>

      {disabled ? (
        <p className="mt-3 text-xs text-muted-foreground">当前部署未启用 AST 索引。</p>
      ) : (
        <>
          <div className="mt-3">
            <input
              className="w-full rounded border border-input bg-background px-2 py-1 text-xs"
              placeholder="按路径筛选…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
            <div className="max-h-[28rem] overflow-auto rounded-lg border border-border bg-background">
              {listQuery.isLoading ? (
                <p className="p-3 text-xs text-muted-foreground">加载文件…</p>
              ) : listQuery.isError ? (
                <p className="p-3 text-xs text-destructive">
                  {(listQuery.error as Error).message || "无法读取 AST"}
                </p>
              ) : files.length === 0 ? (
                <p className="p-3 text-xs text-muted-foreground">
                  索引为空或尚未就绪。可点「重建索引」，或先打开 Agent 工作台触发冷启动。
                </p>
              ) : (
                <ul className="py-1">
                  {files.map((row) => {
                    const active = selected?.path === row.path;
                    return (
                      <li key={row.path}>
                        <button
                          type="button"
                          className={`w-full px-2 py-1.5 text-left text-xs ${
                            active ? "bg-primary/15" : "hover:bg-muted"
                          }`}
                          onClick={() => setSelected(row)}
                        >
                          <span className="block truncate font-mono text-foreground">
                            {row.path}
                          </span>
                          <span className="text-[10px] text-muted-foreground">
                            {row.lang} · {row.symbol_count} 符号
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <div className="max-h-[28rem] overflow-auto">
              {!selected ? (
                <p className="text-xs text-muted-foreground">左侧选文件查看符号树。</p>
              ) : fileQuery.isLoading ? (
                <p className="text-xs text-muted-foreground">加载符号…</p>
              ) : fileQuery.isError ? (
                <p className="text-xs text-destructive">
                  {(fileQuery.error as Error).message || "读取失败"}
                </p>
              ) : detail?.missing ? (
                <p className="text-xs text-muted-foreground">该路径不在当前 generation。</p>
              ) : (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-mono text-[11px] text-muted-foreground">
                      {detail?.path} · {detail?.lang} ·{" "}
                      {detail?.symbols?.length ?? 0} 符号
                    </p>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        className={`rounded px-2 py-0.5 text-[11px] ${
                          view === "tree"
                            ? "bg-muted text-foreground"
                            : "text-muted-foreground"
                        }`}
                        onClick={() => setView("tree")}
                      >
                        树
                      </button>
                      <button
                        type="button"
                        className={`rounded px-2 py-0.5 text-[11px] ${
                          view === "text"
                            ? "bg-muted text-foreground"
                            : "text-muted-foreground"
                        }`}
                        onClick={() => setView("text")}
                      >
                        ASCII
                      </button>
                    </div>
                  </div>
                  {detail?.imports && detail.imports.length > 0 ? (
                    <p className="text-[11px] text-muted-foreground">
                      imports: {detail.imports.join(", ")}
                    </p>
                  ) : null}
                  {view === "text" ? (
                    <pre className="overflow-auto rounded-lg border border-border bg-background p-3 font-mono text-[12px] leading-relaxed text-foreground/90">
                      {detail?.tree_text || "(no symbols)"}
                    </pre>
                  ) : detail?.tree && detail.tree.length > 0 ? (
                    <div className="rounded-lg border border-border bg-background p-3">
                      <SymbolTree nodes={detail.tree} />
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">该文件没有抽出定义符号。</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
