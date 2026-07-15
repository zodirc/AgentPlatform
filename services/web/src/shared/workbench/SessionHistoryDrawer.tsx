import { useQuery } from "@tanstack/react-query";
import { listSessions, type SessionListItem } from "../api/client";
import { Button } from "../../components/ui/button";

type Props = {
  open: boolean;
  currentSessionId: string | null;
  onClose: () => void;
  onSelect: (sessionId: string) => void;
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
}: Props) {
  const q = useQuery({
    queryKey: ["sessions", "mine"],
    queryFn: () => listSessions(30),
    enabled: open,
    staleTime: 10_000,
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-md flex-col border-l border-slate-800 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-white">历史会话</h2>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 border-slate-700 px-2 text-xs"
            onClick={onClose}
          >
            关闭
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {q.isLoading ? (
            <p className="text-sm text-slate-500">加载中…</p>
          ) : null}
          {q.isError ? (
            <p className="text-sm text-rose-300">加载失败，请稍后重试</p>
          ) : null}
          {!q.isLoading && (q.data?.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-500">暂无历史会话</p>
          ) : null}
          <ul className="flex flex-col gap-2">
            {(q.data ?? []).map((item) => {
              const active = item.id === currentSessionId;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                      active
                        ? "border-sky-700 bg-sky-950/40"
                        : "border-slate-800 bg-slate-900/50 hover:border-slate-600"
                    }`}
                    onClick={() => onSelect(item.id)}
                  >
                    <div className="text-sm text-slate-100">{titleOf(item)}</div>
                    <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-slate-500">
                      <span>{formatTime(item.updated_at)}</span>
                      <span>{item.turn_count} 轮</span>
                      <span>{item.default_scenario_id}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </aside>
    </div>
  );
}
