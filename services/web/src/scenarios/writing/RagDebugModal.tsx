import { X } from "lucide-react";
import { useEffect } from "react";
import type { WorkbenchState } from "../../shared/workbench/types";
import { RagEffectPage } from "./RagEffectPage";

type Props = {
  open: boolean;
  wb: WorkbenchState;
  onClose: () => void;
};

export function RagDebugModal({ open, wb, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="资料引用诊断"
      onClick={onClose}
    >
      <div
        className="flex h-[min(90vh,900px)] w-[min(96vw,720px)] flex-col overflow-hidden rounded-xl border border-input bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
          <p className="text-sm font-medium text-foreground">资料引用诊断</p>
          <button
            type="button"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
            title="关闭 (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
          <RagEffectPage wb={wb} embedded />
        </div>
      </div>
    </div>
  );
}
