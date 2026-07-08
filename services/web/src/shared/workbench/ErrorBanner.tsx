type Props = {
  error: string | null;
  onDismiss: () => void;
};

export function ErrorBanner({ error, onDismiss }: Props) {
  if (!error) return null;
  return (
    <div
      role="alert"
      data-testid="workbench-error"
      className="flex items-start justify-between gap-3 rounded-lg border border-rose-800/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-200"
    >
      <span>{error}</span>
      <button
        type="button"
        className="text-rose-400 hover:text-rose-200"
        onClick={onDismiss}
        aria-label="关闭错误提示"
      >
        ✕
      </button>
    </div>
  );
}
