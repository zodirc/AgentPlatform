import { Link } from "react-router-dom";
import { useTheme } from "../shared/theme/ThemeProvider";
import type { ThemeId } from "../shared/theme/theme";
import type { ReactNode } from "react";

export function opsConsolePath(secret: string): string {
  return `/ops/${encodeURIComponent(secret)}/test`;
}

export function opsRunPath(secret: string, runId: string): string {
  return `/ops/${encodeURIComponent(secret)}/test/runs/${runId}`;
}

export function secretFromOpsPath(pathname: string): string {
  const m = pathname.match(/^\/ops\/([^/]+)\//);
  return m ? decodeURIComponent(m[1]) : "";
}

export function OpsShell({
  secret,
  title,
  subtitle,
  children,
  actions,
}: {
  secret: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  const { theme, setTheme, themes, meta } = useTheme();

  return (
    <div className="min-h-screen bg-background text-foreground">
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <header className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-border pb-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
              Ops · 旁路评测
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
            {subtitle ? (
              <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Link
                to={opsConsolePath(secret)}
                className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted"
              >
                控制台
              </Link>
              {actions}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="主题">
            {themes.map((id: ThemeId) => {
              const selected = theme === id;
              return (
                <button
                  key={id}
                  type="button"
                  title={meta[id].description}
                  onClick={() => setTheme(id)}
                  className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                    selected
                      ? "border-primary/50 bg-primary/10 text-foreground ring-1 ring-primary/40"
                      : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  {meta[id].label}
                </button>
              );
            })}
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

export function statusClass(status: string): string {
  if (status === "pass") return "text-success";
  if (status === "fail") return "text-destructive";
  if (status === "running") return "text-warning";
  return "text-muted-foreground";
}
