import { useState } from "react";
import { Button } from "../../components/ui/button";
import { WriteFileDiffPanel } from "../../components/WriteFileDiffPanel";
import { releaseQuarantine, viewQuarantine } from "../../shared/api/quarantine";
import type { WriteFilePreview } from "../../shared/workbench/types";

export function ApprovalActionButtons({
  approveLabel,
  disabled,
  onApprove,
  onDeny,
  allowPrefix,
  onAllowPrefixChange,
  onAllowlist,
}: {
  approveLabel: string;
  disabled: boolean;
  onApprove: () => void;
  onDeny: () => void;
  allowPrefix?: string;
  onAllowPrefixChange?: (value: string) => void;
  onAllowlist?: () => void;
}) {
  return (
    <div className="flex shrink-0 flex-col items-end gap-1.5">
      {onAllowlist ? (
        <label className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
          前缀
          <input
            className="w-[9rem] rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[11px] text-foreground"
            value={allowPrefix ?? ""}
            onChange={(e) => onAllowPrefixChange?.(e.target.value)}
            maxLength={200}
            spellCheck={false}
          />
        </label>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button
          size="sm"
          className="bg-success text-success-foreground hover:bg-success/90"
          disabled={disabled}
          onClick={onApprove}
        >
          {approveLabel}
        </Button>
        {onAllowlist ? (
          <Button
            size="sm"
            variant="outline"
            className="border-success/40 text-success"
            disabled={disabled || !(allowPrefix ?? "").trim()}
            onClick={onAllowlist}
            title="此后以该前缀开头的命令不再询问"
          >
            加入允许列表
          </Button>
        ) : null}
        <Button size="sm" variant="outline" disabled={disabled} onClick={onDeny}>
          拒绝
        </Button>
      </div>
    </div>
  );
}

export function QuarantineNotice({
  events,
  onRelease,
}: {
  events: { payload?: Record<string, unknown> }[];
  onRelease: (text: string) => void;
}) {
  const ids = [
    ...new Set(
      events
        .map((event) => event.payload?.quarantine_id)
        .filter((item): item is string => typeof item === "string" && item.length > 0),
    ),
  ];
  const [open, setOpen] = useState<string>("");
  const [body, setBody] = useState("");
  if (ids.length === 0) return null;
  return (
    <div className="mb-3 rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs" data-testid="quarantine-notice">
      <p>有内容因疑似注入被隔离。可以查看，确认后再放行。</p>
      {ids.map((id) => (
        <div key={id} className="mt-2 flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void viewQuarantine(id).then((item) => {
                setOpen(id);
                setBody(item.body);
              });
            }}
          >
            查看隔离内容
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void releaseQuarantine(id).then((item) => {
                const text = item.body || "";
                setOpen(id);
                setBody(text);
                onRelease(text);
              });
            }}
          >
            放行到输入框
          </Button>
        </div>
      ))}
      {open && body ? (
        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-background p-2">{body}</pre>
      ) : null}
    </div>
  );
}

export function ChatApprovalCard({
  title,
  description,
  context,
  subagent,
  writePreview,
  command,
  argsText,
  approveLabel,
  disabled,
  onApprove,
  onDeny,
  allowPrefix,
  onAllowPrefixChange,
  onAllowlist,
}: {
  title: string;
  description: string;
  context: string;
  subagent: boolean;
  writePreview: WriteFilePreview | null;
  command: string;
  argsText: string;
  approveLabel: string;
  disabled: boolean;
  onApprove: () => void;
  onDeny: () => void;
  allowPrefix?: string;
  onAllowPrefixChange?: (value: string) => void;
  onAllowlist?: () => void;
}) {
  return (
    <div
      className="mb-4 max-w-[min(100%,48rem)] rounded-2xl rounded-tl-md border border-primary/40 bg-primary/10"
      data-testid="chat-approval-card"
      role="region"
      aria-label="待审批内容"
    >
      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-t-2xl border-b border-primary/30 bg-primary/20 px-4 py-2.5 backdrop-blur-sm">
        <p className="min-w-0 flex-1 text-sm font-medium text-primary">
          {title}
          {subagent ? (
            <span className="ml-2 text-xs font-normal text-primary/80">
              · 子任务
            </span>
          ) : null}
        </p>
        <ApprovalActionButtons
          approveLabel={approveLabel}
          disabled={disabled}
          onApprove={onApprove}
          onDeny={onDeny}
          allowPrefix={allowPrefix}
          onAllowPrefixChange={onAllowPrefixChange}
          onAllowlist={onAllowlist}
        />
      </div>
      <div className="p-4">
        <p className="mb-2 text-xs text-muted-foreground">{description}</p>
        {context ? (
          <p className="mb-2 text-xs text-foreground/80">{context}</p>
        ) : null}
        {writePreview ? (
          <WriteFileDiffPanel preview={writePreview} mode="approval" />
        ) : null}
        {command ? (
          <pre className="mt-2 max-h-48 overflow-auto rounded bg-background p-2 text-xs text-warning">
            $ {command}
          </pre>
        ) : null}
        {argsText ? (
          <pre className="mt-2 max-h-48 overflow-auto rounded bg-background p-2 text-xs">
            {argsText}
          </pre>
        ) : null}
      </div>
    </div>
  );
}
