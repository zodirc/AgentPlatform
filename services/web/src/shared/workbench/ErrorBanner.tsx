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
      className="flex items-start justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
    >
      <span>{error}</span>
      <button
        type="button"
        className="text-destructive hover:text-destructive"
        onClick={onDismiss}
        aria-label="关闭错误提示"
      >
        ✕
      </button>
    </div>
  );
}
