import { useState, type ReactNode } from "react";
import {
  opsConsolePath,
  opsEnvelopePath,
  opsHistoryPath,
  opsOfficialPath,
  opsRawPath,
  opsRetrievalPath,
  opsWritingPath,
} from "./opsPaths";
import { OpsOverviewSidebar } from "./OpsOverviewSidebar";
import { SiteBrandMark } from "../shared/SiteBrandMark";
import { SITE_OPS } from "../shared/siteBrand";
import { useSiteBrand } from "../shared/useSiteBrand";
import { ThemeSwitcher } from "../shared/theme/ThemeSwitcher";
import { Link, useLocation } from "react-router-dom";

export {
  opsConsolePath,
  opsEnvelopePath,
  opsHistoryPath,
  opsOfficialPath,
  opsRawPath,
  opsRetrievalPath,
  opsWritingPath,
  opsRunPath,
  secretFromOpsPath,
  turnIdFromSearch,
} from "./opsPaths";

function navActive(pathname: string, href: string): boolean {
  // Match section prefix so /official/<id> still highlights Bench.
  const base = href.replace(/\/$/, "");
  return pathname === base || pathname.startsWith(`${base}/`);
}

export function OpsShell({
  secret,
  title,
  subtitle,
  children,
  actions,
  wide: _wide = false,
}: {
  secret: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
  /** @deprecated All Ops pages share one width; kept for call-site compat. */
  wide?: boolean;
  /**
   * @deprecated Product sources ingestion is per-user/work; never show a global
   * strip on Ops (multi-tenant confusion). Kept as no-op for call-site compat.
   */
  showIngestion?: boolean;
}) {
  const { pathname } = useLocation();
  const [overviewOpen, setOverviewOpen] = useState(false);
  useSiteBrand(title);
  void _wide;

  const links = [
    { to: opsConsolePath(secret), label: "控制台" },
    { to: opsHistoryPath(secret), label: "历史结果" },
    { to: opsOfficialPath(secret), label: "Bench" },
    { to: opsWritingPath(secret), label: "写作评分" },
    { to: opsRetrievalPath(secret), label: "检索审计" },
    { to: opsEnvelopePath(secret), label: "模型信封" },
    { to: opsRawPath(secret), label: "Raw 快照" },
  ];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <header className="mb-6 border-b border-border pb-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <SiteBrandMark site={SITE_OPS} className="h-9 w-9 shrink-0 rounded-md" />
                <div>
                  <p className="text-sm font-semibold tracking-tight text-foreground">
                    {SITE_OPS.name}
                  </p>
                  <p className="text-[11px] text-muted-foreground">{SITE_OPS.tagline}</p>
                </div>
              </div>
              <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">
                {title}
              </h1>
              {subtitle ? (
                <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{subtitle}</p>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="主题与概览">
              <button
                type="button"
                onClick={() => setOverviewOpen(true)}
                className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
                title="主 Agent / 评测台 / 机器 / 容器"
              >
                配置概览
              </button>
              <ThemeSwitcher />
            </div>
          </div>

          <nav
            className="mt-4 flex flex-wrap gap-2 text-xs"
            aria-label="Ops 导航"
          >
            {links.map((link) => {
              const active = navActive(pathname, link.to);
              return (
                <Link
                  key={link.to}
                  to={link.to}
                  className={`rounded-md border px-2.5 py-1 transition-colors ${
                    active
                      ? "border-foreground/40 bg-foreground/5 font-medium text-foreground"
                      : "border-border text-foreground hover:bg-muted"
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>

          {actions ? (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              {actions}
            </div>
          ) : null}
        </header>
        {children}
      </main>
      {secret ? (
        <OpsOverviewSidebar
          secret={secret}
          open={overviewOpen}
          onClose={() => setOverviewOpen(false)}
        />
      ) : null}
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
