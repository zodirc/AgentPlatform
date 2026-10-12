import { useEffect, useState } from "react";
import {
  fetchTurnRollback,
  revertTurnFile,
  rollbackTurn,
} from "../../shared/api/client";

/** 回合卡片上的回退：列出相对快照的改动，可整轮撤销或逐文件保留/撤销。 */
export function TurnRollbackBar({ turnId }: { turnId: string }) {
  const [stat, setStat] = useState("");
  const [note, setNote] = useState("工作区外的副作用无法撤销");
  const [files, setFiles] = useState<{ path: string; status?: string }[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    void fetchTurnRollback(turnId).then(
      (body) => {
        if (cancelled) return;
        setStat(String(body.stat ?? ""));
        setNote(String(body.note ?? "工作区外的副作用无法撤销"));
        const rows = body.changes?.length
          ? body.changes
          : (body.files ?? []).map((path) => ({ path }));
        setFiles(rows);
      },
      () => {
        if (!cancelled) setMessage("无法读取本轮改动");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [turnId]);

  if (!stat && files.length === 0 && !message) return null;

  return (
    <div className="mt-2 space-y-1 rounded-xl border border-border/70 bg-background/40 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
          onClick={() => {
            void rollbackTurn(turnId).then(
              (body) =>
                setMessage(
                  Array.isArray(body.restored)
                    ? `已撤销 ${body.restored.length} 个文件`
                    : "已撤销本轮",
                ),
              () => setMessage("撤销失败"),
            );
          }}
        >
          撤销本轮
        </button>
        <span className="text-[11px] text-muted-foreground">{note}</span>
      </div>
      {stat ? (
        <pre className="max-h-24 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-muted-foreground">
          {stat}
        </pre>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {files.map((file) => (
          <span key={file.path} className="inline-flex items-center gap-1">
            <button
              type="button"
              className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
              onClick={() =>
                setFiles((current) => current.filter((item) => item.path !== file.path))
              }
            >
              保留 {file.path}
            </button>
            <button
              type="button"
              className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
              onClick={() => {
                void revertTurnFile(turnId, file.path).then(
                  () => setMessage(`已撤销 ${file.path}`),
                  () => setMessage(`撤销失败 ${file.path}`),
                );
              }}
            >
              撤销 {file.path}
            </button>
          </span>
        ))}
      </div>
      {message ? <p className="text-[11px] text-muted-foreground">{message}</p> : null}
    </div>
  );
}
