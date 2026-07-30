import type { SiteBrand } from "./siteBrand";
import { AppBrandIcon, OpsBrandIcon } from "./BrandIcons";

/** Inline product mark used in nav / Ops header (same geometry as favicon). */
export function SiteBrandMark({
  site,
  className = "h-6 w-6",
}: {
  site: SiteBrand;
  className?: string;
}) {
  if (site.id === "ops") {
    return <OpsBrandIcon className={className} />;
  }
  return <AppBrandIcon className={className} />;
}
