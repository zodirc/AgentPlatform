import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteSession,
  listSessions,
  type SessionListItem,
} from "../api/client";
import { Button } from "../../components/ui/button";

type Props = {
  open: boolean;
  currentSessionId: string | null;
  onClose: () => void;
  onSelect: (sessionId: string) => void;
  /** Called after deleting the currently open session so the workbench can switch away. */
  onDeletedCurrent: () => void;
};

function titleOf(item: SessionListItem): string {
  const raw = item.title?.trim() || item.last_user_preview?.trim();
  if (!raw) return "空会话";
  return raw.length > 48 ? `${raw.slice(0, 48)}…` : raw;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function SessionHistoryDrawer({
  open,
  currentSessionId,
  onClose,
  onSelect,
  onDeletedCurrent,
}: Props) {
  const queryClient = useQueryClient();
  const q = useQuery({
    queryKey: ["sessions", "mine"],
    queryFn: () => listSessions(30),
    enabled: open,
    staleTime: 10_000,
  });

  const remove = useMutation({
    mutationFn: (sessionId: string) => deleteSession(sessionId),
    onSuccess: (_data, sessionId) => {
      queryClient.setQueryData<SessionListItem[]>(["sessions", "mine"], (prev) =>
        (prev ?? []).filter((row) => row.id !== sessionId),
      );
      void queryClient.invalidateQueries({ queryKey: ["sessions", "mine"] });
      if (sessionId === currentSessionId) {
        onDeletedCurrent();
      }
    },
  });

  if (!open) return null;

  const confirmDelete = (item: SessionListItem) => {
    const label = titleOf(item);
    const ok = window.confirm(
      `确定删除会话「${label}」？\n将永久清除该会话的聊天记录，不可恢复。`,
    );
    if (!ok) return;
    remove.mutate(item.id);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-overlay" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-md flex-col border-l border-border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">历史会话</h2>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 border-input px-2 text-xs"
            onClick={onClose}
          >
            关闭
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {q.isLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : null}
          {q.isError ? (
            <p className="text-sm text-destructive">加载失败，请稍后重试</p>
          ) : null}
          {remove.isError ? (
            <p className="mb-2 text-sm text-destructive">删除失败，请稍后重试</p>
          ) : null}
          {!q.isLoading && (q.data?.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">暂无历史会话</p>
          ) : null}
          <ul className="flex flex-col gap-2">
            {(q.data ?? []).map((item) => {
              const active = item.id === currentSessionId;
              const deleting = remove.isPending && remove.variables === item.id;
              return (
                <li key={item.id}>
                  <div
                    className={`flex items-stretch gap-1 rounded-lg border transition ${
                      active
                        ? "border-primary/50 bg-primary/15"
                        : "border-border bg-card/50 hover:border-input"
                    }`}
                  >
                    <button
                      type="button"
                      className="min-w-0 flex-1 px-3 py-2 text-left"
                      onClick={() => onSelect(item.id)}
                      disabled={deleting}
                    >
                      <div className="text-sm text-foreground">{titleOf(item)}</div>
                      <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                        <span>{formatTime(item.updated_at)}</span>
                        <span>{item.turn_count} 轮</span>
                        <span>{item.default_scenario_id}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      className="shrink-0 self-center px-2 py-2 text-[11px] text-muted-foreground hover:text-destructive disabled:opacity-40"
                      title="删除会话"
                      aria-label={`删除会话 ${titleOf(item)}`}
                      disabled={deleting || remove.isPending}
                      onClick={(e) => {
                        e.stopPropagation();
                        confirmDelete(item);
                      }}
                    >
                      {deleting ? "…" : "删除"}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </aside>
    </div>
  );
}
