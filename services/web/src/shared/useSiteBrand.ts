import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import {
  formatDocumentTitle,
  siteBrandForPath,
  type SiteBrand,
} from "./siteBrand";

function ensureIconLink(): HTMLLinkElement {
  let link = document.querySelector<HTMLLinkElement>("link[rel='icon']");
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.type = "image/svg+xml";
  return link;
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
    const link = ensureIconLink();
    if (link.getAttribute("href") !== site.iconHref) {
      link.href = site.iconHref;
    }
  }, [site, pageTitle]);

  return site;
}
