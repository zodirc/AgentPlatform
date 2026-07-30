import type { SiteBrand } from "./siteBrand";

/** Inline product mark used in nav / Ops header (same asset as favicon). */
export function SiteBrandMark({
  site,
  className = "h-6 w-6",
}: {
  site: SiteBrand;
  className?: string;
}) {
  return (
    <img
      src={site.iconHref}
      alt=""
      width={24}
      height={24}
      className={`shrink-0 rounded-md ${className}`}
      aria-hidden
    />
  );
}
