import { Users, X } from "lucide-react";
import { useEffect } from "react";
import type { SubagentLive } from "../../shared/workbench/subagents";
import { statusLabel } from "../../shared/workbench/subagents";

/** Matches collab Profile subagent_types (docs/37) — not a full agent zoo. */
export const COLLAB_ROLES = [
  { id: "edit", label: "edit", hint: "写 / 改文件" },
  { id: "verify", label: "verify", hint: "验证 / 冒烟" },
  { id: "shell", label: "shell", hint: "命令" },
  { id: "explore", label: "explore", hint: "探索已有代码" },
] as const;

function roleBusy(
  roleId: string,
  subagents: SubagentLive[],
): SubagentLive | undefined {
  return subagents.find(
    (s) => s.agent_type === roleId && s.status === "running",
  );
}

function roleUsed(roleId: string, subagents: SubagentLive[]): boolean {
  return subagents.some((s) => s.agent_type === roleId);
}

export function collabTeamSummary(subagents: SubagentLive[]): string {
  const running = subagents.filter((s) => s.status === "running").length;
  const done = subagents.filter((s) => s.status === "completed").length;
  if (subagents.length === 0) return "尚未委派";
  const gap = collabMissingVerify(subagents);
  const base = `进行中 ${running} · 完成 ${done}`;
  return gap ? `${base} · 缺验证` : base;
}

/** edit finished but no verify/shell yet — soft orchestration gap. */
export function collabMissingVerify(subagents: SubagentLive[]): boolean {
  const sawEdit = subagents.some(
    (s) =>
      s.agent_type === "edit" &&
      (s.status === "completed" || s.status === "running"),
  );
  const sawCheck = subagents.some(
    (s) =>
      (s.agent_type === "verify" || s.agent_type === "shell") &&
      (s.status === "completed" || s.status === "running"),
  );
  return sawEdit && !sawCheck;
}

/** Compact entry — click opens the team overlay (like opening a workspace file). */
export function CollabTeamEntry({
  subagents,
  onOpen,
}: {
  subagents: SubagentLive[];
  onOpen: () => void;
}) {
  const running = subagents.filter((s) => s.status === "running").length;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 rounded-lg border border-border bg-card/40 px-3 py-2 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
      title="打开团队 / 子任务"
    >
      <Users className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-foreground/90">团队 / 子任务</p>
        <p className="truncate text-[11px] text-muted-foreground">
          {collabTeamSummary(subagents)}
          {running > 0 ? " · 点击查看" : " · 双击式子窗口"}
        </p>
      </div>
      {running > 0 ? (
        <span className="min-w-[1.25rem] rounded-full bg-warning/30 px-1.5 text-center text-[10px] font-medium text-foreground">
          {running}
        </span>
      ) : subagents.length > 0 ? (
        <span className="min-w-[1.25rem] rounded-full bg-primary/20 px-1.5 text-center text-[10px] font-medium text-primary">
          {subagents.length}
        </span>
      ) : (
        <span className="text-[11px] text-muted-foreground">打开</span>
      )}
    </button>
  );
}

type ViewerProps = {
  open: boolean;
  subagents: SubagentLive[];
  onClose: () => void;
  onOpenSubagent?: (subagentId: string) => void;
};

/** Overlay viewer — same pattern as WorkspaceFileViewer. */
export function CollabTeamViewer({
  open,
  subagents,
  onClose,
  onOpenSubagent,
}: ViewerProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const running = subagents.filter((s) => s.status === "running").length;
  const done = subagents.filter((s) => s.status === "completed").length;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="团队 / 子任务"
      onClick={onClose}
    >
      <div
        className="flex h-[min(90vh,720px)] w-[min(96vw,640px)] flex-col overflow-hidden rounded-xl border border-input bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
          <Users className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">团队 / 子任务</p>
            <p className="truncate text-xs text-muted-foreground">
              本回合工人 · edit / verify / shell / explore
              {subagents.length > 0
                ? ` · 进行中 ${running} · 完成 ${done}`
                : " · 尚未委派"}
              {collabMissingVerify(subagents) ? " · 缺验证" : ""}
            </p>
          </div>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
            title="关闭 (Esc)"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {subagents.length > 0 ? (
          <div className="shrink-0 border-b border-border px-4 py-2">
            <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              本回合用过
            </p>
            <div className="flex flex-wrap gap-1.5">
              {COLLAB_ROLES.filter((role) => roleUsed(role.id, subagents)).map(
                (role) => {
                  const busy = roleBusy(role.id, subagents);
                  return (
                    <span
                      key={role.id}
                      title={role.hint}
                      className={`rounded-md border px-2 py-0.5 text-[11px] ${
                        busy
                          ? "border-warning/50 bg-warning-muted text-foreground"
                          : "border-primary/30 bg-primary/10 text-foreground"
                      }`}
                    >
                      {role.label}
                      {busy ? " · 跑" : ""}
                    </span>
                  );
                },
              )}
            </div>
          </div>
        ) : null}

        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4">
          {subagents.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              复杂任务会按需派工人（常见：edit 实现 + verify/shell 冒烟；已有代码库才用
              explore）。简单问答不会派。
            </p>
          ) : (
            <ol className="space-y-2">
              {subagents.map((sub) => (
                <li key={sub.subagent_id}>
                  <button
                    type="button"
                    className="w-full rounded-lg border border-primary/25 bg-primary/5 px-3 py-2 text-left text-xs hover:border-primary/50 disabled:cursor-default"
                    onClick={() => {
                      onOpenSubagent?.(sub.subagent_id);
                      onClose();
                    }}
                    disabled={!onOpenSubagent}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-foreground">
                        {sub.agent_type}
                      </span>
                      <span className="text-muted-foreground">
                        {statusLabel(sub.status)}
                      </span>
                    </div>
                    {sub.task ? (
                      <p className="mt-1 line-clamp-2 text-muted-foreground">
                        {sub.task}
                      </p>
                    ) : null}
                    {sub.summary ? (
                      <p className="mt-1 line-clamp-3 text-foreground/80">
                        {sub.summary}
                      </p>
                    ) : null}
                    {onOpenSubagent ? (
                      <p className="mt-1 text-[10px] text-primary/80">
                        在聊天标签中打开只读详情
                      </p>
                    ) : null}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}
