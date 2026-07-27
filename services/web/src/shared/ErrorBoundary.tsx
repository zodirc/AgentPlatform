import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  /** Optional pane label so nested boundaries read naturally. */
  label?: string;
};

type State = {
  error: Error | null;
};

/** I13: any uncaught render error previously blanked the whole app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught render error", error, info.componentStack);
  }

  private handleReset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error === null) {
      return this.props.children;
    }
    return (
      <div
        role="alert"
        className="flex min-h-[200px] flex-col items-center justify-center gap-3 p-8 text-center"
      >
        <p className="text-lg font-semibold">
          {this.props.label ?? "界面"}渲染出错了
        </p>
        <p className="max-w-md break-all text-sm text-muted-foreground">
          {this.state.error.message}
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
            onClick={this.handleReset}
          >
            重试
          </button>
          <button
            type="button"
            className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
            onClick={() => window.location.reload()}
          >
            刷新页面
          </button>
        </div>
      </div>
    );
  }
}
