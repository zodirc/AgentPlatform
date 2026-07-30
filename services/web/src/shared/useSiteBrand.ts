import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import {
  formatDocumentTitle,
  siteBrandForPath,
  type SiteBrand,
} from "./siteBrand";

/** Browsers cache favicons aggressively — remount the link with a bust token. */
function setFavicon(href: string) {
  document
    .querySelectorAll<HTMLLinkElement>("link[rel='icon'], link[rel='shortcut icon']")
    .forEach((el) => el.remove());
  const link = document.createElement("link");
  link.rel = "icon";
  link.type = "image/svg+xml";
  link.href = `${href}?v=${encodeURIComponent(href)}`;
  document.head.appendChild(link);
}

/**
 * Keep browser tab title + favicon aligned with main app vs Ops surface.
 * Pass ``pageTitle`` for page-specific segments (e.g. 评测历史).
 */
export function useSiteBrand(pageTitle?: string | null): SiteBrand {
  const { pathname } = useLocation();
  const site = siteBrandForPath(pathname);

  useEffect(() => {
    document.title = formatDocumentTitle(site, pageTitle);
    setFavicon(site.iconHref);
  }, [site, pageTitle]);

  return site;
}
