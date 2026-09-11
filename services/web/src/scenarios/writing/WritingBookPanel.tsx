import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Trash2 } from "lucide-react";
import {
  discardWritingBook,
  downloadWorkspaceFile,
  fetchWritingBook,
  verdictWritingBook,
} from "../../shared/api/client";
import { workspaceEntryIcon } from "../agent/workspaceFileIcon";

type Props = {
  revision: string;
  selectedPath?: string | null;
  onSelectPath?: (path: string) => void;
  onOpenFile?: (path: string) => void;
  onCleared?: (paths: string[]) => void;
  onExecuteRetcon?: () => void;
};

export function WritingBookPanel({
  revision,
  selectedPath = null,
  onSelectPath,
  onOpenFile,
  onCleared,
  onExecuteRetcon,
}: Props) {
  const queryClient = useQueryClient();
  const bookQuery = useQuery({
    queryKey: ["writing-book", revision],
    queryFn: fetchWritingBook,
  });
  const discardMut = useMutation({
    mutationFn: discardWritingBook,
    onSuccess: (data) => {
      const paths = (bookQuery.data?.parts ?? [])
        .map((part) => part.path?.trim() || "")
        .filter(Boolean);
      queryClient.setQueryData(["writing-book", revision], data.book);
      void queryClient.invalidateQueries({ queryKey: ["writing-book"] });
      void queryClient.invalidateQueries({ queryKey: ["workspace-entries"] });
      onCleared?.(paths);
    },
  });
  const verdictMut = useMutation({
    mutationFn: verdictWritingBook,
    onSuccess: (data) => {
      queryClient.setQueryData(["writing-book", revision], data.book);
      void queryClient.invalidateQueries({ queryKey: ["writing-book"] });
    },
  });

  const book = bookQuery.data;

  const confirmDiscard = () => {
    if (discardMut.isPending) return;
    const ok = window.confirm("清空后这篇的大纲、正文和人物都没有了。确定？");
    if (!ok) return;
    discardMut.mutate();
  };

  return (
    <section className="border-b border-border p-3">
      {bookQuery.isError ? (
        <p className="text-xs text-destructive">作品读不出来</p>
      ) : bookQuery.isLoading || !book ? (
        <p className="text-xs text-muted-foreground">加载中…</p>
      ) : book.empty ? (
        <p className="text-xs text-muted-foreground">还没有稿。</p>
      ) : (
        <>
          <p className="mb-2 flex items-center gap-1.5 truncate text-sm font-medium text-foreground">
            {(book.consistency_flags?.length ?? 0) > 0 ? (
              <span
                className="inline-block size-1.5 shrink-0 rounded-full bg-destructive"
                title="一致性旗"
                aria-label="一致性旗"
              />
            ) : null}
            {book.title}
          </p>
          <ul className="space-y-1">
            {book.parts.map((part) => {
              const path = part.path?.trim() || "";
              const active = Boolean(path) && selectedPath === path;
              const fileName = path.split("/").pop() || `${part.label}.md`;
              const { Icon, className: iconClass } = workspaceEntryIcon(
                fileName,
                false,
              );
              return (
                <li key={part.key}>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      className={`min-w-0 flex-1 rounded px-2 py-1.5 text-left text-xs ${
                        active
                          ? "bg-primary/15 text-primary"
                          : "text-foreground/90 hover:bg-muted hover:text-foreground"
                      }`}
                      title={
                        path ? "双击打开编辑" : "这项不能当文件打开"
                      }
                      onClick={() => {
                        if (path) onSelectPath?.(path);
                      }}
                      onDoubleClick={() => {
                        if (path) onOpenFile?.(path);
                      }}
                    >
                      <span className="flex items-center gap-1.5">
                        <Icon
                          className={`size-3.5 shrink-0 ${iconClass}`}
                          aria-hidden
                        />
                        <span className="min-w-0 flex-1 truncate">
                          {part.label}
                        </span>
                        <span className="shrink-0 text-[10px] text-muted-foreground">
                          {part.chars} 字
                        </span>
                      </span>
                    </button>
                    {path ? (
                      <button
                        type="button"
                        className="shrink-0 rounded p-0.5 text-muted-foreground/70 hover:bg-muted hover:text-foreground"
                        title="下载"
                        aria-label={`下载 ${part.label}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          void downloadWorkspaceFile(path);
                        }}
                      >
                        <Download className="h-3 w-3" aria-hidden />
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-[10px] text-muted-foreground/80">
            单击选中 · 双击打开 · 编辑札记在下一章
          </p>
          {(() => {
            const hand = book.parts.find((part) => part.kind === "author_state");
            if (!hand?.text) return null;
            const rereadIdx = hand.text.indexOf("## 回读记");
            const stance = rereadIdx >= 0 ? hand.text.slice(0, rereadIdx).trim() : hand.text;
            const reread =
              rereadIdx >= 0 ? hand.text.slice(rereadIdx).replace(/^## 回读记\s*/, "").trim() : "";
            return (
              <div className="mt-3 space-y-1 rounded border border-border/70 px-2 py-1.5 text-[11px]">
                <p className="text-[10px] font-medium text-muted-foreground">作者手记</p>
                <p className="whitespace-pre-wrap text-foreground/90">{stance.slice(0, 800)}</p>
                {reread ? (
                  <>
                    <p className="pt-1 text-[10px] font-medium text-muted-foreground">回读记</p>
                    <p className="whitespace-pre-wrap text-foreground/90">{reread.slice(0, 400)}</p>
                  </>
                ) : null}
              </div>
            );
          })()}
          {(book.taste_marks?.length ?? 0) > 0 ? (
            <div className="mt-3 space-y-1 rounded border border-border/70 px-2 py-1.5 text-[11px]">
              <p className="text-[10px] font-medium text-muted-foreground">口味标记</p>
              {book.taste_marks!.slice(-8).map((mark, idx) => (
                <p key={`tm-${idx}`} className="text-foreground/90">
                  [{mark.kind || "?"}] {(mark.excerpt || "").slice(0, 60)}
                </p>
              ))}
            </div>
          ) : null}
          {book.reader_ledger || (book.promises?.length ?? 0) > 0 || (book.deferred?.length ?? 0) > 0 || book.identity ? (
            <div className="mt-3 space-y-1 rounded border border-border/70 px-2 py-1.5 text-[11px]">
              <p className="text-[10px] font-medium text-muted-foreground">账本</p>
              {Array.isArray(book.identity?.is) && book.identity.is.length > 0 ? (
                <p className="text-foreground/90">是：{book.identity.is.join("、")}</p>
              ) : null}
              {Array.isArray(book.identity?.is_not) && book.identity.is_not.length > 0 ? (
                <p className="text-foreground/90">不是：{book.identity.is_not.join("、")}</p>
              ) : null}
              {(book.reader_ledger?.waiting_for?.length ?? 0) > 0 ? (
                <p className="text-foreground/90">
                  读者在等：{book.reader_ledger!.waiting_for!.join("、")}
                </p>
              ) : null}
              {(book.deferred?.length ?? 0) > 0 ? (
                <p className="text-foreground/90">
                  还不决定：{book.deferred!.map((d) => d.question).filter(Boolean).join("、")}
                </p>
              ) : null}
            </div>
          ) : null}
          {(book.editor_flags?.length ?? 0) > 0 ? (
            <div className="mt-3 space-y-1 rounded border border-border/70 px-2 py-1.5 text-[11px]">
              <p className="text-[10px] font-medium text-muted-foreground">编辑旗</p>
              {book.editor_flags!.slice(0, 6).map((flag, idx) => (
                <p key={`ed-${idx}`} className="text-foreground/90">
                  [{flag.type || flag.severity}] {flag.where || ""} {flag.evidence || ""}
                </p>
              ))}
            </div>
          ) : null}
          {(book.retcon_pending?.length ?? 0) > 0 ? (
            <div className="mt-3 rounded border border-primary/40 px-2 py-1.5 text-[11px]">
              <p className="text-[10px] font-medium text-muted-foreground">retcon 待执行</p>
              {book.retcon_pending!.map((item, idx) => (
                <p key={`rc-${idx}`} className="mt-1 text-foreground/90">
                  {item.ch || "前文"}：{item.why || item.old_text?.slice(0, 40) || "改一段"}
                </p>
              ))}
              {onExecuteRetcon ? (
                <button
                  type="button"
                  className="mt-2 rounded border border-primary/50 px-2 py-0.5 text-primary hover:bg-primary/10"
                  onClick={() => onExecuteRetcon()}
                >
                  按此执行
                </button>
              ) : null}
            </div>
          ) : null}
        </>
      )}

      {book && ((book.wild_cards?.length ?? 0) > 0 || (book.consistency_flags?.length ?? 0) > 0) ? (
        <div className="mt-3 space-y-2">
          {(book.wild_cards ?? []).map((ch) => (
            <div
              key={`wild-${ch}`}
              className="rounded border border-border px-2 py-1.5 text-[11px]"
            >
              <p className="text-foreground/90">第 {ch} 章越轨</p>
              <div className="mt-1 flex gap-1">
                <button
                  type="button"
                  className="rounded border border-border px-1.5 py-0.5 hover:bg-muted disabled:opacity-50"
                  disabled={verdictMut.isPending}
                  onClick={() =>
                    verdictMut.mutate({
                      section_id: `ch${ch}`,
                      kind: "wild_card",
                      action: "keep",
                    })
                  }
                >
                  保留
                </button>
                <button
                  type="button"
                  className="rounded border border-destructive/40 px-1.5 py-0.5 text-destructive hover:bg-destructive/10 disabled:opacity-50"
                  disabled={verdictMut.isPending}
                  onClick={() =>
                    verdictMut.mutate({
                      section_id: `ch${ch}`,
                      kind: "wild_card",
                      action: "drop",
                    })
                  }
                >
                  砍掉
                </button>
              </div>
            </div>
          ))}
          {(book.consistency_flags ?? []).map((flag, idx) => {
            const sid = flag.section_id?.trim() || "ch";
            return (
              <div
                key={`flag-${sid}-${idx}`}
                className="rounded border border-destructive/30 px-2 py-1.5 text-[11px]"
              >
                <p className="text-destructive">{flag.text || flag.kind || "一致性旗"}</p>
                <div className="mt-1 flex gap-1">
                  <button
                    type="button"
                    className="rounded border border-border px-1.5 py-0.5 hover:bg-muted disabled:opacity-50"
                    disabled={verdictMut.isPending}
                    onClick={() =>
                      verdictMut.mutate({
                        section_id: sid,
                        kind: "consistency",
                        action: "keep",
                        detail: flag.text,
                      })
                    }
                  >
                    保留
                  </button>
                  <button
                    type="button"
                    className="rounded border border-destructive/40 px-1.5 py-0.5 text-destructive hover:bg-destructive/10 disabled:opacity-50"
                    disabled={verdictMut.isPending}
                    onClick={() =>
                      verdictMut.mutate({
                        section_id: sid,
                        kind: "consistency",
                        action: "drop",
                        detail: flag.text,
                      })
                    }
                  >
                    砍掉
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}

      {book && !book.empty ? (
        <button
          type="button"
          className="mt-3 inline-flex w-full items-center justify-center gap-1 rounded border border-destructive/40 px-2 py-1.5 text-[11px] text-destructive hover:bg-destructive/10 disabled:opacity-50"
          disabled={discardMut.isPending}
          onClick={confirmDiscard}
        >
          <Trash2 className="size-3" aria-hidden />
          {discardMut.isPending ? "正在清空…" : "清空"}
        </button>
      ) : null}
      {discardMut.isError ? (
        <p className="mt-1 text-[11px] text-destructive">清空失败，请重试</p>
      ) : null}
    </section>
  );
}
