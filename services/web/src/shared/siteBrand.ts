/** Shared site naming + favicon marks for main workbench vs Ops console. */

export type SiteId = "app" | "ops";

export type SiteBrand = {
  id: SiteId;
  /** Product / tab name shown in chrome and document.title suffix. */
  name: string;
  /** Compact label for tight nav. */
  shortName: string;
  /** Favicon / mark asset (public/). */
  iconHref: string;
  /** One-line product blurb. */
  tagline: string;
};

export const SITE_APP: SiteBrand = {
  id: "app",
  name: "Agent Platform",
  shortName: "Agent",
  iconHref: "/favicon-app.svg",
  tagline: "写作 · Agent · 威胁情报工作台",
};

export const SITE_OPS: SiteBrand = {
  id: "ops",
  name: "Ops 评测台",
  shortName: "Ops",
  iconHref: "/favicon-ops.svg",
  tagline: "旁路观测 / 评测（不影响工作台热路径）",
};

export function isOpsPath(pathname: string): boolean {
  return pathname === "/ops" || pathname.startsWith("/ops/");
}

export function siteBrandForPath(pathname: string): SiteBrand {
  return isOpsPath(pathname) ? SITE_OPS : SITE_APP;
}

export function formatDocumentTitle(
  site: SiteBrand,
  pageTitle?: string | null,
): string {
  const page = (pageTitle || "").trim();
  return page ? `${page} · ${site.name}` : site.name;
}
