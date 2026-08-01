import type { ReactNode } from "react";
import {
  opsConsolePath,
  opsEnvelopePath,
  opsHistoryPath,
  opsOfficialPath,
  opsRawPath,
  opsRetrievalPath,
} from "./opsPaths";
import { OpsIngestionStrip } from "./OpsIngestionStrip";
import { SiteBrandMark } from "../shared/SiteBrandMark";
import { SITE_OPS } from "../shared/siteBrand";
import { useSiteBrand } from "../shared/useSiteBrand";
import { useTheme } from "../shared/theme/ThemeProvider";
import type { ThemeId } from "../shared/theme/theme";
import { Link } from "react-router-dom";

export {
  opsConsolePath,
  opsEnvelopePath,
  opsHistoryPath,
  opsOfficialPath,
  opsRawPath,
  opsRetrievalPath,
  opsRunPath,
  secretFromOpsPath,
  turnIdFromSearch,
} from "./opsPaths";

export function OpsShell({
  secret,
  title,
  subtitle,
  children,
  actions,
  wide = false,
}: {
  secret: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
  /** Observation pages (official bench) need more horizontal room. */
  wide?: boolean;
}) {
  const { theme, setTheme, themes, meta } = useTheme();
  useSiteBrand(title);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <main
        className={`mx-auto px-4 py-8 sm:px-6 ${wide ? "max-w-7xl" : "max-w-5xl"}`}
      >
        <header className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-border pb-4">
          <div>
            <div className="flex items-center gap-3">
              <SiteBrandMark site={SITE_OPS} className="h-9 w-9 rounded-md" />
              <div>
                <p className="text-sm font-semibold tracking-tight text-foreground">
                  {SITE_OPS.name}
                </p>
                <p className="text-[11px] text-muted-foreground">{SITE_OPS.tagline}</p>
              </div>
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
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
              <Link
                to={opsHistoryPath(secret)}
                className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted"
              >
                历史结果
              </Link>
              <Link
                to={opsOfficialPath(secret)}
                className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted"
              >
                Bench
              </Link>
              <Link
                to={opsRetrievalPath(secret)}
                className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted"
              >
                检索审计
              </Link>
              <Link
                to={opsEnvelopePath(secret)}
                className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted"
              >
                模型信封
              </Link>
              <Link
                to={opsRawPath(secret)}
                className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted"
              >
                Raw 快照
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
        {secret ? <OpsIngestionStrip secret={secret} /> : null}
        {children}
      </main>
    </div>
  );
}

export function statusClass(status: string): string {
  if (status === "pass" || status === "completed") return "text-success";
  if (status === "fail" || status === "failed" || status === "cancelled") {
    return "text-destructive";
  }
  if (status === "running" || status === "queued" || status === "cancelling") return "text-warning";
  if (status === "skipped") return "text-muted-foreground";
  return "text-muted-foreground";
}
