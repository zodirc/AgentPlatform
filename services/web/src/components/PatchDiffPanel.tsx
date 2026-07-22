import { lazy, Suspense, useState } from "react";
import { DiffViewerModal } from "./DiffViewerModal";
import { UnifiedDiffView } from "./UnifiedDiffView";

export type PatchArtifact = {
  type?: string;
  patch_id: string;
  path: string;
  old_text: string;
  new_text: string;
  summary?: string;
  status?: string;
};

const CodeMirror = lazy(() => import("@uiw/react-codemirror"));

type Props = {
  patch: PatchArtifact;
  onAccept: (patchId: string) => void;
  onReject: (patchId: string) => void;
  busy?: boolean;
};

export function PatchDiffPanel({ patch, onAccept, onReject, busy }: Props) {
  const status = patch.status ?? "pending";
  const isPending = status === "pending";
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <div className="rounded-lg border border-warning/40 bg-background/80 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-warning">{patch.path}</p>
          <p className="text-xs text-muted-foreground">
            {patch.summary ?? patch.patch_id}
          </p>
        </div>
        <span className="rounded bg-muted px-2 py-0.5 text-xs text-foreground/90">
          {status === "applied" ? "已落盘" : status}
        </span>
      </div>

      {status === "applied" ? (
        <p className="mb-2 text-[11px] text-success/90">
          写作模式已自动写入工作区（仍可对照下方 diff）
        </p>
      ) : null}

      <UnifiedDiffView oldText={patch.old_text} newText={patch.new_text} />

      <button
        type="button"
        className="mt-2 text-xs text-primary hover:underline"
        onClick={() => setModalOpen(true)}
      >
        在完整视图中打开（滚动 / 查找）
      </button>

      <details className="mt-2">
        <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
          并排全文（可选）
        </summary>
        <Suspense
          fallback={
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <pre className="max-h-56 overflow-auto rounded bg-card p-2 text-xs">
                {patch.old_text}
              </pre>
              <pre className="max-h-56 overflow-auto rounded bg-card p-2 text-xs">
                {patch.new_text}
              </pre>
            </div>
          }
        >
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            <div>
              <p className="mb-1 text-xs text-muted-foreground">旧文本</p>
              <CodeMirror
                value={patch.old_text}
                height="180px"
                readOnly
                basicSetup={{ lineNumbers: true, foldGutter: false }}
              />
            </div>
            <div>
              <p className="mb-1 text-xs text-muted-foreground">新文本</p>
              <CodeMirror
                value={patch.new_text}
                height="180px"
                readOnly
                basicSetup={{ lineNumbers: true, foldGutter: false }}
              />
            </div>
          </div>
        </Suspense>
      </details>

      {isPending && (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            className="rounded-lg bg-success px-3 py-1.5 text-sm text-success-foreground hover:bg-success/90 disabled:opacity-50"
            disabled={busy}
            onClick={() => onAccept(patch.patch_id)}
          >
            接受
          </button>
          <button
            type="button"
            className="rounded-lg border border-input px-3 py-1.5 text-sm text-foreground/90 disabled:opacity-50"
            disabled={busy}
            onClick={() => onReject(patch.patch_id)}
          >
            拒绝
          </button>
        </div>
      )}

      <DiffViewerModal
        open={modalOpen}
        path={patch.path}
        oldText={patch.old_text}
        newText={patch.new_text}
        subtitle={patch.summary ?? patch.path}
        onClose={() => setModalOpen(false)}
      />
    </div>
  );
}
