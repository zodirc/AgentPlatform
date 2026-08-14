import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { fetchDefaultWork } from "../shared/api/client";
import {
  fetchSourceChunkFiles,
  fetchSourceChunksForPath,
  type ChunkFileRow,
  type SourceChunk,
} from "./inspectApi";

type VisFilter = "all" | "seed" | "private";

function visLabel(v: string): string {
  if (v === "seed") return "种子";
  if (v === "private") return "本地";
  return v || "—";
}

function lineSpan(row: { line_start?: number | null; line_end?: number | null }): string {
  if (row.line_start == null) return "";
  if (row.line_end != null && row.line_end !== row.line_start) {
    return `L${row.line_start}–${row.line_end}`;
  }
  return `L${row.line_start}`;
}

function ChunkBody({ chunk }: { chunk: SourceChunk }) {
  return (
    <article className="rounded-lg border border-border bg-background p-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground">
          {chunk.section_title || "（无小节标题）"}
        </span>
        <span className="font-mono">
          {lineSpan(chunk)}
          {chunk.chars ? ` · ${chunk.chars} 字` : ""}
          {chunk.truncated ? " · 已截断" : ""}
        </span>
      </header>
      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-foreground/90">
        {chunk.text || "（空 chunk）"}
      </pre>
    </article>
  );
}

export function CorpusChunksCard() {
  const [vis, setVis] = useState<VisFilter>("all");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<ChunkFileRow | null>(null);

  const work = useQuery({
    queryKey: ["works", "default"],
    queryFn: fetchDefaultWork,
    staleTime: 60_000,
  });
  const workId = work.data?.id;
  const seedOn = work.data?.visibility_seed !== false;

  const filesQuery = useQuery({
    queryKey: ["source-chunk-files", workId, vis, q],
    queryFn: () =>
      fetchSourceChunkFiles({
        workId,
        visibility: vis,
        q: q.trim() || undefined,
      }),
    enabled: Boolean(workId),
    staleTime: 15_000,
  });

  const chunksQuery = useQuery({
    queryKey: ["source-chunks", workId, selected?.path],
    queryFn: () => fetchSourceChunksForPath(selected!.path, { workId }),
    enabled: Boolean(workId && selected?.path),
  });

  const files = filesQuery.data?.files ?? [];
  const grouped = useMemo(() => {
    const seed = files.filter((f) => f.visibility === "seed");
    const local = files.filter((f) => f.visibility !== "seed");
    return { seed, local };
  }, [files]);

  return (
    <section className="rounded-xl border border-border bg-card/60 p-4">
      <h2 className="text-sm font-medium text-foreground">语料切分（Chunks）</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        查看写入向量库后的实际切块正文。种子 = 部署挂载的
        sources/seed；本地 = 本 Work 上传/资料。不含 embedding。
      </p>
      {!seedOn ? (
        <p className="mt-2 text-[11px] text-muted-foreground">
          当前账户已关闭产品种子语料，列表不会出现种子块。
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {(
          [
            ["all", "全部"],
            ["seed", "种子"],
            ["private", "本地"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`rounded-md px-2.5 py-1 text-xs ${
              vis === id
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => {
              setVis(id);
              setSelected(null);
            }}
          >
            {label}
          </button>
        ))}
        <input
          className="min-w-[10rem] flex-1 rounded border border-input bg-background px-2 py-1 text-xs"
          placeholder="按路径筛选…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
        <div className="max-h-[28rem] overflow-auto rounded-lg border border-border bg-background">
          {filesQuery.isLoading ? (
            <p className="p-3 text-xs text-muted-foreground">加载文件…</p>
          ) : filesQuery.isError ? (
            <p className="p-3 text-xs text-destructive">
              {(filesQuery.error as Error).message || "无法读取切分"}
            </p>
          ) : files.length === 0 ? (
            <p className="p-3 text-xs text-muted-foreground">
              暂无已索引切块。可先在资料库同步，或确认种子未关闭。
            </p>
          ) : (
            <FileGroups
              seed={grouped.seed}
              local={grouped.local}
              selected={selected}
              onSelect={setSelected}
            />
          )}
        </div>
        <div className="max-h-[28rem] space-y-2 overflow-auto">
          {!selected ? (
            <p className="text-xs text-muted-foreground">左侧选一份文件查看切块正文。</p>
          ) : chunksQuery.isLoading ? (
            <p className="text-xs text-muted-foreground">加载切块…</p>
          ) : chunksQuery.isError ? (
            <p className="text-xs text-destructive">
              {(chunksQuery.error as Error).message || "读取失败"}
            </p>
          ) : (chunksQuery.data?.chunks ?? []).length === 0 ? (
            <p className="text-xs text-muted-foreground">该路径没有可见切块。</p>
          ) : (
            <>
              <p className="font-mono text-[11px] text-muted-foreground">
                {selected.path} · {chunksQuery.data?.total ?? 0} 块
                {chunksQuery.data?.truncated ? "（已截断）" : ""}
              </p>
              {(chunksQuery.data?.chunks ?? []).map((c) => (
                <ChunkBody key={c.chunk_id || `${c.line_start}-${c.chars}`} chunk={c} />
              ))}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function FileGroups({
  seed,
  local,
  selected,
  onSelect,
}: {
  seed: ChunkFileRow[];
  local: ChunkFileRow[];
  selected: ChunkFileRow | null;
  onSelect: (row: ChunkFileRow) => void;
}) {
  return (
    <div className="py-1">
      {seed.length > 0 ? (
        <Group title="种子语料" rows={seed} selected={selected} onSelect={onSelect} />
      ) : null}
      {local.length > 0 ? (
        <Group title="本地语料" rows={local} selected={selected} onSelect={onSelect} />
      ) : null}
    </div>
  );
}

function Group({
  title,
  rows,
  selected,
  onSelect,
}: {
  title: string;
  rows: ChunkFileRow[];
  selected: ChunkFileRow | null;
  onSelect: (row: ChunkFileRow) => void;
}) {
  return (
    <div className="px-1 py-1">
      <p className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <ul>
        {rows.map((row) => {
          const active =
            selected?.path === row.path && selected.visibility === row.visibility;
          return (
            <li key={`${row.visibility}:${row.path}`}>
              <button
                type="button"
                className={`w-full px-2 py-1.5 text-left text-xs ${
                  active ? "bg-primary/15" : "hover:bg-muted"
                }`}
                onClick={() => onSelect(row)}
              >
                <span className="block truncate font-mono text-foreground">{row.path}</span>
                <span className="text-[10px] text-muted-foreground">
                  {visLabel(row.visibility)} · {row.chunk_count} 块{" "}
                  {lineSpan(row)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
